# Pinkasol playground

An interactive way into *Pinkasol*, the third album of the duo
[Picasol](https://picasol.fr) (piano; drums and synth): **La table du duo**.
The ten tracks are cards; drop one on the piano, the drums, the synth or the
bass and that instrument plays its part of the track. Mix tracks, or
double-click a card to hear the track as recorded. Clicks and drag-and-drop
only, made with [p5.js](https://p5js.org) and plain Web Audio.

- **Parts**: each track is cut into parts (4 or 8 bars) where its stems
  loop like a groove; the timeline under the instruments chooses them (★ =
  everyone plays). One track on the table: its stems play the same part,
  sample-aligned.
- **Tempo matching** (on by default): every instrument is time-stretched,
  pitch kept, to the drums' tempo.
- **Key matching** (on by default): the synth is transposed to sit with the
  piano's key.
- Click an instrument to mute it, a slider per instrument, space = play /
  stop, the Pinkasol face = a random table.

It is a prototype for a *code tile* on [Tilefolio](https://tilefolio.com)
(a sandboxed HTML/JS tile): `serve.py` serves every page with the tile box's
content policy, so what runs here runs there.

## Run it

    python3 serve.py          # http://localhost:8121/
    python3 serve.py --lan    # also from a phone on the same Wi-Fi

The audio isn't in this repository (see below): without it the page loads
but stays silent.

## The Tilefolio tile

`dist/pinkasol-tile.html` is the tile, ready to paste: in edit mode on the
site, **+ Code tile**, paste the file's content, tick **p5.js**, capture or
upload a still, create. 77 KB of the 200 KB a code tile allows.

    make tile         # rebuild it from duo.html, the engine and the manifest
    make tile-local   # the same for this playground:
                      # http://localhost:8121/dist/pinkasol-tile.local.html

It plays in Tilefolio only once:
1. the code tile is live: Tilefolio PR #796 (merged and deployed, with the
   box's `connect-src` = the site's media library, so the tile can fetch its
   audio), and `BOX_URL` set on the server;
2. the part files (`audio/pieces/`, 207 MP3, 62 MB) are in picasol.fr's media
   library, and `audio/media-urls.json` maps each one to its address
   (`{ "01_Rototo/p1-drums.mp3": "https://media.tilefolio.com/i1/…" }`); then
   `make tile` again. Until then the build warns and the tile stays silent.

## Pages

    index.html        menu
    duo.html          La table du duo
    picker.html       workshop: audition the analyser's candidate loops
    engine-test.html  engine smoke test
    attic/            two earlier experiments (a sky of planets, a collage)
    lib/pinkasol-engine.js   the sound engine: bar clock, aligned starts,
                             WSOLA time-stretch / transposition
    lib/p5.min.js            p5.js 1.11.13

## Audio

The album's audio and the cover are Picasol's and the cover artists' and
are not published here. To rebuild locally:

    audio/full/<NN_Name>.mp3        the 10 tracks (as on picasol.fr)
    audio/stems/<NN_Name>/          stems split with Moises:
                                    drums.mp3 piano.mp3 synth.mp3 [bass.mp3]
    audio/stems/stems.json          key, bpm, meter, rubato opening (kept)
    img/cover-medium.webp           the album cover

    make analyse   # bars, parts -> audio/analysis.json (creates tools/.venv)
    make parts     # parts -> audio/pieces/ + manifest.json
    make edges     # report parts with quiet edges
    make audio     # all three, then the tile

`audio/analysis.json` and `audio/pieces/manifest.json` are kept in the repo:
they show the result of the analysis (bars, parts, which instruments play).

## Credits

Picasol: Nicolas Boulicault (piano, composition), Antoine Scherrer (drums,
synth, composition). Recording, mixing, mastering: Marc-Etienne Géry. Cover:
Aurélie Epenoy, Émilie Gréa and Clara Juncker.

## Licence

The code is under the [MIT licence](LICENSE). It doesn't cover Picasol's
music (tracks, stems, parts) nor the cover, which aren't in this repository
and stay all rights reserved. `lib/p5.min.js` is p5.js 1.11.13, under its own
licence (LGPL 2.1).
