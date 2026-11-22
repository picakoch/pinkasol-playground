"""Find bars and candidate pieces in each track's stems.

    tools/.venv/bin/python tools/analyse.py            # all tracks
    tools/.venv/bin/python tools/analyse.py 01_Rototo  # one

Reads audio/stems/<track>/{drums,piano,synth,bass}.mp3 and stems.json
(Moises' key/bpm), writes audio/analysis.json: beat and bar times (from the
drums stem: the stems are time-aligned), and per stem the best candidate
pieces, start/end on bar lines:
- drums, bass: loops (2 or 4 bars) that are loud, steady, and whose seam
  (end -> start) sounds like the bar it replaces
- piano, synth: phrases (4 bars) where the stem is present and the others
  are quiet-ish (more "solo")
Scores are relative within a track; the picker page (picker.html) is where
the ear decides.
"""
import json
import sys
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
STEMS = ROOT / "audio" / "stems"
SR = 22050
HOP = 512
INSTRUMENTS = ["drums", "bass", "piano", "synth"]


def load(path):
    y, _ = librosa.load(path, sr=SR, mono=True)
    return y


def bars_from_beats(beats_t, onset_low, times, meter):
    """Group beats by the meter (4, 13...), choosing the phase whose 'one'
    has the most low-end onset (the kick)."""
    strength = np.interp(beats_t, times, onset_low)
    phase = int(np.argmax([strength[k::meter].mean() for k in range(meter)]))
    return beats_t[phase::meter]


def rms_per_bar(y, bars):
    out = []
    for a, b in zip(bars[:-1], bars[1:]):
        seg = y[int(a * SR):int(b * SR)]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    return np.array(out)


def chroma_onset_per_bar(y, bars):
    """A small fingerprint per bar: onset envelope folded into 16 steps,
    plus mean chroma. Used to judge a loop's seam."""
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    fps = SR / HOP
    prints = []
    for a, b in zip(bars[:-1], bars[1:]):
        i, j = int(a * fps), max(int(b * fps), int(a * fps) + 16)
        steps = np.array_split(env[i:j], 16)
        rhythm = np.array([s.mean() if len(s) else 0 for s in steps])
        rhythm = rhythm / (np.linalg.norm(rhythm) + 1e-9)
        c = chroma[:, i:j].mean(axis=1)
        c = c / (np.linalg.norm(c) + 1e-9)
        prints.append(np.concatenate([rhythm, 0.5 * c]))
    return np.array(prints)


