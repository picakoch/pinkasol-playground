// Pinkasol sound engine — shared by the three experiences (duo, ciel,
// collage). Plain Web Audio, no library. In a tile it is inlined by
// tools/build.py (a tile is one file); here it is /lib/pinkasol-engine.js.
//
//   const eng = await Pinkasol.engine();          // loads the manifest
//   canvas.onpointerdown = () => eng.unlock();    // first gesture: sound on
//   const v = eng.play(eng.piece('01_Rototo', 'drums'));
//   v.level(); v.stop();
//
// Time: the first bar-based loop that starts sets the CLOCK (its bar
// length, its start). Every later piece starts on the clock's next bar
// (opts.quant: 'bar' | 'half' | 'beat' | 'now'). A bar-based piece whose
// tempo is within MATCH of the clock's is resampled to it (playbackRate:
// a slight pitch shift, < 1.4 semitone); further away it plays at its own
// speed (still starting on a bar line). Rubato pieces ("free") never sync.
(function () {
  'use strict';

  const MATCH = 0.08;
  const MAX_DECODED = 24;
  const KEYS = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
  const ALIASES = { 'C#': 'Db', 'D#': 'Eb', 'F#': 'Gb', 'G#': 'Ab', 'A#': 'Bb' };

  // "G minor" -> its relative major's index on the circle of fifths
  function fifths(key) {
    const [note, mode] = String(key).split(' ');
    let i = KEYS.indexOf(ALIASES[note] || note);
    if (i < 0) return null;
    if (mode === 'minor') i = (i + 3) % 12;
    return (i * 7) % 12;
  }

  // Semitones to move key `from` so it sits with key `to`: the same key or
  // its relative ideally, else one fifth apart, with the smallest move
  // (0 when already close). "G major" -> "Ab minor": +1 ... in -5..+6
  function keyShift(from, to) {
    const [note, mode] = String(from).split(' ');
    const i = KEYS.indexOf(ALIASES[note] || note);
    if (i < 0 || fifths(to) === null) return 0;
    let best = 0, bestScore = Infinity;
    for (let n = -5; n <= 6; n++) {
      const x = fifths(`${KEYS[(i + n + 12) % 12]} ${mode}`), y = fifths(to);
      const d = Math.min(Math.abs(x - y) % 12, 12 - (Math.abs(x - y) % 12));
      // a step on the circle of fifths costs 3 semitones of shift: a big
      // transposition sounds grainy, a fifth apart is fine
      const score = d * 3 + Math.abs(n);
      if (score < bestScore || (score === bestScore && Math.abs(n) < Math.abs(best))) { best = n; bestScore = score; }
    }
    return best;
  }

  // Same key, relative major/minor, or one fifth apart
  function compatible(a, b) {
    const x = fifths(a), y = fifths(b);
    if (x === null || y === null) return true;
    const d = Math.abs(x - y) % 12;
    return Math.min(d, 12 - d) <= 1;
  }

  // Time-stretch keeping the pitch (WSOLA): `alpha` = new length / old.
  // Plain JS on the main thread (the box allows no worklet): ~50 ms for a
  // 16 s stereo part. Clean within ±15 %, a little grainy beyond
  function stretch(ctx, buf, alpha) {
    const sr = buf.sampleRate, chs = buf.numberOfChannels, inLen = buf.length;
    const N = 2048, Hs = N / 2, Ha = Hs / alpha, tol = 384, L = 384;
    const outLen = Math.ceil(inLen * alpha);
    const out = ctx.createBuffer(chs, outLen, sr);
    const ins = [], outs = [];
    for (let c = 0; c < chs; c++) { ins.push(buf.getChannelData(c)); outs.push(out.getChannelData(c)); }
    const mono = new Float32Array(inLen);
    for (let c = 0; c < chs; c++) for (let i = 0; i < inLen; i++) mono[i] += ins[c][i];
    const win = new Float32Array(N);
    for (let i = 0; i < N; i++) win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / N);
    let prev = 0;
    for (let k = 0, at = 0; at < outLen; k++, at += Hs) {
      const nominal = Math.round(k * Ha);
      let best = Math.min(nominal, inLen - 1);
      if (k > 0) {
        // the input frame that best continues the previous one
        const natural = prev + Hs;
        let bestC = -Infinity;
        for (let d = -tol; d <= tol; d += 3) {
          const s = nominal + d;
          if (s < 0 || s + L >= inLen || natural + L >= inLen) continue;
          let c = 0;
          for (let i = 0; i < L; i += 4) c += mono[natural + i] * mono[s + i];
          if (c > bestC) { bestC = c; best = s; }
        }
      }
      for (let c = 0; c < chs; c++) {
        const x = ins[c], y = outs[c];
        for (let i = 0; i < N; i++) {
          const a = best + i, b = at + i;
          if (a >= inLen || b >= outLen) break;
          // the first frame starts at full level (the loop's first beat)
          y[b] += x[a] * (k === 0 && i < Hs ? 1 : win[i]);
        }
      }
      prev = best;
    }
    return out;
  }

  async function engine(opts = {}) {
    const base = opts.base || '/audio/pieces/';
    const manifest = opts.manifest || (await (await fetch(base + 'manifest.json')).json());
    const tracks = manifest.tracks;
    const byId = Object.fromEntries(tracks.map((t) => [t.id, t]));
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();

    const master = ctx.createGain();
    master.gain.value = 0.7;
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -10;
    limiter.knee.value = 6;
    limiter.ratio.value = 8;
    limiter.attack.value = 0.003;
    limiter.release.value = 0.2;
    const masterAnalyser = ctx.createAnalyser();
    masterAnalyser.fftSize = 1024;
    master.connect(limiter).connect(masterAnalyser).connect(ctx.destination);

    const decoded = new Map(); // file -> Promise<AudioBuffer>
    const order = [];
    const voices = new Set();
    let clock = null; // { t0, bar, beats, tempo, track }
    let leading = null; // Promise: the clock's first piece is loading
    // Tempo matching: bar-based pieces are time-stretched (pitch kept) to
    // the clock's bar, whatever their tempo. Off: ±MATCH varispeed only
    let tempoMatch = false;
    const stretched = new Map(); // "file|alpha" -> Promise<AudioBuffer>
    // The buffer to play for `p`: stretched to `bar` (tempo matching, or
    // null) and transposed by p.semitones (stretched by the pitch ratio,
    // then played that much faster: same length, new pitch)
    function stretchedFor(p, bar) {
      const ratio = 2 ** ((p.semitones || 0) / 12);
      const alphaT = bar ? (bar * p.bars) / p.loop_end : 1;
      const alpha = alphaT * ratio;
      if (Math.abs(alpha - 1) < 0.003) return { alpha: 1, alphaT, ratio: 1, buf: load(p) };
      const key = `${p.file}|${alpha.toFixed(4)}`;
      if (!stretched.has(key)) {
        stretched.set(key, load(p).then((b) => stretch(ctx, b, alpha)));
        if (stretched.size > MAX_DECODED) stretched.delete(stretched.keys().next().value);
      }
      return { alpha, alphaT, ratio, buf: stretched.get(key) };
    }
    const matches = (p, track) => tempoMatch && clock && !p.free && track.meter === clock.beats;
    const listeners = new Set();
    const emit = () => listeners.forEach((f) => f());

    function load(piece) {
      const f = piece.file;
      if (!decoded.has(f)) {
        // manifest.urls: each file's address in the site's media library
        // (the tile build), else base + file (the playground)
        decoded.set(f, fetch((manifest.urls && manifest.urls[f]) || base + f)
          .then((r) => { if (!r.ok) throw new Error(`${f}: ${r.status}`); return r.arrayBuffer(); })
          .then((b) => ctx.decodeAudioData(b)));
        order.push(f);
        while (order.length > MAX_DECODED) {
          const old = order.shift();
          if (![...voices].some((v) => v.piece.file === old)) decoded.delete(old);
          else order.push(old);
          if (order.length > MAX_DECODED * 2) break;
        }
      }
      return decoded.get(f);
    }

    const preload = (pieces) => Promise.all(pieces.map((p) => load(p).catch(() => null)));

    function piece(trackId, inst, n = 0) {
      const list = byId[trackId]?.pieces.filter((p) => p.inst === inst && !p.free) || [];
      return list[n % Math.max(1, list.length)] || null;
    }
    const pieces = (trackId, inst) => byId[trackId]?.pieces.filter((p) => !inst || p.inst === inst) || [];
    const instruments = (trackId) => [...new Set(pieces(trackId).map((p) => p.inst))];
    const trackOf = (p) => byId[p.file.split('/')[0]];

    // The next quantised time on the clock, at least `lead` s from now
    function nextTime(quant = 'bar', lead = 0.06) {
      const now = ctx.currentTime + lead;
      if (!clock || quant === 'now') return now;
      const unit = quant === 'bar' ? clock.bar : quant === 'half' ? clock.bar / 2 : clock.bar / clock.beats;
      const k = Math.ceil((now - clock.t0) / unit - 1e-6);
      return clock.t0 + Math.max(0, k) * unit;
    }

    function play(p, o = {}) {
      if (!p) return null;
      const track = trackOf(p);
      const loop = o.loop ?? !p.free;
      const synced = !p.free && o.sync !== false;
      let rate = 1;
      if (synced && clock && track.meter === clock.beats) {
        const r = clock.tempo / track.tempo;
        if (Math.abs(r - 1) <= MATCH) rate = r;
      }
      const gain = ctx.createGain();
      gain.gain.value = 0;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.6;
      const out = o.destination || master;
      gain.connect(analyser).connect(out);
      const td = new Uint8Array(analyser.fftSize);
      const fd = new Uint8Array(analyser.frequencyBinCount);

      const v = {
        piece: p, track, inst: p.inst, rate, loop, gain, analyser,
        playing: true, ready: false, startsAt: null, src: null, target: o.gain ?? 1, loopLen: p.loop_end,
        level() {
          analyser.getByteTimeDomainData(td);
          let s = 0;
          for (let i = 0; i < td.length; i++) { const x = (td[i] - 128) / 128; s += x * x; }
          return Math.min(1, Math.sqrt(s / td.length) * 3);
        },
        spectrum() { analyser.getByteFrequencyData(fd); return fd; },
        setGain(x, time = 0.15) {
          v.target = x;
          if (!v.ready) return; // the fade-in, when scheduled, goes to target
          // Never cancel the fade-in still to come (a start on the next bar)
          const from = Math.max(ctx.currentTime, v.startsAt + v.fadeIn);
          gain.gain.cancelScheduledValues(from);
          gain.gain.setTargetAtTime(x, from, time / 3);
        },
        stop(fade = 0.4, at) {
          if (!v.playing) return;
          v.playing = false;
          voices.delete(v);
          const t = Math.max(ctx.currentTime, at ?? ctx.currentTime);
          gain.gain.cancelScheduledValues(t);
          gain.gain.setTargetAtTime(0, t, fade / 4);
          if (v.src) v.src.stop(t + fade + 0.1);
          setTimeout(() => { try { gain.disconnect(); } catch (e) { /* gone */ } }, (t - ctx.currentTime + fade + 0.3) * 1000);
          // The clock goes when the last loop has really stopped (a stop on
          // the next bar keeps it until then: what starts meanwhile syncs)
          const later = Math.max(0, t - ctx.currentTime);
          const release = () => { if (![...voices].some((x) => x.loop && !x.piece.free)) clock = null; emit(); };
          if (later > 0.01) setTimeout(release, later * 1000); else release();
          emit();
        },
        // Seconds into the piece's loop now (for visuals), null before start
        position() {
          if (!v.startsAt || ctx.currentTime < v.startsAt) return null;
          const len = v.loopLen / v.rate;
          const t = ctx.currentTime - v.startsAt;
          return v.loop ? t % len : Math.min(t, len);
        },
      };
      voices.add(v);

      // The first bar-based loop leads; others started meanwhile wait for it
      const lead = !clock && !leading && loop && !p.free && o.sync !== false;
      const loaded = load(p);
      if (lead) leading = loaded.catch(() => null);
      Promise.all([loaded, lead ? null : synced ? leading : null]).then(async ([buf]) => {
        if (!v.playing) return;
        // Tempo matching: the stretched copy, exactly the clock's bars long;
        // a transposed piece (p.semitones): stretched by the pitch ratio and
        // played that much faster. loopLen is in the buffer's seconds
        const tempoMatched = !lead && synced && matches(p, track);
        if (tempoMatched || p.semitones) {
          const s = stretchedFor(p, tempoMatched ? clock.bar : null);
          buf = await s.buf;
          v.loopLen = p.loop_end * s.alpha;
          rate = s.ratio; v.rate = rate;
          if (tempoMatched) v.stretched = s.alphaT;
          v.semitones = p.semitones || 0;
          if (!v.playing) return;
        }
        const src = ctx.createBufferSource();
        src.buffer = buf;
        if (loop) { src.loop = true; src.loopStart = 0; src.loopEnd = Math.min(v.loopLen, buf.duration); }
        src.connect(gain);
        // (not on a transposed piece: varispeed would bend its new pitch)
        if (!lead && synced && !v.stretched && !p.semitones && clock && track.meter === clock.beats) {
          const r = clock.tempo / track.tempo;
          if (Math.abs(r - 1) <= MATCH) { rate *= r; v.rate = rate; }
        }
        src.playbackRate.value = rate;
        const when = o.at != null ? Math.max(o.at, ctx.currentTime + 0.01)
          : lead ? ctx.currentTime + 0.05 : synced ? nextTime(o.quant || 'bar') : ctx.currentTime + 0.03;
        if (lead) {
          const real = v.loopLen / rate; // the loop in real seconds
          clock = { t0: when, bar: real / p.bars, beats: track.meter, tempo: track.tempo * (p.loop_end / real), track: track.id };
          leading = null;
        }
        src.start(when, 0);
        if (!loop) src.stop(when + (buf.duration) / rate);
        src.onended = () => { if (v.playing && !loop) { v.playing = false; voices.delete(v); if (![...voices].some((x) => x.loop && !x.piece.free)) clock = null; emit(); } };
        v.fadeIn = o.fadeIn ?? 0.02;
        gain.gain.setValueAtTime(0, when);
        gain.gain.linearRampToValueAtTime(v.target, when + v.fadeIn);
        v.src = src; v.startsAt = when; v.ready = true;
        emit();
      }).catch((e) => { if (lead) leading = null; console.error(e); v.stop(0); });
      emit();
      return v;
    }

    // A track's part: its stems, loaded first, then started on the same
    // sample (next bar of the clock, or now when there is none; the first
    // one leads). `olds` stop at that moment. Returns the voices
    // o.immediate: now, not on the next bar: the clock restarts from this
    // moment (the first piece leads) and `olds` fade out in 30 ms. Give it
    // the whole table so every instrument restarts together
    async function playTogether(list, o = {}, olds = []) {
      list = list.filter(Boolean);
      await Promise.all(list.map((p) => load(p)));
      if (o.immediate) { clock = null; leading = null; }
      // Stretch before choosing the moment: no piece may start late. The
      // first piece leads when there is no clock (put the drums first)
      // Prepare every stretched/transposed buffer exactly as play() will
      // ask for it, before choosing the moment: no piece may start late.
      // The first piece leads when there is no clock (put the drums first)
      const head = list[0];
      const bar = clock ? clock.bar : head.loop_end / head.bars;
      const beats = clock ? clock.beats : trackOf(head).meter;
      await Promise.all(list.map((p) => {
        const leads = !clock && p === head;
        const matched = tempoMatch && !leads && !p.free && trackOf(p).meter === beats;
        return matched || p.semitones ? stretchedFor(p, matched ? bar : null).buf : null;
      }));
      const at = clock ? nextTime('bar') : ctx.currentTime + (o.immediate ? 0.04 : 0.08);
      olds.filter((v) => v && v.playing).forEach((v) => v.stop(o.fade ?? (o.immediate ? 0.03 : 0.25), at));
      return list.map((p) => play(p, { ...o, at }));
    }

    // A part of a track as pieces the engine plays: { inst: piece }
    function part(trackId, k) {
      const t = byId[trackId];
      const pt = t?.parts?.[k];
      if (!pt) return null;
      return Object.fromEntries(Object.entries(pt.files).map(([inst, file]) => [inst,
        { inst, file, loop_end: pt.loop_end, bars: pt.bars, free: false, part: k }]));
    }

    // Replace voice `old` by piece `p` on the next bar: a crossfade
    function swap(old, p, o = {}) {
      const v = play(p, o);
      if (old && old.playing) {
        const t = clock ? nextTime('bar') : ctx.currentTime;
        old.stop(o.fade ?? 0.25, t);
      }
      return v;
    }

    function level() {
      const td = new Uint8Array(masterAnalyser.fftSize);
      masterAnalyser.getByteTimeDomainData(td);
      let s = 0;
      for (let i = 0; i < td.length; i++) { const x = (td[i] - 128) / 128; s += x * x; }
      return Math.min(1, Math.sqrt(s / td.length) * 3);
    }
    const spectrumData = new Uint8Array(masterAnalyser.frequencyBinCount);
    const spectrum = () => { masterAnalyser.getByteFrequencyData(spectrumData); return spectrumData; };

    // Beat phase of the clock now: { bar: 0..1, beat: 0..1, n: beat index }
    function phase() {
      if (!clock || ctx.currentTime < clock.t0) return null;
      const t = ctx.currentTime - clock.t0;
      const beat = clock.bar / clock.beats;
      return { bar: (t % clock.bar) / clock.bar, beat: (t % beat) / beat, n: Math.floor((t % clock.bar) / beat) };
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) ctx.suspend(); else if (voices.size) ctx.resume();
    });

    return {
      ctx, tracks, byId, palette: manifest.palette,
      unlock: () => (ctx.state === 'running' ? Promise.resolve() : ctx.resume()),
      load, preload, piece, pieces, instruments, play, playTogether, part, swap, nextTime, phase, level, spectrum,
      compatible, keyShift, trackOf,
      get clock() { return clock; },
      get tempoMatch() { return tempoMatch; },
      set tempoMatch(x) { tempoMatch = !!x; },
      // Forget the clock: the next piece (or playTogether's first) leads
      resetClock() { clock = null; leading = null; },
      get voices() { return [...voices]; },
      stopAll(fade = 0.5) { [...voices].forEach((v) => v.stop(fade)); },
      onchange(f) { listeners.add(f); return () => listeners.delete(f); },
    };
  }

  window.Pinkasol = { engine, compatible, keyShift };
})();
