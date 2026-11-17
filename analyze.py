"""Summarise runs/exp-final: H1 style comparison, H2 where nuance dies, H3 length, H4 plain chain."""
import json
import statistics as st
import sys
from pathlib import Path

from hvisl import FACTS

D = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/exp-final")
rt = [json.loads(l) for l in open(D / "roundtrip.jsonl", encoding="utf-8")]
MODELS, STYLES = ["opus", "sonnet", "haiku"], ["none", "plain", "fancy"]


def m(xs):
    return f"{st.mean(xs):4.1f}" if xs else "  - "


print("== H1: facts kept (of 13) after one round trip, mean over reps ==")
print(f"{'':8}" + "".join(f"{s:>8}" for s in STYLES) + f"{'words p/f':>12}")
for mod in MODELS + ["ALL"]:
    rows = [r for r in rt if mod == "ALL" or r["model"] == mod]
    cells = [m([r["topics_score"]["kept"] for r in rows if r["style"] == s]) for s in STYLES]
    w = [m([r["email_words"] for r in rows if r["style"] == s]) for s in ("plain", "fancy")]
    print(f"{mod:8}" + "".join(f"{c:>8}" for c in cells) + f"{w[0]:>6}/{w[1]}")

print("\n== Invented claims per round trip ==")
for s in STYLES:
    print(f"{s:6} {m([r['topics_score']['invented'] for r in rt if r['style'] == s])}")

print("\n== H2: where facts die (kept in EMAIL vs kept in TOPICS), all models ==")
for s in ("plain", "fancy"):
    rows = [r for r in rt if r["style"] == s]
    print(f"{s:6} email {m([r['email_score']['kept'] for r in rows])}  -> topics {m([r['topics_score']['kept'] for r in rows])}")

print("\n== Per-fact survival in TOPICS (kept count / runs) ==")
print(f"{'fact':5}" + "".join(f"{s:>8}" for s in STYLES) + "  fact")
for k, v in FACTS.items():
    c = []
    for s in STYLES:
        rows = [r for r in rt if r["style"] == s]
        c.append(f"{sum(r['topics_score']['facts'][k] == 'kept' for r in rows)}/{len(rows)}")
    print(f"{k:5}" + "".join(f"{x:>8}" for x in c) + f"  {v[:60]}")

print("\n== Per-fact survival in the EMAIL itself (H2) ==")
for k in FACTS:
    c = []
    for s in ("plain", "fancy"):
        rows = [r for r in rt if r["style"] == s]
        c.append(f"{sum(r['email_score']['facts'][k] == 'kept' for r in rows)}/{len(rows)}")
    print(f"{k:5}" + "".join(f"{x:>8}" for x in c))

print("\n== H3: email length vs facts kept (written emails) ==")
xs = [r["email_words"] for r in rt if r["style"] != "none"]
ys = [r["topics_score"]["kept"] for r in rt if r["style"] != "none"]
if len(xs) > 2:
    print(f"Pearson r = {st.correlation(xs, ys):.2f}  (n={len(xs)})")
    for lo, hi in [(0, 120), (120, 180), (180, 250), (250, 9999)]:
        b = [y for x, y in zip(xs, ys) if lo <= x < hi]
        print(f"  {lo:>3}-{hi if hi < 9999 else '+':<4} words: kept {m(b)}  (n={len(b)})")

chains = sorted(D.glob("chain_plain_*.jsonl"))
if chains:
    print("\n== H4: plain chain vs fancy chain (facts kept at generation 1/5/10/20) ==")
    import csv
    fancy = list(csv.DictReader(open("runs/20261117-185032/metrics.csv")))
    for mod in MODELS:
        p = [json.loads(l) for l in open(D / f"chain_plain_{mod}.jsonl", encoding="utf-8")]
        pk = {r["generation"]: r["score"]["kept"] for r in p}
        fk = {int(r["generation"]): int(r["kept"]) for r in fancy if r["chain"] == mod}
        gens = [1, 5, 10, 20]
        print(f"{mod:7} plain " + " ".join(f"{pk.get(g, '-'):>3}" for g in gens)
              + "   fancy " + " ".join(f"{fk.get(g, '-'):>3}" for g in gens)
              + f"   plain inv@20 {p[-1]['score']['invented'] if p else '-'}")
