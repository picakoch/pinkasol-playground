#!/usr/bin/env python3
"""Local playground for the Pinkasol code tile.

Serves this folder on port 8121 with the code tile box's policy
(backend/src/box/policy.js, branch issue-782-code-tile), adapted: the
"media library" is this server's /audio/ and /img/, and connect-src allows
them too (the planned box change: fetch audio from the media library).
So what runs here should run in the box: no other script, no outside
fetch, no storage.

    python3 serve.py         # this Mac only: http://localhost:8121/
    python3 serve.py --lan   # also the phone, on the same Wi-Fi:
                             # http://<the Mac's address>:8121/ (printed)
"""
import http.server
import json
import re
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

PORT = 8121
LAN = "--lan" in sys.argv
ROOT = Path(__file__).resolve().parent
# The owner's tools: no box policy (they post, they read the stems)
TOOLS = ("/picker.html", "/parts.html")
PY = str(ROOT / "tools" / ".venv" / "bin" / "python")
# parts.html's "Régénérer": the edits into the analysis, the cut, the tiles
REGENERATE = [
    [PY, "-W", "ignore", "tools/apply_edits.py"],
    [PY, "tools/cut.py"],
    ["python3", "tools/build.py", "--local"],
    ["python3", "tools/build.py"],
]
REGENERATING = threading.Lock()


def policy(origin):
    """The box policy for the address the page was opened with (localhost
    on the Mac, the Mac's LAN address on the phone)."""
    media = f"{origin}/audio/ {origin}/img/"
    return "; ".join([
        "default-src 'none'",
        f"script-src 'unsafe-inline' {origin}/lib/",
        "style-src 'unsafe-inline'",
        f"img-src data: blob: {media}",
        f"media-src data: blob: {media}",
        "font-src data:",
        f"connect-src {media}",
        "frame-src 'none'",
        "worker-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # The box policy on every page (the menu, the experiences), not on the
        # owner's tools (TOOLS: picker.html, parts.html)
        path = self.path.split("?")[0]
        if (path == "/" or path.endswith(".html")) and path not in TOOLS:
            host = self.headers.get("Host", f"localhost:{PORT}")
            if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d{1,5})?", host):
                host = f"localhost:{PORT}"
            self.send_header("Content-Security-Policy", policy(f"http://{host}"))
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        # The owner's tools, from this Mac only: picker.html's "Save picks",
        # parts.html's "Enregistrer" and "Régénérer"
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self.send_error(404)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        if self.path == "/save-picks":
            json.loads(body)
            (ROOT / "audio" / "picks.json").write_bytes(body)
            self.send_response(204)
            return self.end_headers()
        if self.path == "/save-parts":
            save_parts(body)
            self.send_response(204)
            return self.end_headers()
        if self.path == "/regenerate":
            return self.regenerate(body)
        self.send_error(404)

    def regenerate(self, body):
        # One at a time: the cut and the builds write the same files
        if not REGENERATING.acquire(blocking=False):
            return self.send_json(409, {"ok": False, "log": "Une régénération est déjà en cours."})
        try:
            if body.strip():
                save_parts(body)
            log, ok = [], True
            for step in REGENERATE:
                log.append("$ " + " ".join(step))
                r = subprocess.run(step, cwd=ROOT, capture_output=True, text=True)
                log.append((r.stdout + r.stderr).strip())
                if r.returncode:
                    ok = False
                    log.append(f"(failed: exit {r.returncode})")
                    break
            self.send_json(200 if ok else 500, {"ok": ok, "log": "\n".join(x for x in log if x)})
        finally:
            REGENERATING.release()

    def send_json(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def save_parts(body):
    """parts.html's edits: { track: [ {bar, bars, star?}, ... ] }, bar and
    bars in quarter bars; {} or a track left out = the analyser's parts"""
    edits = json.loads(body)
    def q(x):  # quarter bars (the editor's snap); whole bars stay integers
        v = round(float(x) * 4) / 4
        return int(v) if v.is_integer() else v

    def part(p):
        out = {"bar": q(p["bar"]), "bars": max(0.25, q(p["bars"]))}
        if isinstance(p.get("star"), bool):  # the owner's ★ (absent = automatic)
            out["star"] = p["star"]
        return out
    clean = {str(track): [part(p) for p in parts] for track, parts in edits.items() if parts}
    path = ROOT / "audio" / "parts-edit.json"
    if clean:
        path.write_text(json.dumps(dict(sorted(clean.items())), indent=1) + "\n")
    elif path.exists():
        path.unlink()


def lan_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # no packet sent: picks the outgoing interface
            return s.getsockname()[0]
        except OSError:
            return None


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("0.0.0.0" if LAN else "127.0.0.1", PORT), Handler) as httpd:
    print(f"Pinkasol playground on http://localhost:{PORT}/ (box policy on)")
    if LAN:
        print(f"  from the phone (same Wi-Fi): http://{lan_address()}:{PORT}/")
    httpd.serve_forever()
