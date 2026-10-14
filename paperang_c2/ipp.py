"""Turn a document that arrived over IPP/AirPrint (PDF or image) into print jobs.

Called by ippeveprinter once per job (see deploy/paperang-ipp.sh).
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import tempfile
from typing import List

from PIL import Image, ImageChops

from . import render

TRAILING_MARGIN = 40        # dots of white kept below the last ink on a page


def trim_bottom(img: Image.Image, margin: int = TRAILING_MARGIN) -> Image.Image:
    """Cut the blank tail of a page: a page is much taller than the receipt it holds."""
    g = img.convert("L")
    bbox = ImageChops.invert(g).getbbox()
    if bbox is None:
        return None                      # completely blank page: skip it
    return g.crop((0, 0, g.width, min(g.height, bbox[3] + margin)))


CROP_MARGIN = 24            # dots of white kept around the content after cropping
MAX_UPSCALE = 2.0           # never enlarge content more than this, so one small line does not become huge


def crop_to_content(page: Image.Image, width: int, margin: int = CROP_MARGIN, max_scale: float = MAX_UPSCALE):
    """Cut the white margins off a page and scale the content up to the paper width.

    AirPrint clients lay a page out for A4/Letter/4x6 with generous margins; on a 110 mm roll that wastes
    paper and shrinks the text. Returns a `width`-wide image (content centred), or None for a blank page.
    """
    g = page.convert("L")
    box = ImageChops.invert(g).getbbox()
    if box is None:
        return None
    l, t, r, b = box
    c = g.crop((max(0, l - margin), max(0, t - margin), min(g.width, r + margin), min(g.height, b + margin)))
    scale = min(width / c.width, max_scale)
    if abs(scale - 1.0) > 1e-3:
        c = c.resize((max(1, round(c.width * scale)), max(1, round(c.height * scale))), Image.LANCZOS)
    if c.width > width:
        c = c.crop((0, 0, width, c.height))
    out = Image.new("L", (width, c.height), 255)
    out.paste(c, ((width - c.width) // 2, 0))
    return out


def pdf_pages(path: str, dpi: int = 300) -> List[Image.Image]:
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", path, os.path.join(d, "p")],
                       check=True, capture_output=True, timeout=120)
        files = sorted(glob.glob(os.path.join(d, "p*.png")))
        if not files:
            raise RuntimeError("pdftoppm produced no pages")
        out = []
        for f in files:
            with Image.open(f) as im:
                out.append(im.convert("L").copy())
        return out


def document_kind(path: str, content_type: str) -> str:
    """MIME type of the file, trusting its bytes over the (often generic) content type."""
    from . import raster
    with open(path, "rb") as f:
        kind = raster.sniff(f.read(16))
    return kind if kind != "application/octet-stream" else (content_type or "").lower()


def load_pages(path: str, content_type: str) -> List[Image.Image]:
    from . import raster
    kind = document_kind(path, content_type)
    if kind in ("image/pwg-raster", "image/urf"):
        with open(path, "rb") as f:
            return raster.decode(f.read())
    if kind == "application/pdf":
        return pdf_pages(path)
    if kind.startswith("image/"):
        return [Image.open(path)]
    raise RuntimeError(f"unsupported document type {content_type!r}")


def run_job(path: str, content_type: str, addr: str | None, mode: str | None = None) -> int:
    from .device import C2
    from .transport import open_transport
    is_photo = document_kind(path, content_type) in ("image/jpeg", "image/png")
    mode = mode or os.environ.get("PAPERANG_MODE") or ("dither" if is_photo else "threshold")
    pages = load_pages(path, content_type)
    t = open_transport(addr)
    try:
        c2 = C2(t)
        info = c2.info()
        printed = 0
        crop = os.environ.get("PAPERANG_CROP", "1") != "0"
        x0, x1 = render.printable_area(info.print_width, info.dpi or 300)
        for pg in pages:
            if not is_photo and crop:
                pg = crop_to_content(pg, x1 - x0)
                if pg is None:
                    continue
                pg = render.place(pg, info.print_width, x0)
                im = render.fit_image(pg, info.print_width, mode)
            else:
                im = render.for_paper(lambda w: render.fit_image(pg, w, mode), info.print_width, info.dpi or 300)
                if not is_photo:
                    im = trim_bottom(im)
                    if im is None:
                        continue
                    im = im.convert("1")
            render.check_height(im)
            c2.print_image(im, info, linger=False)
            printed += 1
        c2.finish_printing()                # once, after the last page
        print(f"printed {printed}/{len(pages)} page(s)", file=sys.stderr)
    finally:
        t.close()
    return 0
