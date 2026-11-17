"""Build the LinkedIn post images (1200x1200) as HTML, then screenshot them with headless Firefox.

usage: python3 images/make_images.py
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
RT = [json.loads(l) for l in open(HERE.parent / "runs/exp-final/roundtrip.jsonl", encoding="utf-8")]

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;'
         '6..72,600&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">')
BASE = """
:root{--bg:#f4f6f8;--paper:#fff;--ink:#1b232c;--muted:#5d6a78;--line:#d3dae2;--you:#1f5f8b;--ai:#c0622f;
--d:"Newsreader",Georgia,serif;--b:"Instrument Sans",system-ui,sans-serif;--m:"JetBrains Mono",monospace}
*{box-sizing:border-box}html,body{margin:0;width:1200px;height:1200px;overflow:hidden}
body{background:var(--bg);color:var(--ink);font:28px/1.4 var(--b);padding:84px 88px;display:flex;flex-direction:column}
.eyebrow{font:500 22px var(--m);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{font:600 64px/1.08 var(--d);margin:18px 0 0;letter-spacing:-.01em}
.foot{margin-top:auto;display:flex;justify-content:space-between;font:400 21px var(--m);color:var(--muted);
border-top:2px solid var(--line);padding-top:24px}
"""


def page(name, css, body):
    (HERE / f"{name}.html").write_text(
        f'<!doctype html><meta charset="utf-8">{FONTS}<style>{BASE}{css}</style><body>{body}'
        '<div class="foot"><span>45 round trips · Opus, Sonnet, Haiku</span><span>github.com/ssigurthorsson/ai-text-drift</span></div>',
        encoding="utf-8")


# A: the word that changed ---------------------------------------------------
page("1-should-will", """
.quote{margin:70px 0 0;font:400 46px/1.45 var(--d)}
.quote em{font-style:normal;color:var(--ai);font-weight:600;border-bottom:5px solid var(--ai)}
.quote ins{text-decoration:none;color:var(--you);font-weight:600;border-bottom:5px solid var(--you)}
.lab{font:500 20px var(--m);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:6px}
.big{margin-top:84px;display:flex;align-items:baseline;gap:28px}
.big b{font:600 150px/1 var(--d);color:var(--ai)}
.big span{font-size:34px;max-width:560px;line-height:1.3}
""", """
<span class="eyebrow">One word, 29 times out of 30</span>
<h1>I asked AI to write my email. It made a promise I never made.</h1>
<p class="quote"><span class="lab">I wrote</span>Running additional module tests before assembly
<ins>should</ins> address this.</p>
<p class="quote" style="margin-top:28px"><span class="lab">The AI email said</span>To address this,
<em>we will introduce</em> additional module tests before assembly.</p>
<div class="big"><b>29/30</b><span>AI-written emails turned my guess into a commitment.</span></div>
""")

# B: what survived (chart) ----------------------------------------------------
ROWS = [  # fact id, label, group
    ("1a", "The 4–6% fault rate", "Facts"),
    ("4a", "Anna takes over Reykjavík", "Facts"),
    ("3a", "Contract paused, not cancelled", "Facts"),
    ("1d", "The fix “should” work, not “will”", "Nuance"),
    ("2c", "Cause is the price change, not the product", "Nuance"),
    ("3b", "Why: switching delays Q2 production", "Nuance"),
]


def kept(style, fid):
    rows = [r for r in RT if r["style"] == style]
    return sum(r["topics_score"]["facts"][fid] == "kept" for r in rows), len(rows)


W, X0, BW, BH, GAP, ROWH = 1024, 0, 1024, 22, 5, 100
svg, y = [], 0
for i, (fid, label, group) in enumerate(ROWS):
    if i in (0, 3):
        svg.append(f'<text x="0" y="{y + 26}" class="grp">{"Survived" if i == 0 else "Lost"}</text>')
        y += 44
    svg.append(f'<text x="0" y="{y + 24}" class="lbl">{label}</text>')
    for j, (style, col) in enumerate((("none", "var(--you)"), ("fancy", "var(--ai)"))):
        k, n = kept(style, fid)
        by = y + 40 + j * (BH + GAP)
        w = max(BW * 0.82 * k / n, 6)
        svg.append(f'<rect x="0" y="{by}" width="{BW * .82:.0f}" height="{BH}" rx="4" fill="var(--line)" opacity=".45"/>')
        svg.append(f'<rect x="0" y="{by}" width="{w:.0f}" height="{BH}" rx="4" fill="{col}"/>')
        svg.append(f'<text x="{BW * .82 + 16:.0f}" y="{by + 18}" class="val">{k}/{n}</text>')
    y += ROWH
page("2-what-survived", """
.legend{display:flex;gap:36px;margin:26px 0 18px;font-size:24px}
.legend i{display:inline-block;width:22px;height:22px;border-radius:4px;vertical-align:-3px;margin-right:10px}
svg{overflow:visible}.grp{font:500 20px var(--m);letter-spacing:.08em;text-transform:uppercase;fill:var(--muted)}
.lbl{font:500 25px var(--b);fill:var(--ink)}.val{font:500 20px var(--m);fill:var(--ink)}
""", f"""
<span class="eyebrow">What the reader's AI summary kept</span>
<h1>The numbers survive. The “should” and the “because” don't.</h1>
<div class="legend"><span><i style="background:var(--you)"></i>My 4 plain sentences</span>
<span><i style="background:var(--ai)"></i>AI-polished email</span></div>
<svg width="{W}" height="{y}" viewBox="0 0 {W} {y}">{''.join(svg)}</svg>
""")

# C: length vs facts ----------------------------------------------------------
import statistics as st  # noqa: E402
words = {s: round(st.mean(r["email_words"] for r in RT if r["style"] == s)) for s in ("none", "fancy")}
facts = {s: st.mean(r["topics_score"]["kept"] for r in RT if r["style"] == s) for s in ("none", "fancy")}


def doc(n_lines, color):
    widths = [92, 100, 86, 97, 74, 100, 90, 60]
    return "".join(f'<i style="width:{widths[k % len(widths)]}%;background:{color}"></i>' for k in range(n_lines))


page("3-length", """
.cols{display:grid;grid-template-columns:1fr 1fr;gap:56px;margin-top:56px;align-items:end}
.doc{background:var(--paper);border:2px solid var(--line);border-radius:8px;padding:34px 30px;display:flex;
flex-direction:column;gap:13px}.doc i{display:block;height:12px;border-radius:6px;opacity:.55}
.n{font:600 76px/1 var(--d);margin-top:26px}.n small{font:400 26px var(--b);color:var(--muted);margin-left:8px}
.k{font-size:26px;margin-top:10px}.k b{font-family:var(--m);font-weight:500}
""", f"""
<span class="eyebrow">Same message, two lengths</span>
<h1>2.5× the words. Not one extra fact.</h1>
<div class="cols">
 <div><div class="doc">{doc(7, "var(--you)")}</div>
  <div class="n" style="color:var(--you)">{words['none']}<small>words, my note</small></div>
  <div class="k">Facts the reader got: <b>{facts['none']:.1f} of 13</b></div></div>
 <div><div class="doc">{doc(18, "var(--ai)")}</div>
  <div class="n" style="color:var(--ai)">{words['fancy']}<small>words, AI email</small></div>
  <div class="k">Facts the reader got: <b>{facts['fancy']:.1f} of 13</b></div></div>
</div>
""")

# D: the round trip, real text ------------------------------------------------
page("4-round-trip", """
.steps{display:grid;gap:18px;margin-top:40px}
.st{display:grid;grid-template-columns:210px 1fr;gap:28px;align-items:start;background:var(--paper);
border:2px solid var(--line);border-radius:8px;padding:22px 28px}
.st .who{font:500 20px/1.5 var(--m);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.st p{margin:0;font:400 28px/1.4 var(--d)}
.gone{display:block;margin-top:12px;font:400 22px/1.4 var(--m);color:var(--ai);border:2px dashed var(--ai);border-radius:6px;padding:8px 12px}.hl{background:#dbe8f2;padding:0 4px}
.arrow{text-align:center;font:400 26px var(--m);color:var(--muted);margin:-6px 0}
""", """
<span class="eyebrow">One sentence, one round trip</span>
<h1>Where the reason went missing</h1>
<div class="steps">
 <div class="st"><span class="who">I wrote</span><p>We will pause the Nordtak contract instead of cancelling it,
 <span class="hl">because switching suppliers mid-year would delay the Q2 production ramp by about two months.</span></p></div>
 <div class="arrow">↓ AI writes a polished email</div>
 <div class="st"><span class="who">AI email</span><p>Switching suppliers mid-year would delay our Q2 production ramp by
 approximately two months, and pausing allows us to protect that timeline while preserving flexibility.</p></div>
 <div class="arrow">↓ reader's AI summarizes it</div>
 <div class="st"><span class="who">AI summary</span><p>The Nordtak supplier contract will be paused rather than cancelled
 to protect the Q2 production ramp.<span class="gone">missing: switching would delay Q2 by about two months</span></p></div>
</div>
<p style="margin:30px 0 0;font-size:27px">The “because” was gone in <b>every</b> summary of an AI-written email (0 of 30).</p>
""")


# E: how the test works (descriptive diagram) ----------------------------------
page("5-how-it-works", """
h1{font-size:56px}
.flow{display:grid;grid-template-columns:1fr 56px 1fr 56px 1fr;align-items:stretch;margin-top:46px}
.box{background:var(--paper);border:2px solid var(--line);border-radius:8px;padding:22px 20px;display:flex;flex-direction:column;gap:10px}
.box .n{font:500 18px var(--m);color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
.box h3{margin:0;font:600 30px/1.15 var(--d)}.box p{margin:0;font-size:21px;line-height:1.4;color:var(--muted)}
.box.you{border-color:var(--you)}.box.you h3{color:var(--you)}.box.ai h3{color:var(--ai)}
.ar{display:flex;align-items:center;justify-content:center;font:400 40px var(--m);color:var(--muted)}
.styles{display:flex;flex-direction:column;gap:6px;margin-top:4px}
.styles span{font:500 18px var(--m);border:1.5px solid var(--line);border-radius:5px;padding:5px 8px;color:var(--ink)}
.judge{margin-top:26px;background:var(--paper);border:2px dashed var(--muted);border-radius:8px;padding:22px 26px;
display:grid;grid-template-columns:1fr 1fr;gap:6px 30px;font-size:21px}
.judge .t{grid-column:1/-1;font:600 28px var(--d);margin-bottom:6px}
.judge div::before{content:"·";color:var(--muted);margin-right:10px}
.res{margin-top:26px;display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.res div{border-top:4px solid var(--ai);padding-top:12px;font-size:21px;line-height:1.35}
.res b{display:block;font:600 44px/1.1 var(--d);color:var(--ai);margin-bottom:4px}
""", """
<span class="eyebrow">How the test works</span>
<h1>What survives when AI writes your email and AI reads it?</h1>
<div class="flow">
 <div class="box you"><span class="n">Step 1 · you</span><h3>4 plain sentences</h3>
  <p>A quality issue, churn, a paused contract, a new office lead. 101 words.</p></div>
 <div class="ar">→</div>
 <div class="box ai"><span class="n">Step 2 · writer</span><h3>3 ways to send it</h3>
  <div class="styles"><span>none · your text as-is</span><span>plain · AI, short</span><span>fancy · AI, polished</span></div></div>
 <div class="ar">→</div>
 <div class="box ai"><span class="n">Step 3 · AI reader</span><h3>Pulls out the main points</h3>
  <p>4 bullet points, like a busy recipient asking AI to summarize.</p></div>
</div>
<div class="judge"><span class="t">Step 4 · a judge model checks 13 facts in the summary</span>
 <div>numbers: 4–6% fault rate</div><div>certainty: “should”, not “will”</div>
 <div>names: Anna, Reykjavík, Nordtak</div><div>reasons: why the contract is paused</div>
 <div>decisions: pause, not cancel</div><div>who believes it: sales, not a fact</div></div>
<div class="res">
 <div><b>29/30</b>AI emails turned “should” into “will”</div>
 <div><b>0/30</b>summaries of AI emails kept the reason</div>
 <div><b>2.5×</b>longer fancy email, no extra facts</div>
</div>
""")

# F: GitHub social preview (1280x640) -----------------------------------------
page("social-preview", """
html,body{width:1280px;height:640px}body{padding:64px 80px}
h1{font-size:76px;margin-top:22px}.tag{font-size:30px;color:var(--muted);margin-top:22px;max-width:980px}
.tag em{font-style:normal;color:var(--ai);font-weight:600}.tag b{color:var(--you)}.foot{display:none}
.chips{margin-top:auto;display:flex;gap:14px;font:500 21px var(--m)}
.chips span{border:2px solid var(--line);border-radius:6px;padding:8px 14px;background:var(--paper)}
""", """
<span class="eyebrow">github · ai-text-drift</span>
<h1>AI writes the email.<br>AI reads the email.<br>What's left?</h1>
<p class="tag">A round-trip test with Claude: <b>“should”</b> becomes <em>“will”</em>, reasons disappear, and polish adds words, not facts.</p>
<div class="chips"><span>Opus · Sonnet · Haiku</span><span>13 facts judged</span><span>45 round trips + 100-step chains</span></div>
""")


def shoot():
    prof = HERE / ".ffprofile"  # snap Firefox can't read profiles in /tmp
    prof.mkdir(exist_ok=True)
    if True:
        for f in sorted(HERE.glob("*.html")):
            out = f.with_suffix(".png")
            subprocess.run(["firefox", "--headless", "--no-remote", "--profile", str(prof), "--window-size", "1280,640" if f.stem == "social-preview" else "1200,1200",
                            "--screenshot", str(out), f.resolve().as_uri()], check=True, capture_output=True, timeout=90)
            print("wrote", out)


if __name__ == "__main__":
    shoot()
