#!/usr/bin/env python3
"""Generate calibration pages for a roll thermal printer. Print them with

    python3 -m paperang_c2 image PAGE.png --raw --mode threshold

(--raw keeps the page exactly as drawn: 1 image pixel = 1 printed dot). Photograph the paper and read it.

  stairs  one bar per 7-row data frame, longer each frame, labelled every 5th. A missing frame is a visible gap.
          Use it to check that no data is dropped (timing rules in docs/PROTOCOL.md).
  ruler   millimetre ticks down the left edge with labels. Shows how much paper is fed before the first row.
  boxes   outline boxes at different horizontal positions and line widths. A box whose right (or left) side is
          missing was printed partly off the paper: this is how the real printable width is found.
  edges   dot-number ticks at both ends of a line. Read the first and last dot that reach the paper.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image, ImageDraw  # noqa: E402

from paperang_c2 import render  # noqa: E402

DPI = 300
MM = DPI / 25.4


def stairs(width=1248, frames=45, rows_per_frame=7):
    im = Image.new("L", (width, rows_per_frame * frames + 20), 255)
    d = ImageDraw.Draw(im)
    font = render.load_font(30)
    for k in range(frames):
        y = k * rows_per_frame
        d.rectangle((0, y, 40 + k * 22, y + 3), fill=0)
        if k % 5 == 0:
            d.text((40 + k * 22 + 14, y - 6), f"#{k + 1}", font=font, fill=0)
    return im


def ruler(width=1248, length_mm=45):
    im = Image.new("L", (width, int(length_mm * MM) + 30), 255)
    d = ImageDraw.Draw(im)
    font = render.load_font(34)
    d.rectangle((0, 0, width - 1, 3), fill=0)
    for mm in range(length_mm + 1):
        y = int(round(mm * MM))
        major = mm % 5 == 0
        d.line((0, y, 180 if major else 90, y), fill=0, width=3 if major else 1)
        if major:
            d.text((200, y - 4 if mm else 8), f"{mm} mm", font=font, fill=0)
    return im


def boxes(width=1248):
    specs = [("A", 18, width - 18, 6), ("B", 0, width - 1, 6), ("C", 60, width - 60, 6),
             ("D", 18, width - 18, 2), ("E", 18, width - 18, 10)]
    h, gap = 56, 34
    im = Image.new("L", (width, 30 + len(specs) * (h + gap)), 255)
    d = ImageDraw.Draw(im)
    font = render.load_font(30)
    y = 20
    for name, x0, x1, t in specs:
        for i in range(t):
            d.rectangle((x0 + i, y + i, x1 - i, y + h - 1 - i), outline=0)
        d.text(((x0 + x1) // 2 - 80, y + h // 2 - 18), f"{name}: {x0}-{x1} w{t}", font=font, fill=0)
        y += h + gap
    return im


def edges(width=1248):
    im = Image.new("L", (width, 190), 255)
    d = ImageDraw.Draw(im)
    font = render.load_font(22)
    d.rectangle((0, 0, width - 1, 5), fill=0)
    for x in range(0, width, 6):
        d.line((x, 189, x, 189 - (70 if x % 60 == 0 else 46 if x % 12 == 0 else 26)), fill=0)
    for n, x in enumerate(list(range(0, 121, 24)) + list(range(width - 144, width, 24))):
        d.text((max(0, x - 8), 12 if n % 2 == 0 else 46), str(x), font=font, fill=0)
    return im


PAGES = {"stairs": stairs, "ruler": ruler, "boxes": boxes, "edges": edges}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page", choices=sorted(PAGES))
    ap.add_argument("out", help="PNG file to write")
    ap.add_argument("--width", type=int, default=1248, help="print width in dots (default 1248)")
    a = ap.parse_args()
    img = PAGES[a.page](a.width)
    img.save(a.out)
    print(f"{a.out}: {img.width}x{img.height} dots ({img.height / MM:.0f} mm tall)")


if __name__ == "__main__":
    main()
