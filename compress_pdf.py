#!/usr/bin/env python3
"""
compress_pdf.py — compress a PDF to a target file size, keeping as much clarity as possible.

Most tools apply a fixed preset and either miss your target or blow past it, throwing away
quality you already paid for. This one treats the target as a *budget to spend*:

  Phase 1  Pick the best resolution that can possibly fit, by bisecting a DPI ladder at a
           deliberately low probe quality.
  Phase 2  Hold that resolution and bisect JPEG quality *upward* to use up the remaining
           bytes. This is where the clarity comes from.

Resolution is chosen before quality because for scanned text, sharp glyph edges matter more
than JPEG fidelity — and because embedded JPEGs can only be downsampled by integer DCT
factors (a 300dpi scan reaches 150, 75 or 37 dpi, nothing between). Asking for 80dpi
silently gets you 150; the ladder rungs in between are illusions. Quality is the knob with
real, fine-grained control, so that's the one worth searching carefully.

Two engines:
  images  Recompress/downsample only the embedded images. Text and vectors stay vector, so
          they remain sharp and selectable at any output size. Tried first.
  raster  Flatten each page to one JPEG. Loses selectable text, but reaches sizes the image
          engine can't. Only used if `images` cannot hit the target.

Every run also produces a full before/after analysis (per page, per image, plus the exact
search path taken) — see --stats and --json.

Usage:
  python3 compress_pdf.py big.pdf --target 1MB
  python3 compress_pdf.py big.pdf -t 900kb -o small.pdf --stats
  python3 compress_pdf.py big.pdf -t 1MB --json report.json
  python3 compress_pdf.py *.pdf -t 2MB --suffix _web
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pymupdf
except ImportError:  # older installs only expose `fitz`
    import fitz as pymupdf


# --------------------------------------------------------------------------- sizes

_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*(b|kb|k|mb|m|gb|g|kib|mib|gib)?\s*$", re.I)
_UNITS = {
    None: 1, "b": 1,
    "k": 1000, "kb": 1000, "kib": 1024,
    "m": 1000**2, "mb": 1000**2, "mib": 1024**2,
    "g": 1000**3, "gb": 1000**3, "gib": 1024**3,
}


def parse_size(text: str) -> int:
    """'1MB' -> 1000000, '900kb' -> 900000, '1048576' -> 1048576."""
    m = _SIZE_RE.match(str(text))
    if not m:
        raise argparse.ArgumentTypeError(f"can't read {text!r} as a size (try 1MB, 900kb, 1500000)")
    n = int(float(m.group(1)) * _UNITS[m.group(2).lower() if m.group(2) else None])
    if n <= 0:
        raise argparse.ArgumentTypeError("target size must be positive")
    return n


def human(n: int | None) -> str:
    if n is None:
        return "—"
    for unit, div in (("MB", 1000**2), ("KB", 1000)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


# --------------------------------------------------------------------------- settings

@dataclass(frozen=True)
class Setting:
    dpi: int
    quality: int
    gray: bool = False

    def __str__(self) -> str:
        return f"{self.dpi}dpi q{self.quality}{' grayscale' if self.gray else ''}"


# Descending = gentle to harsh. Values cluster near common scan resolutions and their
# halves/quarters, which is where the DCT-factor snapping actually lands.
DPI_STEPS = [300, 260, 220, 200, 180, 160, 150, 130, 120, 110, 100, 90, 80, 75, 65, 60, 50, 42, 36]

# Quality rungs for phase 2. PROBE_Q is the low quality used while hunting for the DPI tier:
# low enough that resolution is the only thing limiting the fit, high enough to not be junk.
QUALITY_STEPS = [35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
PROBE_Q = 35

SAVE_OPTS = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                 clean=True, use_objstms=1)


# --------------------------------------------------------------------------- analysis

def analyze(data: bytes) -> dict:
    """Full structural read-out of a PDF: document, per page, per image.

    Deliberately thorough -- this is what the UI's stats panel renders, and what makes the
    difference between "it got smaller" and knowing *exactly* what changed.
    """
    out: dict = {"bytes": len(data), "pages": [], "images": []}
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        meta = doc.metadata or {}
        out["doc"] = {
            "page_count": doc.page_count,
            "pdf_version": meta.get("format") or "",
            "producer": meta.get("producer") or "",
            "creator": meta.get("creator") or "",
            "title": meta.get("title") or "",
            "encrypted": bool(getattr(doc, "is_encrypted", False)),
            "fast_web_view": bool(getattr(doc, "is_fast_webaccess", False)),
            "repaired": bool(getattr(doc, "is_repaired", False)),
            "xref_objects": doc.xref_length() - 1,
            "embedded_fonts": 0,
            "image_bytes": 0,
        }

        fonts: set[str] = set()
        for pno, page in enumerate(doc):
            text = page.get_text().strip()
            entries = page.get_images(full=True)
            drawings = 0
            try:
                drawings = len(page.get_drawings())
            except Exception:
                pass
            for f in page.get_fonts(full=True):
                # (xref, ext, type, basefont, name, encoding) -- ext != 'n/a' means embedded
                if len(f) > 3 and f[1] not in ("", "n/a"):
                    fonts.add(str(f[3]))

            page_img_bytes = 0
            for entry in entries:
                xref, smask, w, h, bpc, cs, alt_cs, name, filt = (list(entry) + [None] * 9)[:9]
                rects = page.get_image_rects(xref)
                placed = rects[0] if rects else None
                dpi_x = round(w / (placed.width / 72)) if placed and placed.width else None
                dpi_y = round(h / (placed.height / 72)) if placed and placed.height else None

                stored = None
                try:
                    stored = len(doc.xref_stream_raw(xref))
                except Exception:
                    pass
                ext, cs_name, comps = None, None, None
                try:
                    info = doc.extract_image(xref)
                    ext = info.get("ext")
                    cs_name = info.get("cs-name")
                    comps = info.get("colorspace")
                    if stored is None:
                        stored = info.get("size")
                except Exception:
                    pass

                page_img_bytes += stored or 0
                out["images"].append({
                    "page": pno + 1,
                    "xref": xref,
                    "width": w,
                    "height": h,
                    "megapixels": round(w * h / 1e6, 2) if w and h else None,
                    "dpi_x": dpi_x,
                    "dpi_y": dpi_y,
                    "bpc": bpc,
                    "colorspace": cs_name or cs or "",
                    "components": comps,
                    "format": ext or (str(filt).lstrip("/") if filt else ""),
                    "filter": str(filt).lstrip("/") if filt else "",
                    "bytes": stored,
                    "has_alpha": bool(smask),
                })

            r = page.rect
            out["pages"].append({
                "page": pno + 1,
                "width_pt": round(r.width, 1),
                "height_pt": round(r.height, 1),
                "width_mm": round(r.width * 25.4 / 72, 1),
                "height_mm": round(r.height * 25.4 / 72, 1),
                "rotation": page.rotation,
                "text_chars": len(text),
                "images": len(entries),
                "vector_ops": drawings,
                "image_bytes": page_img_bytes,
            })
            out["doc"]["image_bytes"] += page_img_bytes

        out["doc"]["embedded_fonts"] = len(fonts)
        out["doc"]["font_names"] = sorted(fonts)[:12]
        total = out["doc"]["image_bytes"]
        out["doc"]["image_share_pct"] = round(100 * total / len(data), 1) if data else 0.0
        out["doc"]["text_chars"] = sum(p["text_chars"] for p in out["pages"])
        dpis = [i["dpi_x"] for i in out["images"] if i["dpi_x"]]
        out["doc"]["max_dpi"] = max(dpis) if dpis else None
        out["doc"]["min_dpi"] = min(dpis) if dpis else None
    return out


def effective_dpi(data: bytes) -> int | None:
    """Highest actual image resolution left in a PDF, for honest reporting."""
    try:
        return analyze(data)["doc"]["max_dpi"]
    except Exception:
        return None


# --------------------------------------------------------------------------- engines

def _finalize(doc: pymupdf.Document) -> bytes:
    """Drop metadata bloat, subset fonts, serialize with max structural savings."""
    for cleanup in (lambda: doc.set_metadata({}), doc.del_xml_metadata,
                    lambda: doc.subset_fonts(fallback=False)):
        try:
            cleanup()
        except Exception:
            pass  # all three are nice-to-have; none is worth failing the run over
    return doc.tobytes(**SAVE_OPTS)


def lossless(src: Path) -> bytes:
    """Structural cleanup only — not a single pixel touched."""
    with pymupdf.open(src) as doc:
        return _finalize(doc)


def compress_images(src: Path, s: Setting) -> bytes:
    """Downsample + re-encode embedded images; leave text and vectors as vectors."""
    with pymupdf.open(src) as doc:
        doc.rewrite_images(
            dpi_threshold=s.dpi + 1,   # must exceed dpi_target; anything sharper is resampled
            dpi_target=s.dpi,
            quality=s.quality,
            lossy=True,
            lossless=True,
            bitonal=False,   # 1-bit scans are already tiny; JPEG would bloat *and* smear them
            color=True,
            gray=True,
            set_to_gray=s.gray,
        )
        return _finalize(doc)


def _page_jpeg(page: pymupdf.Page, s: Setting) -> bytes:
    pix = page.get_pixmap(dpi=s.dpi, colorspace=pymupdf.csGRAY if s.gray else pymupdf.csRGB,
                          alpha=False, annots=True)
    try:
        return pix.tobytes("jpeg", jpg_quality=s.quality)
    except Exception:
        from PIL import Image
        img = Image.frombytes("L" if s.gray else "RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=s.quality, optimize=True, progressive=True)
        return buf.getvalue()


def compress_raster(src: Path, s: Setting) -> bytes:
    """Flatten every page to one JPEG. Kills selectable text; reaches very small sizes."""
    with pymupdf.open(src) as doc, pymupdf.open() as out:
        for page in doc:
            jpeg = _page_jpeg(page, s)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=jpeg)
        return _finalize(out)


# --------------------------------------------------------------------------- search

def _bisect(items, fits):
    """Earliest index in `items` that fits, assuming a monotonic ladder.

    `items` runs most-desirable to least. Returns (index, payload) or None.
    """
    lo, hi, best = 0, len(items) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        ok, payload = fits(items[mid])
        if ok:
            best = (mid, payload)
            hi = mid - 1     # something gentler might also fit
        else:
            lo = mid + 1
    return best


def search(src: Path, target: int, engine, log, gray: bool, trace: list):
    """Two-phase: best fitting resolution, then the most quality that resolution affords."""
    def probe(dpi, q, phase):
        t0 = time.perf_counter()
        data = engine(src, Setting(dpi, q, gray))
        ok = len(data) <= target
        trace.append({
            "phase": phase, "dpi": dpi, "quality": q, "gray": gray,
            "bytes": len(data), "fits": ok, "ms": round((time.perf_counter() - t0) * 1000),
        })
        log(f"    {phase:<6} {dpi:>3}dpi q{q:<3}{' gray' if gray else '     '} -> "
            f"{human(len(data)):>9}  {'fits' if ok else 'too big'}")
        return ok, data

    found = _bisect(DPI_STEPS, lambda dpi: probe(dpi, PROBE_Q, "dpi"))
    if not found:
        return None
    dpi = DPI_STEPS[found[0]]
    best = (found[1], Setting(dpi, PROBE_Q, gray))

    # Phase 2 — spend what's left of the budget on quality at that resolution.
    higher = [q for q in QUALITY_STEPS if q > PROBE_Q][::-1]   # highest first
    if higher:
        got = _bisect(higher, lambda q: probe(dpi, q, "qual"))
        if got:
            best = (got[1], Setting(dpi, higher[got[0]], gray))
    return best


# --------------------------------------------------------------------------- api

@dataclass
class Result:
    """Everything a caller (CLI or web server) needs to report on a compression run."""
    data: bytes
    engine: str                  # "lossless" | "images" | "raster"
    setting: Setting | None      # None when lossless cleanup alone sufficed
    target: int
    original_size: int
    met_target: bool
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def saved_pct(self) -> float:
        return 100 * (1 - self.size / self.original_size) if self.original_size else 0.0

    @property
    def accuracy_pct(self) -> float:
        """How much of the byte budget was actually used. 100% = landed exactly on target."""
        return 100 * self.size / self.target if self.target else 0.0

    @property
    def pages(self) -> int:
        return self.before.get("doc", {}).get("page_count", 0)

    @property
    def source_dpi(self) -> int | None:
        return self.before.get("doc", {}).get("max_dpi")

    @property
    def effective_dpi(self) -> int | None:
        return self.after.get("doc", {}).get("max_dpi")

    def report(self) -> dict:
        """JSON-safe summary of the whole run."""
        return {
            "target": self.target,
            "original_size": self.original_size,
            "result_size": self.size,
            "saved_pct": round(self.saved_pct, 1),
            "budget_used_pct": round(self.accuracy_pct, 1),
            "headroom": self.target - self.size,
            "engine": self.engine,
            "setting": str(self.setting) if self.setting else "lossless cleanup",
            "dpi_requested": self.setting.dpi if self.setting else None,
            "quality": self.setting.quality if self.setting else None,
            "grayscale": bool(self.setting and self.setting.gray),
            "met_target": self.met_target,
            "elapsed_ms": self.elapsed_ms,
            "probes": len(self.trace),
            "versions": {
                "pymupdf": getattr(pymupdf, "__version__", "?"),
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            },
            "trace": self.trace,
            "before": self.before,
            "after": self.after,
        }


def compress(src: Path, target: int, mode: str = "auto", log=lambda *a: None) -> Result:
    """Compress `src` to at most `target` bytes. Pure computation: writes no files.

    Tries a lossless structural pass first, then the images engine, then raster. If the
    target is simply unreachable, returns the smallest result achievable with met_target
    False rather than raising -- callers decide whether that is acceptable.
    """
    t0 = time.perf_counter()
    raw = src.read_bytes()
    before = analyze(raw)
    trace: list = []

    def done(data, engine, setting, met):
        return Result(data=data, engine=engine, setting=setting, target=target,
                      original_size=len(raw), met_target=met, before=before,
                      after=analyze(data), trace=trace,
                      elapsed_ms=round((time.perf_counter() - t0) * 1000))

    base = lossless(src)
    trace.append({"phase": "lossless", "dpi": None, "quality": None, "gray": False,
                  "bytes": len(base), "fits": len(base) <= target, "ms": 0})
    log(f"  lossless cleanup     -> {human(len(base))}")
    if len(base) <= target:
        return done(base, "lossless", None, True)

    plan = [] if mode == "raster" else [("images", compress_images)]
    if mode != "images":
        plan.append(("raster", compress_raster))

    for name, engine in plan:
        for gray in (False, True):
            if gray:
                log("    ...no colour setting fits; trying grayscale")
            found = search(src, target, engine, log, gray, trace)
            if found:
                data, setting = found
                return done(data, name, setting, True)
        log(f"    {name} engine cannot reach the target")

    # Unreachable: hand back the smallest thing we can actually produce.
    harsh = Setting(DPI_STEPS[-1], QUALITY_STEPS[0], True)
    engine_name, engine = plan[-1]
    return done(engine(src, harsh), engine_name, harsh, False)


# --------------------------------------------------------------------------- cli output

def print_stats(r: Result) -> None:
    """The nerdy view: document deltas, per-image resolution changes, search path."""
    b, a = r.before["doc"], r.after["doc"]

    print("\n  document")
    rows = [
        ("pages", b["page_count"], a["page_count"]),
        ("pdf version", b["pdf_version"], a["pdf_version"]),
        ("file size", human(r.before["bytes"]), human(r.after["bytes"])),
        ("image bytes", f'{human(b["image_bytes"])} ({b["image_share_pct"]}%)',
         f'{human(a["image_bytes"])} ({a["image_share_pct"]}%)'),
        ("images", len(r.before["images"]), len(r.after["images"])),
        ("max image dpi", b["max_dpi"] or "—", a["max_dpi"] or "—"),
        ("text chars", b["text_chars"], a["text_chars"]),
        ("embedded fonts", b["embedded_fonts"], a["embedded_fonts"]),
        ("xref objects", b["xref_objects"], a["xref_objects"]),
        ("fast web view", b["fast_web_view"], a["fast_web_view"]),
    ]
    print(f"    {'':<16}{'before':>22}   {'after':>22}")
    for label, x, y in rows:
        print(f"    {label:<16}{str(x):>22}   {str(y):>22}")

    if r.before["images"]:
        print("\n  images")
        print(f"    {'pg':>3} {'pixels':>13} {'dpi':>5} {'fmt':>6} {'bytes':>10}"
              f"   {'pixels':>13} {'dpi':>5} {'fmt':>6} {'bytes':>10}  {'change':>8}")
        after_by_page: dict[int, list] = {}
        for im in r.after["images"]:
            after_by_page.setdefault(im["page"], []).append(im)
        for im in r.before["images"]:
            peers = after_by_page.get(im["page"], [])
            am = peers.pop(0) if peers else None
            b_px = f"{im['width']}x{im['height']}"
            b_dpi = im["dpi_x"] if im["dpi_x"] is not None else "—"
            a_px = f"{am['width']}x{am['height']}" if am else "—"
            a_dpi = (am["dpi_x"] if am and am["dpi_x"] is not None else "—")
            a_fmt = am["format"][:6] if am else "—"
            a_bytes = human(am["bytes"]) if am else "—"
            delta = "—"
            if am and im.get("bytes") and am.get("bytes"):
                delta = f"{100 * (1 - am['bytes'] / im['bytes']):.0f}%"
            print(f"    {im['page']:>3} {b_px:>13} {str(b_dpi):>5} {im['format'][:6]:>6} "
                  f"{human(im['bytes']):>10}   {a_px:>13} {str(a_dpi):>5} {a_fmt:>6} "
                  f"{a_bytes:>10}  {delta:>8}")

    print(f"\n  search path ({len(r.trace)} probes, {r.elapsed_ms} ms total)")
    for t in r.trace:
        label = ("lossless" if t["phase"] == "lossless"
                 else f"{t['phase']} {t['dpi']}dpi q{t['quality']}{' gray' if t['gray'] else ''}")
        print(f"    {label:<28} {human(t['bytes']):>10}  "
              f"{'fits' if t['fits'] else 'too big':<8} {t['ms']:>5} ms")
    print(f"\n  budget: {human(r.size)} of {human(r.target)} "
          f"({r.accuracy_pct:.1f}% used, {human(r.target - r.size)} spare)")


def process(src: Path, target: int, args, log) -> int:
    print(f"\n{src.name}  —  {human(src.stat().st_size)}  ->  target {human(target)}")

    dest = Path(args.output) if args.output else src.with_name(f"{src.stem}{args.suffix}{src.suffix}")
    if dest.resolve() == src.resolve():
        print("  ! refusing to overwrite the input; pass -o or --suffix", file=sys.stderr)
        return 1

    r = compress(src, target, args.mode, log)
    print(f"  {r.pages} page{'s' * (r.pages != 1)}"
          + (f", source images ~{r.source_dpi} dpi" if r.source_dpi else ""))

    if not r.met_target:
        print(f"  ! cannot reach {human(target)}; smallest achievable is {human(r.size)}. "
              f"Writing that.", file=sys.stderr)

    dest.write_bytes(r.data)
    if r.engine == "lossless":
        print(f"  done: {human(r.size)} with zero pixel loss  ->  {dest.name}")
    else:
        print(f"  done: {human(r.size)}  ({r.saved_pct:.1f}% smaller)  via {r.engine} @ {r.setting}")
        if r.effective_dpi:
            drift = r.setting and abs(r.effective_dpi - r.setting.dpi) > 4
            print(f"        output images ~{r.effective_dpi} dpi"
                  + (f" (requested {r.setting.dpi}; JPEG downsamples in integer steps)" if drift else ""))
        if r.met_target:
            print(f"        {human(target - r.size)} under budget, {r.elapsed_ms} ms")
    print(f"  -> {dest}")

    if args.stats:
        print_stats(r)
    if args.json:
        Path(args.json).write_text(json.dumps(r.report(), indent=2))
        print(f"  report -> {args.json}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compress PDFs to a target file size, keeping as much clarity as possible.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  compress_pdf.py report.pdf -t 1MB\n"
               "  compress_pdf.py scan.pdf -t 900kb -o scan_small.pdf --stats\n"
               "  compress_pdf.py scan.pdf -t 1MB --json report.json\n"
               "  compress_pdf.py *.pdf -t 2MB --suffix _web\n",
    )
    p.add_argument("inputs", nargs="+", type=Path, help="PDF file(s) to compress")
    p.add_argument("-t", "--target", required=True, type=parse_size,
                   help="target size, e.g. 1MB / 900kb / 1500000")
    p.add_argument("-o", "--output", help="output path (single input only)")
    p.add_argument("--suffix", default="_compressed",
                   help="suffix for auto-named output (default: _compressed)")
    p.add_argument("--mode", choices=("auto", "images", "raster"), default="auto",
                   help="auto (default): images engine, fall back to raster")
    p.add_argument("--stats", action="store_true",
                   help="print the full before/after analysis and search path")
    p.add_argument("--json", metavar="FILE", help="write the machine-readable report here")
    p.add_argument("-v", "--verbose", action="store_true", help="show every probe as it runs")
    args = p.parse_args()

    if args.output and len(args.inputs) > 1:
        p.error("-o works with a single input; use --suffix for batches")
    if args.json and len(args.inputs) > 1:
        p.error("--json works with a single input")

    log = print if args.verbose else (lambda *a: None)
    rc = 0
    for src in args.inputs:
        if not src.is_file():
            print(f"! not a file: {src}", file=sys.stderr)
            rc = 1
            continue
        try:
            rc |= process(src, args.target, args, log)
        except Exception as e:
            print(f"! {src.name}: {type(e).__name__}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
