"""Turn text / images into print-width 1-bit bitmaps."""
from __future__ import annotations

import os
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

# The print head is 1248 dots wide (110 mm) but the roll may be narrower. Measured on a "4 inch" roll:
# the left edge of the paper is dot 0 and everything beyond about dot 1200 (4 in = 101.6 mm at 300 dpi)
# lands outside the paper, so frames lost their right-hand edge. Keep content inside the paper.
PAPER_WIDTH_MM = float(os.environ.get("PAPERANG_PAPER_WIDTH_MM", "101.6"))
EDGE_MARGIN = 12            # dots (1 mm) kept free at both paper edges

MAX_HEIGHT_DOTS = 6000          # ~500 mm at 300 dpi; refuse anything longer by default

_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux (Debian: fonts-noto-cjk). fc-match is no help: it often picks a font without CJK.
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def printable_area(print_width: int, dpi: int = 300):
    """(x0, x1): the dots of one print line that actually fall on the paper, minus a safety margin."""
    paper_dots = round(PAPER_WIDTH_MM / 25.4 * dpi)
    return EDGE_MARGIN, min(print_width, paper_dots) - EDGE_MARGIN


def place(img: Image.Image, canvas_width: int, x0: int) -> Image.Image:
    """Put img on a white canvas `canvas_width` wide, its left edge at dot x0."""
    white = 1 if img.mode == "1" else 255
    out = Image.new(img.mode, (canvas_width, img.height), white)
    out.paste(img, (x0, 0))
    return out


def for_paper(build, print_width: int, dpi: int = 300) -> Image.Image:
    """build(width) -> image of exactly that width; result is a print_width-wide line image whose content
    sits inside the printable part of the paper."""
    x0, x1 = printable_area(print_width, dpi)
    return place(build(x1 - x0), print_width, x0)


def load_font(size: int, path: Optional[str] = None) -> ImageFont.FreeTypeFont:
    for cand in ([path] if path else []) + _FONT_CANDIDATES:
        if cand and os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    raise RuntimeError("no CJK font found; install fonts-noto-cjk or pass --font /path/to/font.ttc")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def text_to_image(text: str, width: int, size: int = 56, align: str = "left",
                  margin: int = 40, font_path: Optional[str] = None) -> Image.Image:
    font = load_font(size, font_path)
    probe = ImageDraw.Draw(Image.new("L", (width, 10)))
    lines = _wrap(probe, text, font, width - 2 * margin)
    step = int(size * 1.35)
    img = Image.new("L", (width, margin * 2 + step * max(1, len(lines))), 255)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        w = d.textlength(line, font=font)
        x = {"left": margin, "center": (width - w) / 2, "right": width - margin - w}[align]
        d.text((x, margin + i * step), line, font=font, fill=0)
    return img


def fit_image(src: Image.Image, width: int, mode: str = "dither", rotate_landscape: bool = False) -> Image.Image:
    """Scale to `width` and reduce to 1 bit. mode: dither (Floyd-Steinberg) | threshold | none (already 1-bit)."""
    im = src
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im.convert("RGBA"))
        im = bg
    im = ImageOps.exif_transpose(im).convert("L")
    if rotate_landscape and im.width > im.height:
        im = im.rotate(90, expand=True)
    if im.width != width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    im = ImageOps.autocontrast(im)
    if mode == "dither":
        return im.convert("1")                      # Floyd-Steinberg by default in Pillow
    if mode == "threshold":
        return im.point(lambda v: 255 if v >= 128 else 0).convert("1")
    if mode == "none":
        return im.convert("1")
    raise ValueError(f"unknown mode {mode!r}")


def check_height(img: Image.Image, limit: int = MAX_HEIGHT_DOTS) -> None:
    if img.height > limit:
        raise ValueError(f"image is {img.height} dots tall (limit {limit}); pass a higher limit if you really mean it")
