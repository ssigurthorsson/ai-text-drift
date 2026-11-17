"""Judge consistency check: re-score sampled messages from a run and compare verdicts.

usage: python judge_check.py runs/<dir> [--n 5] [--judge opus]
"""
import argparse
import json
import random
from pathlib import Path

from hvisl import FACTS, MODELS, Ledger, judge_message

p = argparse.ArgumentParser()
p.add_argument("run_dir")
p.add_argument("--n", type=int, default=5)
p.add_argument("--judge", default="opus", choices=MODELS)
p.add_argument("--budget-usd", type=float, default=0.5)
a = p.parse_args()

rows = [json.loads(l) for f in sorted(Path(a.run_dir).glob("*.jsonl")) for l in open(f, encoding="utf-8")]
random.seed(0)
sample = random.sample(rows, min(a.n, len(rows)))
ledger = Ledger(a.budget_usd)
agree = total = 0
for r in sample:
    j2, _ = judge_message(ledger, MODELS[a.judge], r["output_topics"])
    first = r["judge"]["status_by_fact"]
    diffs = {k: (first[k], j2["status_by_fact"][k]) for k in FACTS if first[k] != j2["status_by_fact"][k]}
    agree += len(FACTS) - len(diffs)
    total += len(FACTS)
    print(f"{r['chain']} gen {r['generation']}: {len(FACTS)-len(diffs)}/{len(FACTS)} agree", diffs or "")
print(f"\nAgreement: {agree}/{total} = {agree/total:.0%}   (cost ~${ledger.total_usd:.3f} equiv)")
