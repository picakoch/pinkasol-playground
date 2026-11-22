"""Put the owner's parts (audio/parts-edit.json, from parts.html) into
audio/analysis.json, without re-analysing the songs.

    tools/.venv/bin/python -W ignore tools/apply_edits.py

For each song in parts-edit.json: its parts become the edited ones, with
start/end, `playing` and `all` recomputed from its stems on the analysis'
bars (analyse.parts_from_edits, the same rules as the analyser). The
analyser's own parts stay in `parts_auto` (the editor's "back to the
analysis"). A song no longer in parts-edit.json gets its `parts_auto` back.
Then tools/cut.py cuts the files.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse  # noqa: E402  (same folder)

OUT = analyse.ROOT / "audio" / "analysis.json"


def main():
    data = json.loads(OUT.read_text())
    edits = analyse.load_edits()
    changed = 0
    for track, a in data.items():
        a.setdefault("parts_auto", [p for p in a["parts"] if not p.get("edited")] or a["parts"])
        if track not in edits:
            if any(p.get("edited") for p in a["parts"]):
                a["parts"] = a["parts_auto"]
                print(f"{track}: back to the analysis' parts")
                changed += 1
            continue
        folder = analyse.STEMS / track
        stems = {i: analyse.load(folder / f"{i}.mp3") for i in analyse.INSTRUMENTS if (folder / f"{i}.mp3").exists()}
        length = min(len(y) for y in stems.values())
        mix = sum(y[:length] for y in stems.values())
        bars = np.array(a["bars"])
        level = {i: analyse.rms_per_bar(y, bars) for i, y in stems.items()}
        peak = {i: (np.percentile(v, 95) or 1.0) for i, v in level.items()}
        norm = {i: np.minimum(v / peak[i], 1.2) for i, v in level.items()}
        a["parts"] = analyse.parts_from_edits(edits[track], stems, bars, norm, mix)
        print(f"{track}: {len(a['parts'])} edited parts "
              + " ".join(f"{p['bar']}+{p['bars']}{'*' if p['all'] else ''}[{''.join(i[0] for i in p['playing'])}]" for p in a["parts"]))
        changed += 1
    OUT.write_text(json.dumps(dict(sorted(data.items())), indent=1, ensure_ascii=False))
    print(f"{changed} songs updated in audio/analysis.json")


if __name__ == "__main__":
    main()
