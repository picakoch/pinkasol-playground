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
import sys
from pathlib import Path

PORT = 8121
LAN = "--lan" in sys.argv


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
        # owner's tool (picker.html)
        path = self.path.split("?")[0]
        if (path == "/" or path.endswith(".html")) and path != "/picker.html":
            host = self.headers.get("Host", f"localhost:{PORT}")
            if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d{1,5})?", host):
                host = f"localhost:{PORT}"
            self.send_header("Content-Security-Policy", policy(f"http://{host}"))
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        # picker.html's "Save picks", from this Mac only
        if self.path != "/save-picks" or self.client_address[0] not in ("127.0.0.1", "::1"):
            return self.send_error(404)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        json.loads(body)
        (Path(__file__).parent / "audio" / "picks.json").write_bytes(body)
        self.send_response(204)
        self.end_headers()


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
