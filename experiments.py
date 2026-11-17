"""Hypothesis tests for the 'plain beats fancy' LinkedIn post.

H1/H2/H3  one round trip, styles: none (recipient AI reads the 4 sentences directly),
          plain email, fancy email. Judge scores the email AND the extracted topics.
H4        20-generation chain with plain emails (compare to the fancy 100-gen run).

usage: python experiments.py roundtrip --reps 5
       python experiments.py chain --generations 20
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from hvisl import (EXTRACTOR_SYSTEM, FACTS, MODELS, SEED, WRITER_SYSTEM, BudgetExceeded,
                   Ledger, bullets, call, judge_message)

WRITERS = {
    "fancy": WRITER_SYSTEM,
    "plain": (
        "You write internal company emails. Turn the bullet points you are given into a "
        "short, plain, direct business email to the whole company. No filler. "
        "Output only the email (subject line and body)."
    ),
}


def score(judge: dict) -> dict:
    s = judge["status_by_fact"]
    return {
        "kept": sum(v == "kept" for v in s.values()),
        "distorted": sum(v == "distorted" for v in s.values()),
        "missing": sum(v == "missing" for v in s.values()),
        "invented": len(judge["invented_claims"]),
        "facts": s,
    }


def one_trip(ledger, model_key, style, rep, judge_model):
    model = MODELS[model_key]
    seed = bullets(SEED)
    rec = {"model": model_key, "style": style, "rep": rep}
    if style == "none":
        # The sender's own sentences, sent as-is in an email (no AI writer).
        email = "Subject: Update\n\nHi all,\n\n" + "\n\n".join(SEED) + "\n\nThanks"
    else:
        email, _ = call(ledger, model, WRITERS[style], seed, "low")
        j_email, _ = judge_message(ledger, judge_model, email)
        rec["email_score"] = score(j_email)
    topics, _ = call(ledger, model, EXTRACTOR_SYSTEM, email, "low")
    j_topics, _ = judge_message(ledger, judge_model, topics)
    rec.update(email=email, email_words=len(email.split()), topics=topics,
               topics_score=score(j_topics), invented_claims=j_topics["invented_claims"])
    return rec


def roundtrip(args, ledger, out):
    jobs = [(m, s, r) for m in args.models for s in args.styles for r in range(args.reps)]
    path = out / ("roundtrip.jsonl" if len(args.styles) > 1 else f"roundtrip_{args.styles[0]}.jsonl")
    lock = threading.Lock()
    with ThreadPoolExecutor(args.workers) as pool, path.open("w", encoding="utf-8") as f:
        futs = {pool.submit(one_trip, ledger, m, s, r, MODELS[args.judge]): (m, s, r) for m, s, r in jobs}
        for fut in as_completed(futs):
            m, s, r = futs[fut]
            try:
                rec = fut.result()
            except BudgetExceeded as e:
                print(f"skip {m}/{s}/{r}: {e}")
                continue
            except Exception as e:  # noqa: BLE001
                print(f"FAILED {m}/{s}/{r}: {e}")
                continue
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            es = rec.get("email_score", {}).get("kept", "-")
            print(f"{m:6} {s:5} #{r}: email kept {es:>2}/13, topics kept {rec['topics_score']['kept']:>2}/13, "
                  f"{rec['email_words']:>3} words  (total ~${ledger.total_usd:.2f})", flush=True)


def chain(args, ledger, out):
    def run(model_key):
        model, topics = MODELS[model_key], bullets(SEED)
        with (out / f"chain_plain_{model_key}.jsonl").open("w", encoding="utf-8") as f:
            for g in range(1, args.generations + 1):
                try:
                    email, _ = call(ledger, model, WRITERS["plain"], topics, "low")
                    new, _ = call(ledger, model, EXTRACTOR_SYSTEM, email, "low")
                    j, _ = judge_message(ledger, MODELS[args.judge], new)
                except Exception as e:  # noqa: BLE001
                    print(f"[{model_key}] stopped at gen {g}: {e}")
                    return
                sc = score(j)
                f.write(json.dumps({"model": model_key, "generation": g, "email_words": len(email.split()),
                                    "email": email, "topics": new, "score": sc,
                                    "invented_claims": j["invented_claims"]}, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{model_key}] plain gen {g:>2}: kept {sc['kept']}/13, invented {sc['invented']} "
                      f"(total ~${ledger.total_usd:.2f})", flush=True)
                topics = new
    with ThreadPoolExecutor(len(args.models)) as pool:
        list(pool.map(run, args.models))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["roundtrip", "chain"])
    p.add_argument("--models", default="opus,sonnet,haiku")
    p.add_argument("--styles", default="none,plain,fancy")
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--generations", type=int, default=20)
    p.add_argument("--judge", default="opus", choices=MODELS)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--budget-usd", type=float, default=5.0)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    args.models = [m.strip() for m in args.models.split(",")]
    args.styles = args.styles.split(",")
    out = Path(args.out or Path("runs") / f"exp-{datetime.now():%Y%m%d-%H%M%S}")
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.budget_usd)
    print(f"{args.mode} -> {out}  budget ${args.budget_usd}")
    (roundtrip if args.mode == "roundtrip" else chain)(args, ledger, out)
    (out / f"usage_{args.mode}.json").write_text(json.dumps(
        {"total_usd": round(ledger.total_usd, 4), "by_model": ledger.by_model}, indent=2))
    print(f"\nTOTAL ~${ledger.total_usd:.2f} equiv")


if __name__ == "__main__":
    main()
