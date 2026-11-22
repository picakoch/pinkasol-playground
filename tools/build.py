"""Build the Tilefolio code tile: one HTML file to paste in the code panel.

    python3 tools/build.py           # dist/pinkasol-tile.html  (for Tilefolio)
    python3 tools/build.py --local   # dist/pinkasol-tile.local.html (try it here)

From duo.html: the engine (lib/pinkasol-engine.js) and the parts' manifest
are inlined, the p5 <script> tag is removed (tick "p5.js" in the panel: the
box adds the library itself), the "← Pinkasol" link is hidden (a tile can't
navigate), and the audio and the cover come from picasol.fr's media library:

- audio: audio/media-urls.json, { "<track>/<file>.mp3": "https://…" }, the
  address of each part file once uploaded to the site's library (Strapi
  renames uploads, so they can't be guessed). Files missing from it fall
  back to MEDIA_BASE + file, and the build says how many.
- cover: COVER_URL (the Pinkasol cover, already in picasol.fr's library).

--local builds the same tile for this playground (audio from /audio/pieces/,
cover from /img/, the p5 tag kept as the box would add it), served by
serve.py with the box's policy: what plays there plays in the tile.

A code tile is 200 KB at most: the build fails above that.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 200 * 1024
MEDIA_BASE = "https://media.tilefolio.com/i1/"
COVER_URL = "https://media.tilefolio.com/i1/medium_pinkasol_cover_h_0f5f9e0dd8.jpg.webp"


def manifest_for_tile():
    m = json.loads((ROOT / "audio" / "pieces" / "manifest.json").read_text())
    # the duo table plays parts only: drop the analyser's single pieces
    keep = ("id", "title", "key", "meter", "tempo", "bar_seconds", "parts")
    return {"palette": m.get("palette"), "tracks": [{k: t[k] for k in keep if k in t} for t in m["tracks"]]}


def main():
    local = "--local" in sys.argv
    html = (ROOT / "duo.html").read_text()
    engine = (ROOT / "lib" / "pinkasol-engine.js").read_text()
    manifest = manifest_for_tile()

    files = [f for t in manifest["tracks"] for p in t["parts"] for f in p["files"].values()]
    if local:
        base, cover = "/audio/pieces/", "/img/cover-medium.webp"
    else:
        base, cover = MEDIA_BASE, COVER_URL
        urls_path = ROOT / "audio" / "media-urls.json"
        urls = json.loads(urls_path.read_text()) if urls_path.exists() else {}
        manifest["urls"] = {f: urls[f] for f in files if f in urls}
        missing = len(files) - len(manifest["urls"])
        if missing:
            print(f"warning: {missing} of {len(files)} part files have no media-library address "
                  f"(audio/media-urls.json): they would be fetched from {MEDIA_BASE}<file>, "
                  "which doesn't exist until they are uploaded", file=sys.stderr)

    # The box adds the ticked libraries itself: no p5 tag in the tile
    if not local:
        html, n = re.subn(r'\s*<script src="/lib/p5\.min\.js"></script>', "", html)
        assert n == 1, "p5 script tag not found"
    # The engine call gets the manifest (before inlining the engine: its
    # own comments show the same call)
    assert html.count("Pinkasol.engine()") == 1, "engine call not found"
    html = html.replace("Pinkasol.engine()", f"Pinkasol.engine({{ manifest: PINKASOL_MANIFEST, base: {json.dumps(base)} }})")
    # The engine and the manifest, inline
    tag = '<script src="/lib/pinkasol-engine.js"></script>'
    assert html.count(tag) == 1, "engine script tag not found"
    data = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    html = html.replace(tag, f"<script>\n{engine}\n</script>\n<script>\nwindow.PINKASOL_TILE = true;\n"
                             f"const PINKASOL_MANIFEST = {data};\n</script>")
    # The cover, for the random button
    assert html.count("COVER.src = '/img/cover-medium.webp';") == 1, "cover not found"
    html = html.replace("COVER.src = '/img/cover-medium.webp';", f"COVER.src = {json.dumps(cover)};")
    # No way out of a tile: hide the link back to the playground's menu
    html = html.replace('<a id="back" href="/">← Pinkasol</a>', "")

    size = len(html.encode("utf-8"))
    if size > MAX_BYTES:
        sys.exit(f"error: {size} bytes, a code tile is {MAX_BYTES} at most")
    out = ROOT / "dist" / ("pinkasol-tile.local.html" if local else "pinkasol-tile.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"{out.relative_to(ROOT)}: {size / 1024:.1f} KB of {MAX_BYTES // 1024} KB, {len(files)} part files")


if __name__ == "__main__":
    main()