def peak_level(y, frame=SR // 20):
    r = np.sqrt(np.mean(y[: len(y) // frame * frame].reshape(-1, frame) ** 2, axis=1))
    return float(np.percentile(r, 95)) or 1.0


def free_phrases(y, until, peak, frame=SR // 20):
    """Pieces of a rubato part (no bars): cut at the stem's quiet points,
    3-12 s, played once rather than looped."""
    part = y[: int(until * SR)]
    r = np.sqrt(np.mean(part[: len(part) // frame * frame].reshape(-1, frame) ** 2, axis=1)) / peak
    quiet = np.where(r < 0.12)[0]
    cuts = [0] + [int(i) for i in quiet] + [len(r)]
    out, a = [], 0
    for c in cuts[1:]:
        secs = (c - a) * frame / SR
        if secs < 3:
            continue
        if secs > 12:
            c = a + int(12 * SR / frame)
            c = a + int(np.argmin(r[a + int(3 * SR / frame):c])) + int(3 * SR / frame)
        seg = r[a:c]
        if len(seg) and seg.mean() > 0.3:
            out.append({"free": True, "start": round(a * frame / SR, 3), "end": round(c * frame / SR, 3),
                        "score": round(float(seg.mean()), 3)})
        a = c
    return sorted(out, key=lambda p: -p["score"])[:3]


def pick(scores, length, count=4):
    """Best non-overlapping windows."""
    order = np.argsort(scores)[::-1]
    chosen = []
    for i in order:
        if not np.isfinite(scores[i]):
            continue
        if all(abs(i - c) >= length for c in chosen):
            chosen.append(int(i))
        if len(chosen) == count:
            break
    return chosen



def drum_prints(y, bars):
    """Per bar: the drums' pattern, onsets in 3 bands (kick, snare/toms,
    cymbals) over 16 steps, normalised."""
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=hop))
    f = librosa.fft_frequencies(sr=SR, n_fft=1024)
    env = [np.maximum(0, np.diff(np.log1p(S[(f >= lo) & (f < hi)].sum(0)), prepend=0))
           for lo, hi in ((20, 150), (150, 2000), (2000, 11000))]
    fps = SR / hop
    out = []
    for a, b in zip(bars[:-1], bars[1:]):
        i, j = int(a * fps), max(int(b * fps), int(a * fps) + 16)
        v = np.concatenate([[x.mean() if len(x) else 0 for x in np.array_split(e[i:j], 16)] for e in env])
        out.append(v / (np.linalg.norm(v) + 1e-9))
    return np.array(out)


def snapper(mix):
    """Moves a time to the strongest attack of the mix within ±70 ms."""
    hop = 128
    env = librosa.onset.onset_strength(y=mix, sr=SR, hop_length=hop)
    fps = SR / hop
    floor = np.percentile(env, 90) * 0.5

    def snap(t):
        i = int(round(t * fps))
        w = int(0.07 * fps)
        a, b = max(0, i - w), min(len(env), i + w + 1)
        if b <= a:
            return t
        k = a + int(np.argmax(env[a:b]))
        return k / fps if env[k] >= floor else t
    return snap


def select_parts(stems, bars, norm, mix, duration, bar_s):
    n = len(bars) - 1
    long_ = min((4, 8), key=lambda k: abs(k * bar_s - 16))
    lengths = (long_, long_ // 2)
    has_drums = "drums" in stems
    dfp = drum_prints(stems["drums"], bars) if has_drums else None
    drms = rms_per_bar(stems["drums"], bars) if has_drums else None

    def plays(i, s, L):
        return float((norm[i][s:s + L] > 0.25).mean()) >= 0.75

    def presence(i, s, L):
        return float((norm[i][s:s + L] > 0.25).mean())

    # How well window (s, L) loops: 0..~3, None when it can't
    quality = {}

    def q(s, L):
        if (s, L) in quality:
            return quality[(s, L)]
        if s < 0 or s + L > n:
            return None
        score = 0.0
        if has_drums and plays("drums", s, L):
            win = dfp[s:s + L]
            med = np.median(win, axis=0)
            med /= np.linalg.norm(med) + 1e-9
            sims = win @ med
            lv = drms[s:s + L] / (np.median(drms[s:s + L]) + 1e-9)
            # the bar after the loop sounds like its first bar
            seam = float(dfp[s + L] @ dfp[s]) if s + L < n else float(win[-1] @ med)
            if sims.min() < 0.72 or lv.min() < 0.6:
                quality[(s, L)] = None
                return None
            score += 2 * sims.min() + 0.5 * lv.min() + 0.5 * seam
        # every instrument that plays is really there in the FIRST and the
        # LAST bar (no quiet start or tail: a synth coming in late, a piano
        # phrase ending early), and doesn't drop out in between
        for i in stems:
            if not plays(i, s, L):
                continue
            win = norm[i][s:s + L]
            lv = win / (np.median(win) + 1e-9)
            if min(lv[0], lv[-1]) < 0.6 or min(win[0], win[-1]) < 0.25:
                quality[(s, L)] = None
                return None
            if i != "drums":
                score += 0.3 * min(1.0, lv.min())
        quality[(s, L)] = score
        return score

    def overlaps(s, L, chosen):
        return any(s < c + cl and c < s + L for c, cl in chosen)

    def best(insts, chosen, zone=None, need=0.75):
        """The best looping window where `insts` play (8 bars preferred)."""
        found = []
        for L in lengths:
            for s in (zone if zone is not None else range(0, n - L + 1)):
                s = int(s)
                if s + L > n or overlaps(s, L, chosen):
                    continue
                pres = min(presence(i, s, L) for i in insts) if insts else 1.0
                if pres < need:
                    continue
                qq = q(s, L)
                if qq is None:
                    continue
                act = np.mean([norm[i][s:s + L].mean() for i in stems])
                found.append((pres + 0.25 * qq + 0.2 * act + (0.15 if L == long_ else 0), s, L))
            if found and L == long_ and max(found)[0] > 1.6:
                break  # a good 8-bar loop: no need to look at 4
        return max(found)[1:] if found else None

    chosen, targets = [], {}
    everyone = best(list(stems), chosen)
    if everyone:
        chosen.append(everyone)
        targets[everyone] = list(stems)
    elif "bass" in stems and "synth" in stems:
        # Rototo, Arroyoyo, Noisette, Pinkasol: bass and synth never together
        for drop in ("synth", "bass"):
            insts = [i for i in stems if i != drop]
            w = best(insts, chosen)
            if w:
                chosen.append(w)
                targets[w] = insts
    # One per stretch of the song
    count = int(np.clip(round(duration / 45), 4, 7))
    for zone in np.array_split(np.arange(0, n), count):
        if any(zone[0] <= c < zone[-1] + 1 for c, _ in chosen):
            continue
        w = best([], chosen, zone=zone, need=0)
        if w:
            chosen.append(w)
    # Every instrument: up to two parts where it really plays
    for i in stems:
        for _ in range(2):
            if sum(plays(i, c, cl) for c, cl in chosen) >= 2:
                break
            w = best([i], chosen)
            if not w:
                break
            chosen.append(w)

    snap = snapper(mix)
    parts = []
    for s, L in sorted(chosen):
        a, b = snap(float(bars[s])), snap(float(bars[s + L]))
        parts.append({
            "bar": s, "bars": L, "start": round(a, 3), "end": round(b, 3),
            "playing": [i for i in stems if plays(i, s, L)],
            "all": (s, L) in targets and all(plays(i, s, L) for i in targets[(s, L)]),
            "loop": round(q(s, L) or 0, 2),
        })
    return parts


EDITS = ROOT / "audio" / "parts-edit.json"


def load_edits():
    """The owner's parts (parts.html): { track: [ {bar, bars}, ... ] }."""
    return json.loads(EDITS.read_text()) if EDITS.exists() else {}


def parts_from_edits(edited, stems, bars, norm, mix):
    """The owner's parts, as select_parts() gives them. `bar` and `bars` may
    be fractions of a bar (quarter bars, the editor's snap): a position
    inside a bar is interpolated between its bar line and the next (beats).
    start/end snapped to the attacks (±70 ms), `playing` by the same strict
    rule (present in 3/4 of the bars it covers, a bar counted when at least
    half covered), `all` when every stem plays (or, in a song where bass and
    synth never meet, every stem but one of those two), unless the owner
    forced it (`star`: true/false)."""
    n = len(bars) - 1
    bars = np.asarray(bars, dtype=float)
    snap = snapper(mix)
    q = lambda x: round(float(x) * 4) / 4

    def time_at(x):
        k = int(min(max(np.floor(x), 0), n - 1))
        return float(bars[k] + (x - k) * (bars[k + 1] - bars[k]))

    def covered(s, L):
        out = []
        for k in range(int(np.floor(s)), int(np.ceil(s + L))):
            if 0 <= k < n and min(k + 1, s + L) - max(k, s) >= 0.5:
                out.append(k)
        return out or [int(min(max(np.floor(s), 0), n - 1))]

    def plays(i, ks):
        return float((norm[i][ks] > 0.25).mean()) >= 0.75

    parts = []
    for e in sorted(edited, key=lambda e: (float(e["bar"]), float(e["bars"]))):
        s = min(max(q(e["bar"]), 0.0), n - 0.25)
        L = min(max(q(e["bars"]), 0.25), n - s)
        ks = covered(s, L)
        playing = [i for i in stems if plays(i, ks)]
        everyone = len(playing) == len(stems)
        if not everyone and "bass" in stems and "synth" in stems:
            others = [i for i in stems if i not in ("bass", "synth")]
            everyone = all(i in playing for i in others) and (("bass" in playing) != ("synth" in playing))
        part = {
            "bar": s if s % 1 else int(s), "bars": L if L % 1 else int(L),
            "start": round(snap(time_at(s)), 3), "end": round(snap(time_at(s + L)), 3),
            "playing": playing, "all": everyone, "all_auto": everyone, "edited": True,
        }
        if isinstance(e.get("star"), bool):
            part["star"] = e["star"]
            part["all"] = e["star"]
        parts.append(part)
    return parts


def analyse(track, meta):
    folder = STEMS / track
    stems = {i: load(folder / f"{i}.mp3") for i in INSTRUMENTS if (folder / f"{i}.mp3").exists()}
    drums = stems["drums"]

    # Beats from the whole mix (all stems), not the drums alone: parts
    # without drums (a bass intro, a piano coda) need bars too
    length = min(len(y) for y in stems.values())
    mix = sum(y[:length] for y in stems.values())
    # stems.json: bpm (Moises', corrected by ear), meter (Malavista: 13),
    # free_until (Exit B: a rubato opening, no bars before it)
    meter = meta.get("meter", 4)
    free_until = float(meta.get("free_until", 0))
    skip = int(free_until * SR)
    # bpm_by_ear: the owner's tempo, imposed (Exit B's tracker settles on 86)
    fixed = {"bpm": float(meta["bpm"]), "tightness": 400} if meta.get("bpm_by_ear") else {}
    tempo, beats = librosa.beat.beat_track(y=mix[skip:], sr=SR, hop_length=HOP, start_bpm=meta["bpm"],
                                           units="time", **fixed)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beats) + free_until
    low = librosa.onset.onset_strength(y=drums, sr=SR, hop_length=HOP, fmax=150, n_mels=32)
    times = librosa.times_like(low, sr=SR, hop_length=HOP)
    bars = bars_from_beats(beats, low, times, meter)
    # Then out to both ends of the track at the median bar length (where the
    # tracker found no beat, e.g. a free intro), never into the rubato part
    bar_len = float(np.median(np.diff(bars)))
    duration = length / SR
    before = np.arange(bars[0] - bar_len, free_until - 1e-6, -bar_len)[::-1]
    after = np.arange(bars[-1] + bar_len, duration - bar_len / 2, bar_len)
    bars = np.concatenate([before, bars, after])
    n = len(bars) - 1

    level = {i: rms_per_bar(y, bars) for i, y in stems.items()}
    # 95th percentile, not the max: one loud bar mustn't make the rest look quiet
    peak = {i: (np.percentile(v, 95) or 1.0) for i, v in level.items()}
    norm = {i: np.minimum(v / peak[i], 1.2) for i, v in level.items()}

    # Pieces of 4-8 s whatever the meter: bars of 2 s -> 4 bars, of 3.4 s
    # (Malavista's 13/4) -> 2 bars
    bar_s = float(np.median(np.diff(bars)))
    loop_bars = min((1, 2, 4), key=lambda k: abs(k * bar_s - 8))
    phrase_bars = max(2, loop_bars)
    pieces = {}
    for inst, y in stems.items():
        lv = norm[inst]
        if inst in ("drums", "bass"):
            fp = chroma_onset_per_bar(y, bars)
            L = loop_bars
            scores = np.full(n, -np.inf)
            # a quiet stem (a bass under the piano) still gets candidates
            floor = 0.35 if (lv > 0.35).sum() > 2 * L else 0.1
            for s in range(0, n - L):
                win = lv[s:s + L]
                if win.min() < floor:
                    continue
                steady = 1 - win.std() / (win.mean() + 1e-9)
                # the seam: the bar after the loop should resemble its first bar
                seam = float(fp[s] @ fp[s + L]) / (np.linalg.norm(fp[s]) * np.linalg.norm(fp[s + L]) + 1e-9)
                scores[s] = win.mean() + steady + 2 * seam
        else:
            L = phrase_bars
            others = [norm[o] for o in stems if o != inst]
            scores = np.full(n, -np.inf)
            for s in range(0, n - L + 1):
                win = lv[s:s + L]
                if win.mean() < 0.3:
                    continue
                rest = np.mean([o[s:s + L].mean() for o in others]) if others else 0
                scores[s] = win.mean() + 0.6 * (win.mean() - rest)
        pieces[inst] = [
            {"bar": s, "bars": L, "start": round(float(bars[s]), 3), "end": round(float(bars[s + L]), 3),
             "score": round(float(scores[s]), 3)}
            for s in pick(scores, L)
        ] + (free_phrases(y, free_until, peak_level(y)) if free_until else [])

    # Parts: the same bars for every instrument, so a track's stems started
    # together play the passage as recorded. They must LOOP like a groove:
    # on bar lines (snapped to the real attacks), the drums alike in every
    # bar (no break, no fill at the end: Arroyoyo's part 3 had both), no
    # instrument dropping out. 8 bars when the groove holds, else 4
    parts = select_parts(stems, bars, norm, mix, duration, bar_s)
    # The owner's parts (parts.html) win over the analyser's, which are kept
    # in parts_auto (the editor's "back to the analysis")
    auto = parts
    edited = load_edits().get(track)
    if edited:
        parts = parts_from_edits(edited, stems, bars, norm, mix)

    return {
        **meta,
        "parts": parts,
        "parts_auto": auto,
        "tempo": round(tempo, 2),
        "meter": meter,
        "free_until": free_until,
        "bars": [round(float(b), 3) for b in bars],
        "bar_seconds": round(bar_len, 3),
        "duration": round(duration, 2),
        "pieces": pieces,
    }


def main():
    meta = json.loads((STEMS / "stems.json").read_text())
    only = sys.argv[1:]
    out_path = ROOT / "audio" / "analysis.json"
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for track, m in meta.items():
        if only and track not in only:
            continue
        print(f"{track}…", flush=True)
        out[track] = analyse(track, m)
        r = out[track]
        print(f"  {r['tempo']} bpm (Moises {m['bpm']}), {len(r['bars'])} bars of {r['bar_seconds']} s; "
              + ", ".join(f"{i}: {len(p)}" for i, p in r["pieces"].items()))
        out_path.write_text(json.dumps(dict(sorted(out.items())), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
