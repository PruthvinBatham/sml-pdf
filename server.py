#!/usr/bin/env python3
"""
server.py — local web server for the drag-and-drop PDF compressor.

Stdlib only (plus PyMuPDF, which compress_pdf.py already needs), so there is nothing to
pip install, and it runs the same on macOS, Windows and Linux.

The browser POSTs the raw PDF bytes as the request body rather than a multipart form, so
there is no form parsing here at all. The response is the JSON analysis report; the
compressed bytes are held briefly under an id and fetched separately, which keeps the
report cheap to render and gives the download a proper filename.

  python3 server.py            # http://127.0.0.1:8000
  python3 server.py --port 9000
"""

from __future__ import annotations

import argparse
import json
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import compress_pdf

ROOT = Path(__file__).parent
DIST = ROOT / "web" / "dist"
MAX_UPLOAD = 300 * 1024 * 1024   # refuse absurd bodies rather than filling memory
KEEP_RESULTS = 8                 # most recent compressed files held for download
RESULT_TTL = 30 * 60             # seconds


class ResultStore:
    """Holds compressed PDFs in memory just long enough for the browser to download them."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, tuple[bytes, str, float]] = {}

    def put(self, data: bytes, name: str) -> str:
        key = uuid.uuid4().hex
        with self._lock:
            self._items[key] = (data, name, time.time())
            self._evict()
        return key

    def get(self, key: str):
        with self._lock:
            self._evict()
            return self._items.get(key)

    def _evict(self):
        now = time.time()
        for k in [k for k, (_, _, t) in self._items.items() if now - t > RESULT_TTL]:
            self._items.pop(k, None)
        if len(self._items) > KEEP_RESULTS:
            for k in sorted(self._items, key=lambda k: self._items[k][2])[:-KEEP_RESULTS]:
                self._items.pop(k, None)


RESULTS = ResultStore()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DIST), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # ---------------------------------------------------------------- helpers

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode(), "application/json")

    # ---------------------------------------------------------------- POST

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/compress":
            return self._json(404, {"error": "no such endpoint"})

        qs = urllib.parse.parse_qs(parsed.query)
        raw_target = (qs.get("target") or ["1MB"])[0]
        mode = (qs.get("mode") or ["auto"])[0]
        name = (qs.get("name") or ["document.pdf"])[0]
        if mode not in ("auto", "images", "raster"):
            return self._json(400, {"error": f"bad mode {mode!r}"})
        try:
            target = compress_pdf.parse_size(raw_target)
        except Exception:
            return self._json(400, {"error": f"bad target size {raw_target!r}"})

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._json(400, {"error": "empty body"})
        if length > MAX_UPLOAD:
            return self._json(413, {"error": "file too large"})

        tmp = Path(tempfile.mkdtemp(prefix="pdfcompress-"))
        try:
            src = tmp / "input.pdf"
            with src.open("wb") as f:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)

            if src.read_bytes()[:5] != b"%PDF-":
                return self._json(400, {"error": "that does not look like a PDF"})

            r = compress_pdf.compress(src, target, mode)
            stem = Path(name).stem or "document"
            out_name = f"{stem}_compressed.pdf"
            report = r.report()
            report["id"] = RESULTS.put(r.data, out_name)
            report["download"] = f"/api/result/{report['id']}"
            report["filename"] = out_name
            report["source_name"] = name
            self._json(200, report)
        except Exception as e:
            traceback.print_exc()
            try:
                self._json(500, {"error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------------- GET

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path.startswith("/api/result/"):
            item = RESULTS.get(parsed.path.rsplit("/", 1)[-1])
            if not item:
                return self._json(404, {"error": "result expired — compress again"})
            data, name, _ = item
            return self._send(200, data, "application/pdf",
                              {"Content-Disposition": f'attachment; filename="{name}"'})

        if not DIST.is_dir():
            msg = (b"<h1>UI not built</h1><p>Run <code>python3 run.py</code>, or "
                   b"<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>")
            return self._send(503, msg, "text/html")

        return super().do_GET()

    def end_headers(self):
        # Never let the browser cache the shell; makes rebuilds show up immediately.
        if self.path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    ap = argparse.ArgumentParser(description="Local PDF compressor server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    with Server((args.host, args.port), Handler) as httpd:
        print(f"PDF compressor running at http://{args.host}:{args.port}")
        print("  drop a PDF, set a target size, compress")
        print("  Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
