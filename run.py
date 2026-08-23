#!/usr/bin/env python3
"""
run.py — one command to start the PDF compressor on macOS, Windows or Linux.

Builds the UI if it is missing or stale, checks PyMuPDF is importable, opens a browser,
then runs the server. Everything here is stdlib and platform-neutral: npm is located with
shutil.which (which finds npm.cmd on Windows), the browser is opened with the webbrowser
module rather than `open`/`start`, and all paths go through pathlib.

  python3 run.py                # macOS / Linux
  py run.py                     # Windows
  python3 run.py --port 9000
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DIST = WEB / "dist"
WATCHED = [WEB / "src", WEB / "index.html", WEB / "public", WEB / "package.json"]


def npm() -> str:
    """Absolute path to npm, or exit with an actionable message."""
    found = shutil.which("npm")
    if not found:
        sys.exit("npm not found. Install Node.js from https://nodejs.org and re-run.")
    return found


def run_npm(*args: str) -> None:
    subprocess.run([npm(), *args], cwd=WEB, check=True)


def newest_mtime(paths) -> float:
    newest = 0.0
    for p in paths:
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
        elif p.is_dir():
            for child in p.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
    return newest


def ensure_ui(force: bool) -> None:
    if not (WEB / "node_modules").is_dir():
        print("installing UI dependencies (first run only)...")
        run_npm("install", "--no-fund", "--no-audit")

    built = DIST / "index.html"
    stale = force or not built.is_file() or newest_mtime(WATCHED) > built.stat().st_mtime
    if stale:
        print("building UI...")
        run_npm("run", "build")
    else:
        print("UI already up to date")


def main() -> int:
    ap = argparse.ArgumentParser(description="Start the local PDF compressor")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rebuild", action="store_true", help="force a UI rebuild")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()

    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            import fitz  # noqa: F401
        except ImportError:
            sys.exit(f"PyMuPDF is missing. Install it with:\n  "
                     f"{Path(sys.executable).name} -m pip install pymupdf")

    ensure_ui(args.rebuild)

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        # Open slightly late so the server is listening by the time the tab loads.
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)),
                         daemon=True).start()

    try:
        return subprocess.call([sys.executable, "-u", str(ROOT / "server.py"),
                                "--port", str(args.port), "--host", args.host])
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
