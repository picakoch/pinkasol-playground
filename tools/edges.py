"""Report parts whose playing instruments are quiet in their first/last bar
(level of the edge bar vs the part's median bar, and vs the stem's loud
level). tools/.venv/bin/python tools/edges.py"""
import json
from pathlib import Path
import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
A = json.loads((ROOT / "audio" / "analysis.json").read_text())
SR = 11025
bad = total = 0
for t, a in A.items():
    bars = np.array(a["bars"])
    levels = {}
    for inst in a["pieces"]:
        y, _ = librosa.load(ROOT / "audio" / "stems" / t / f"{inst}.mp3", sr=SR)
        r = np.array([np.sqrt(np.mean(y[int(s * SR):int(e * SR)] ** 2)) for s, e in zip(bars[:-1], bars[1:])])
        levels[inst] = r / (np.percentile(r, 95) or 1)
    for k, p in enumerate(a["parts"]):
        for inst in p["playing"]:
            lv = levels[inst][p["bar"]:p["bar"] + p["bars"]]
            med = np.median(lv)
            first, last = lv[0] / med, lv[-1] / med
            total += 1
            if min(first, last) < 0.6 or min(lv[0], lv[-1]) < 0.3:
                bad += 1
                print(f"{a['title']:10} part {k + 1} {inst:5} first {first:.2f} last {last:.2f} (abs {lv[0]:.2f} {lv[-1]:.2f})")
print(f"{bad} quiet edges in {total} instrument-parts")
