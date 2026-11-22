"""Cut the pieces the experiences play, and write their manifest.

    tools/.venv/bin/python tools/cut.py

For each track and stem: the owner's picks (audio/picks.json, from
picker.html) when there are some, else the analyser's best candidates
(audio/analysis.json). Each piece is a short MP3 in audio/pieces/<track>/,
cut on bar lines from the stem, with TAIL seconds more after its end (the
ring-out when it stops). audio/pieces/manifest.json says, per piece, where
its loop is in the file: [0, loop_end] (sample-accurate once decoded).
"""
import hashlib
import json
import re
import subprocess

import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
OUT = AUDIO / "pieces"
TAIL = 1.5
PER_STEM = {"drums": 2, "bass": 2, "piano": 2, "synth": 2}
FREE = 1  # rubato phrases per stem


SR = 44100
# Loops: the last XFADE seconds of the loop fade out while the audio just
# before the part's start fades in (equal power), so the jump from the end
# back to the start continues the music: no click at the seam. The start
# itself (the downbeat) is untouched. Bump LOOP_VERSION when the cut
# changes: it is in the file names, so tools/upload.mjs sends them again
XFADE = 0.04
# The file starts PREROLL seconds before the part (the manifest's `offset`):
# an MP3's very first samples are coded less precisely, so the loop must not
# restart there. The engine loops [offset, offset + loop_end]
PREROLL = 0.1
LOOP_VERSION = "xf40-pre100"


def pcm(src, start, dur):
    """Stereo float32 samples of src from start, dur seconds long."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.6f}", "-t", f"{dur:.6f}", "-i", str(src),
         "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def preroll(start):
    return round(min(PREROLL, start), 4)


def cut_loop(src, start, end, dest):
    """A part's file: PREROLL seconds of lead-in, [start, end] looping
    seamlessly (its end crossfaded into the audio before its start), then
    TAIL seconds."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    pre = preroll(start)
    x = pcm(src, start - pre, pre + (end - start) + TAIL)
    p = int(round(pre * SR))
    n = int(round((end - start) * SR))
    k = min(int(XFADE * SR), p, n // 4)
    if k > 0:
        t = np.linspace(0, 1, k, endpoint=False, dtype=np.float32)[:, None]
        fade_out, fade_in = np.cos(t * np.pi / 2), np.sin(t * np.pi / 2)
        x[p + n - k:p + n] = x[p + n - k:p + n] * fade_out + x[p - k:p] * fade_in
    body = x
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
         "-b:a", "128k", str(dest)],
        input=np.clip(body, -1, 1).astype(np.float32).tobytes(), check=True)


def cut(src, start, end, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start + TAIL:.3f}", "-i", str(src),
         "-af", "afade=t=in:d=0.004", "-ac", "2", "-ar", "44100", "-b:a", "128k", str(dest)],
        check=True,
    )


def ms(part):
    """A part whose bounds are to the ms (the analyser, the editor's
    snaps); off the grid (the editor's Libre step), they are to the µs"""
    return round(part["start"], 3) == part["start"] and round(part["end"], 3) == part["end"]


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
        # File names by content (p<k>-<inst>-<hash of the bounds>): a part
        # that changes gets a new name, so tools/upload.mjs (which reuses a
        # library file by name) sends it again. A file already cut with the
        # same bounds is kept as is
        entry["parts"] = []
        keep = set()
        for k, part in enumerate(a.get("parts", [])):
            files = {}
            for inst in a["pieces"]:
                # a time to the ms keeps its old key (the files cut before the
                # editor's Libre step keep their names); a free one, to the µs
                key = lambda x: f"{x:.3f}" if round(x, 3) == x else f"{x:.6f}"
                h = hashlib.sha1(f"{track}|{inst}|{key(part['start'])}|{key(part['end'])}|{LOOP_VERSION}".encode()).hexdigest()[:6]
                name = f"p{k + 1}-{inst}-{h}.mp3"
                if not (OUT / track / name).exists():
                    cut_loop(AUDIO / "stems" / track / f"{inst}.mp3", part["start"], part["end"], OUT / track / name)
                files[inst] = f"{track}/{name}"
                keep.add(name)
            entry["parts"].append({
                "start": part["start"], "end": part["end"], "bars": part["bars"],
                "loop_end": round(part["end"] - part["start"], 3 if ms(part) else 6), "offset": preroll(part["start"]),
                "playing": part["playing"],
                "all": part.get("all", False), "files": files,
            })
        # Part files no longer in the manifest (an old cut, the old names)
        for old in (OUT / track).glob("p*-*.mp3"):
            if re.match(r"p\d+-", old.name) and old.name not in keep:
                old.unlink()
        manifest["tracks"].append(entry)
        print(track, len(entry["pieces"]), "pieces,", len(entry["parts"]), "parts")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
