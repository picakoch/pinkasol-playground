"""Cut the pieces the experiences play, and write their manifest.

    tools/.venv/bin/python tools/cut.py

For each track and stem: the owner's picks (audio/picks.json, from
picker.html) when there are some, else the analyser's best candidates
(audio/analysis.json). Each piece is a short MP3 in audio/pieces/<track>/,
cut on bar lines from the stem, with TAIL seconds more after its end (the
ring-out when it stops). audio/pieces/manifest.json says, per piece, where
its loop is in the file: [0, loop_end] (sample-accurate once decoded).
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
OUT = AUDIO / "pieces"
TAIL = 1.5
PER_STEM = {"drums": 2, "bass": 2, "piano": 2, "synth": 2}
FREE = 1  # rubato phrases per stem


def cut(src, start, end, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start + TAIL:.3f}", "-i", str(src),
         "-af", "afade=t=in:d=0.004", "-ac", "2", "-ar", "44100", "-b:a", "128k", str(dest)],
        check=True,
    )


def main():
    analysis = json.loads((AUDIO / "analysis.json").read_text())
    picks_path = AUDIO / "picks.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    manifest = {"palette": {"blue": "#174596", "paper": "#fdfdfd", "orange": "#dc8d4e"}, "tracks": []}
    for track, a in analysis.items():
        entry = {k: a[k] for k in ("title", "key", "meter", "tempo", "bar_seconds")}
        entry["id"] = track
        entry["pieces"] = []
        for inst, candidates in a["pieces"].items():
            chosen = picks.get(track, {}).get(inst)
            if not chosen:
                barred = [c for c in candidates if not c.get("free")][: PER_STEM[inst]]
                free = [c for c in candidates if c.get("free")][:FREE]
                chosen = barred + free
            for n, c in enumerate(chosen):
                name = f"{inst}-{n + 1}.mp3"
                cut(AUDIO / "stems" / track / f"{inst}.mp3", c["start"], c["end"], OUT / track / name)
                entry["pieces"].append({
                    "inst": inst,
                    "file": f"{track}/{name}",
                    "loop_end": round(c["end"] - c["start"], 3),
                    "bars": None if c.get("free") else c["bars"],
                    "free": bool(c.get("free")),
                    "from": c["start"],
                })
        # Parts: every stem cut on the same bars, so a track's stems started
        # together play its passage as recorded (time-aligned, no full mix)
        entry["parts"] = []
        for k, part in enumerate(a.get("parts", [])):
            files = {}
            for inst in a["pieces"]:
                name = f"p{k + 1}-{inst}.mp3"
                cut(AUDIO / "stems" / track / f"{inst}.mp3", part["start"], part["end"], OUT / track / name)
                files[inst] = f"{track}/{name}"
            entry["parts"].append({
                "start": part["start"], "end": part["end"], "bars": part["bars"],
                "loop_end": round(part["end"] - part["start"], 3), "playing": part["playing"],
                "all": part.get("all", False), "files": files,
            })
        manifest["tracks"].append(entry)
        print(track, len(entry["pieces"]), "pieces,", len(entry["parts"]), "parts")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
