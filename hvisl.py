"""Hvísluleikur — a telephone-game drift experiment across Claude models.

Each generation:
  topics (4 bullets) --writer--> fancy email --extractor--> 4 topics --> next generation
A fixed judge model scores every generation against the original seed.

Agents run through the local `claude -p` CLI, i.e. on your Claude subscription login
(no API key). Each call is an isolated, tool-less, session-less headless run.

All token usage is logged per call. "usd" is the list-price equivalent the CLI reports;
on a subscription it is not billed, but it is a good proxy for how much of your usage
limit a run consumes. The run aborts once that equivalent reaches --budget-usd.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SEED = [
    "The main finding is that 4–6% of units show a fault in early testing after assembly. "
    "Running additional module tests before assembly should address this.",
    "Customer churn in the Nordic region is up, mostly among small accounts. "
    "The sales team thinks this is driven by the recent price change rather than the product.",
    "We will pause the Nordtak supplier contract instead of cancelling it, because switching "
    "suppliers mid-year would delay the Q2 production ramp by about two months.",
    "Anna Jónsdóttir will take over the Reykjavík office, but only after the current lead "
    "finishes the ISO certification audit.",
]

# Atomic facts the judge scores one by one.
FACTS = {
    "1a": "4–6% of units show a fault (a range, not a single number)",
    "1b": "The fault appears in early testing after assembly",
    "1c": "Proposed fix: additional module tests before assembly",
    "1d": "The fix is a suggestion that 'should' help, not a guarantee",
    "2a": "Customer churn is up in the Nordic region",
    "2b": "The churn is mostly among small accounts",
    "2c": "Suspected cause is the recent price change, not the product",
    "2d": "The cause is the sales team's belief, not an established fact",
    "3a": "The Nordtak supplier contract is paused, NOT cancelled",
    "3b": "Reason: switching suppliers mid-year would delay the Q2 production ramp",
    "3c": "The delay would be about two months",
    "4a": "Anna Jónsdóttir takes over the Reykjavík office",
    "4b": "Only after the current lead finishes the ISO certification audit",
}

# Deterministic text checks on the extracted topics (cross-check for the judge).
TEXT_CHECKS = {
    "range_4_6pct": r"4\s*(?:–|-|to)\s*6\s*(?:%|percent)",
    "two_months": r"\b(?:two|2)\s*months?\b",
    "q2": r"\bQ2\b|second quarter",
    "nordtak": r"Nordtak",
    "anna": r"Anna\s+J[óo]nsd[óo]ttir",
    "reykjavik": r"Reykjav[íi]k",
    "iso_audit": r"\bISO\b",
    "word_pause": r"\bpaus",
    "word_cancel": r"\bcancel(?!l?ing it)",  # 'instead of cancelling it' is fine
}

MODELS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
}

WRITER_SYSTEM = (
    "You are an executive communications writer. Turn the bullet points you are given "
    "into a polished, fancy, professional business email to the whole company. "
    "Output only the email (subject line and body)."
)

EXTRACTOR_SYSTEM = (
    "You read business emails and extract their main topics. Return exactly 4 bullet "
    "points, one short sentence each, starting with '- '. Output nothing else."
)

JUDGE_SYSTEM = (
    "You are a strict evaluator comparing a derived message to a list of original atomic facts. "
    "Score every fact id exactly once:\n"
    "- 'kept': the fact is stated with its meaning and specifics intact (paraphrase is fine).\n"
    "- 'distorted': the topic is present but something changed: a number/range altered or "
    "rounded, a hedge or attribution turned into certainty (e.g. 'should' -> 'will', "
    "'the sales team thinks' -> stated as fact), a decision changed (e.g. paused -> cancelled), "
    "a condition dropped, or order/causality reversed.\n"
    "- 'missing': the fact is absent.\n"
    "Judge only against the fact as written; do not reward extra detail. Also list concrete "
    "claims in the derived message that are NOT supported by the original facts."
)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string", "enum": list(FACTS)},
                    "status": {"type": "string", "enum": ["kept", "distorted", "missing"]},
                    "note": {"type": "string"},
                },
                "required": ["fact_id", "status", "note"],
                "additionalProperties": False,
            },
        },
        "invented_claims": {"type": "array", "items": {"type": "string"}},
        "similarity_1_to_10": {"type": "integer"},
    },
    "required": ["facts", "invented_claims", "similarity_1_to_10"],
    "additionalProperties": False,
}


class BudgetExceeded(Exception):
    pass


@dataclass
class Ledger:
    """Thread-safe token/cost accounting with a hard budget cap."""

    budget_usd: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    by_model: dict = field(default_factory=dict)
    total_usd: float = 0.0

    def check(self) -> None:
        with self.lock:
            if self.total_usd >= self.budget_usd:
                raise BudgetExceeded(f"Budget ${self.budget_usd:.2f} reached (${self.total_usd:.4f} spent)")

    def add(self, model: str, usage: dict, cost: float) -> None:
        inp = usage["input_tokens"] + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        out = usage["output_tokens"]
        with self.lock:
            row = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0, "usd": 0.0})
            row["calls"] += 1
            row["input"] += inp
            row["output"] += out
            row["usd"] += cost
            self.total_usd += cost


CLI_ENV = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}


def call(ledger: Ledger, model: str, system: str, user: str, effort: str, schema=None, attempts=3) -> tuple[str, dict]:
    """call_once with retries on transient CLI/API failures."""
    for i in range(attempts):
        try:
            return call_once(ledger, model, system, user, effort, schema)
        except (RuntimeError, subprocess.TimeoutExpired, KeyError):
            if i == attempts - 1:
                raise
            time.sleep(10 * (i + 1))


def call_once(ledger: Ledger, model: str, system: str, user: str, effort: str, schema=None) -> tuple[str, dict]:
    """One isolated headless Claude Code run on the subscription login."""
    ledger.check()
    cmd = [
        "claude", "-p", "--model", model, "--system-prompt", system, "--effort", effort,
        "--tools", "", "--strict-mcp-config", "--setting-sources", "",
        "--no-session-persistence", "--output-format", "json",
    ]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.time()
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=CLI_ENV, timeout=600)
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    if d.get("is_error"):
        raise RuntimeError(f"{model} error: {d.get('result') or d.get('api_error_status')}")
    usage, cost = d["usage"], d.get("total_cost_usd", 0.0)
    ledger.add(model, usage, cost)
    meta = {
        "model": model,
        "stop_reason": d.get("stop_reason"),
        "input_tokens": usage["input_tokens"] + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
        "output_tokens": usage["output_tokens"],
        "usd_equiv": round(cost, 6),
        "seconds": round(time.time() - t0, 2),
    }
    if d.get("stop_reason") == "refusal":
        raise RuntimeError(f"{model} refused")
    text = json.dumps(d["structured_output"]) if schema else d["result"].strip()
    return text, meta


def bullets(lines: list[str]) -> str:
    return "\n".join(f"- {l}" for l in lines)


def judge_message(ledger, judge_model, message: str) -> tuple[dict, dict]:
    facts_text = "\n".join(f"{k}: {v}" for k, v in FACTS.items())
    jtext, jmeta = call(
        ledger, judge_model, JUDGE_SYSTEM,
        f"ORIGINAL ATOMIC FACTS:\n{facts_text}\n\nDERIVED MESSAGE:\n{message}",
        "low", JUDGE_SCHEMA,
    )
    judge = json.loads(jtext)
    # Normalise to {fact_id: status}; anything the judge skipped counts as missing.
    judge["status_by_fact"] = {k: "missing" for k in FACTS}
    for f in judge["facts"]:
        judge["status_by_fact"][f["fact_id"]] = f["status"]
    return judge, jmeta


def text_checks(message: str) -> dict:
    return {k: bool(re.search(rx, message, re.IGNORECASE)) for k, rx in TEXT_CHECKS.items()}


def run_chain(ledger, name, model, judge_model, generations, effort, out_dir, log) -> list[dict]:
    rows = []
    topics = bullets(SEED)
    jsonl = (out_dir / f"{name}.jsonl").open("a", encoding="utf-8")
    for gen in range(1, generations + 1):
        try:
            email, wmeta = call(ledger, model, WRITER_SYSTEM, topics, effort)
            new_topics, emeta = call(ledger, model, EXTRACTOR_SYSTEM, email, effort)
            judge, jmeta = judge_message(ledger, judge_model, new_topics)
        except BudgetExceeded as e:
            log(f"[{name}] stopped at gen {gen}: {e}")
            break
        except Exception as e:  # noqa: BLE001 - keep other chains alive
            log(f"[{name}] FAILED at gen {gen}: {e}")
            break
        statuses = list(judge["status_by_fact"].values())
        checks = text_checks(new_topics)
        row = {
            "chain": name, "generation": gen,
            "kept": statuses.count("kept"), "distorted": statuses.count("distorted"),
            "missing": statuses.count("missing"), "invented": len(judge["invented_claims"]),
            "similarity": judge["similarity_1_to_10"],
            **{f"fact_{k}": v for k, v in judge["status_by_fact"].items()},
            **{f"text_{k}": int(v) for k, v in checks.items()},
            "email_words": len(email.split()), "topic_words": len(new_topics.split()),
            "tokens_in": wmeta["input_tokens"] + emeta["input_tokens"] + jmeta["input_tokens"],
            "tokens_out": wmeta["output_tokens"] + emeta["output_tokens"] + jmeta["output_tokens"],
            "usd_equiv": round(wmeta["usd_equiv"] + emeta["usd_equiv"] + jmeta["usd_equiv"], 6),
        }
        rows.append(row)
        jsonl.write(json.dumps({
            **row, "input_topics": topics, "email": email, "output_topics": new_topics,
            "judge": judge, "calls": {"writer": wmeta, "extractor": emeta, "judge": jmeta},
        }, ensure_ascii=False) + "\n")
        jsonl.flush()
        log(f"[{name}] gen {gen:>3}: kept {row['kept']}/{len(FACTS)}, distorted {row['distorted']}, invented {row['invented']}, "
            f"sim {row['similarity']}, ~${row['usd_equiv']:.4f} (total ~${ledger.total_usd:.4f})")
        topics = new_topics
    jsonl.close()
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default="opus,sonnet,haiku", help="comma list from: " + ",".join(MODELS))
    p.add_argument("--generations", type=int, default=10)
    p.add_argument("--judge", default="opus", choices=MODELS)
    p.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    p.add_argument("--budget-usd", type=float, default=2.0, help="stop once list-price-equivalent usage reaches this")
    args = p.parse_args()

    names = [m.strip() for m in args.models.split(",")]
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    ledger = Ledger(args.budget_usd)
    print_lock = threading.Lock()

    def log(msg):
        with print_lock:
            print(msg, flush=True)

    log(f"Run dir: {out_dir}  | models {names} | {args.generations} generations | budget ${args.budget_usd}")
    with ThreadPoolExecutor(len(names)) as pool:
        futures = [
            pool.submit(run_chain, ledger, n, MODELS[n], MODELS[args.judge],
                        args.generations, args.effort, out_dir, log)
            for n in names
        ]
        all_rows = [r for f in futures for r in f.result()]

    if all_rows:
        with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            w.writeheader()
            w.writerows(all_rows)

    usage = {"budget_usd": args.budget_usd, "total_usd": round(ledger.total_usd, 4), "by_model": ledger.by_model}
    (out_dir / "usage.json").write_text(json.dumps(usage, indent=2))

    print("\n=== Token usage ===")
    print(f"{'model':<20}{'calls':>6}{'input':>10}{'output':>10}{'USD-equiv':>10}")
    for m, r in ledger.by_model.items():
        print(f"{m:<20}{r['calls']:>6}{r['input']:>10}{r['output']:>10}{r['usd']:>10.4f}")
    print(f"{'TOTAL':<46}{ledger.total_usd:>10.4f}")
    print(f"\nPer-generation results: {out_dir}/metrics.csv ; full text: {out_dir}/<chain>.jsonl")


if __name__ == "__main__":
    main()
