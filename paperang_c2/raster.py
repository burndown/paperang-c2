"""Decode the two raster formats AirPrint-style clients send: Apple URF (image/urf) and PWG raster (image/pwg-raster).

Both are a small page header followed by rows compressed the same way:
    line-repeat byte (n -> the row appears n+1 times), then pixel groups:
        0..127   repeat the next pixel (c+1) times
        129..255 (257-c) literal pixels follow
        128      the rest of the row is white
PWG: 1-bit, 8-bit gray and 24-bit RGB. URF: 8-bit gray and 24-bit RGB.
"""
from __future__ import annotations

import struct
from typing import List

from PIL import Image

PWG_SYNC = b"RaS2"
URF_SYNC = b"UNIRAST\x00"
PWG_HEADER = 1796


class RasterError(ValueError):
    pass


def sniff(data: bytes) -> str:
    """MIME type from the first bytes (ippeveprinter may call everything application/octet-stream)."""
    if data.startswith(PWG_SYNC):
        return "image/pwg-raster"
    if data.startswith(URF_SYNC):
        return "image/urf"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return "application/octet-stream"


def _decode_rows(buf: bytes, pos: int, row_bytes: int, height: int, unit: int, white: int) -> tuple:
    """Return (raw bytes, new position). `unit` = bytes per compressed pixel (1 for 1/8-bit, 3 for RGB)."""
    out = bytearray()
    fill = bytes((white,)) * unit
    rows = 0
    while rows < height:
        if pos >= len(buf):
            raise RasterError("raster data ended early")
        repeat = buf[pos] + 1
        pos += 1
        line = bytearray()
        while len(line) < row_bytes:
            if pos >= len(buf):
                raise RasterError("raster data ended inside a row")
            c = buf[pos]
            pos += 1
            if c <= 127:
                line += buf[pos:pos + unit] * (c + 1)
                pos += unit
            elif c == 128:
                line += fill * ((row_bytes - len(line) + unit - 1) // unit)
            else:
                n = 257 - c
                line += buf[pos:pos + n * unit]
                pos += n * unit
        del line[row_bytes:]                  # a final group may overshoot by padding
        repeat = min(repeat, height - rows)
        out += bytes(line) * repeat
        rows += repeat
    return bytes(out), pos


def _to_image(raw: bytes, width: int, height: int, bits: int, ink_is_one: bool) -> Image.Image:
    if bits == 1:
        im = Image.frombytes("1", (width, height), raw)       # Pillow: 1 = white
        if ink_is_one:
            im = im.point(lambda v: 255 - v)
        return im.convert("L")
    if bits == 8:
        return Image.frombytes("L", (width, height), raw)
    if bits == 24:
        return Image.frombytes("RGB", (width, height), raw).convert("L")
    raise RasterError(f"unsupported pixel size {bits} bits")


# CUPS colour spaces a PWG header can carry (offset 400) that use 1 = ink for 1-bit data
_PWG_BLACK_IS_ONE = {3}                          # CUPS_CSPACE_K


def decode_pwg(data: bytes) -> List[Image.Image]:
    pages, pos = [], len(PWG_SYNC)
    while pos + PWG_HEADER <= len(data):
        h = data[pos:pos + PWG_HEADER]
        width, height = struct.unpack(">II", h[372:380])
        bits = struct.unpack(">I", h[388:392])[0]
        colorspace = struct.unpack(">I", h[400:404])[0]
        if bits not in (1, 8, 24):
            raise RasterError(f"PWG raster with {bits} bits per pixel is not supported")
        ink_is_one = colorspace in _PWG_BLACK_IS_ONE
        row_bytes = (width * bits + 7) // 8
        unit = 1 if bits < 24 else 3
        white = 0x00 if (bits == 1 and ink_is_one) else 0xFF
        raw, pos = _decode_rows(data, pos + PWG_HEADER, row_bytes, height, unit, white)
        pages.append(_to_image(raw, width, height, bits, ink_is_one))
    return pages


def decode_urf(data: bytes) -> List[Image.Image]:
    count = struct.unpack(">I", data[8:12])[0]          # 0 means "streamed: read until the end"
    pages, pos = [], 12
    while (count == 0 or len(pages) < count) and pos < len(data):
        if pos + 32 > len(data):
            raise RasterError("URF page header truncated")
        bits = data[pos]
        width, height = struct.unpack(">II", data[pos + 12:pos + 20])
        if bits not in (1, 8, 24):
            raise RasterError(f"URF with {bits} bits per pixel is not supported")
        unit = 1 if bits < 24 else 3
        row_bytes = (width * bits + 7) // 8
        raw, pos = _decode_rows(data, pos + 32, row_bytes, height, unit, 0x00 if bits == 1 else 0xFF)
        pages.append(_to_image(raw, width, height, bits, bits == 1))   # 1-bit URF: 1 = ink
    return pages


def decode(data: bytes) -> List[Image.Image]:
    kind = sniff(data)
    if kind == "image/pwg-raster":
        return decode_pwg(data)
    if kind == "image/urf":
        return decode_urf(data)
    raise RasterError(f"not a raster file ({kind})")
