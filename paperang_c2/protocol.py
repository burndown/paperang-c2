"""
Paperang "protocol 2" (0xA5-framed) packet builder -- reference implementation
reconstructed from the decompiled overseas app cn.paperang.international 6.5.40.

This is the framing the app switches to when a Paperang-named printer answers the
0xA5 "query protocol version" probe (i/v1.java:1497-1514, 1416-1421). It is NOT
the old 0x02 ... 0x03 framing (dl/b.java:i) nor the 0x07 variant (dl/b.java:r).

Nothing here talks to hardware. Functions only return bytes.

Frame (p/h.java:508-525 s0(), k/a.java:94-111 r()):
    A5 01 | len(payload) LE16 | payload | crc32(payload) LE32 | 5A
    crc32 = standard reflected CRC-32 (table 0xEDB88320) seeded with the fixed
    key 0x35769521 (n/b.java:31-49), i.e. zlib.crc32(payload, 0x35769521).
    Only the payload is covered by the CRC.

Request payload (p/h.java builders):
    group(1) cmd(1) dir(1=request) | len(data) LE16 | data
Response payload (p/h.java:558-569 t0()):
    group cmd dir(2=response, 1=device event) | contentLen LE16 | content
    content = status(1: 1 ok, 3 illegal cmd) | valueLen LE16 | value
TLV parameters (p/h.java:310-323 e0()):  tag(1) len LE16 value ...
"""
from __future__ import annotations

import zlib
from typing import Iterable, List, Optional

CRC_KEY = 0x35769521          # n/b.java:39 (896963873)
HEAD = b"\xA5\x01"            # p/h.java:512-513
TAIL = b"\x5A"                # p/h.java:523 (90)


# --------------------------------------------------------------------------- framing
def le16(v: int) -> bytes:
    return bytes((v & 0xFF, (v >> 8) & 0xFF))          # s/a.java:183 q()


def le32(v: int) -> bytes:
    return (v & 0xFFFFFFFF).to_bytes(4, "little")       # s/a.java:199 s()


def crc32_key(data: bytes) -> int:
    return zlib.crc32(data, CRC_KEY) & 0xFFFFFFFF


def frame(payload: bytes) -> bytes:
    """Wrap a payload: A5 01 len16 payload crc32 5A."""
    if len(payload) > 0xFFFF:
        raise ValueError("payload too long for 16-bit length")
    return HEAD + le16(len(payload)) + payload + le32(crc32_key(payload)) + TAIL


def cmd(group: int, c: int, data: bytes = b"", direction: int = 1) -> bytes:
    """Request frame: payload = group cmd dir len16 data."""
    return frame(bytes((group, c, direction)) + le16(len(data)) + data)


def tlv(params: Iterable[tuple]) -> bytes:
    out = b""
    for tag, value in params:
        out += bytes((tag,)) + le16(len(value)) + value
    return out


# --------------------------------------------------------------------------- commands
# Queries sent by the app's connect sequence (i/v1.java O0/I7/M0/I0/c9/I5/A7/t7).
def q_protocol_version() -> bytes: return cmd(0x01, 0x15)  # h.X, first probe on connect
def q_sn() -> bytes:               return cmd(0x01, 0x02)  # h.Y
def q_hw_version() -> bytes:       return cmd(0x01, 0x06)  # handled in t0 case 6
def q_sw_version() -> bytes:       return cmd(0x01, 0x07)  # h.Z
def q_product_type() -> bytes:     return cmd(0x01, 0x08)  # h.a0 -> TLV(category, type string e.g. "C2")
def q_poweroff_time() -> bytes:    return cmd(0x01, 0x09)  # h.W
def q_battery() -> bytes:          return cmd(0x01, 0x0B)  # h.R (value/10 = %)
def q_max_packet_len() -> bytes:   return cmd(0x01, 0x14)  # h.V -> devMaxLen
def q_max_cache() -> bytes:        return cmd(0x01, 0x20)  # h.U
def q_thermal_info() -> bytes:     return cmd(0x05, 0x01)  # h.E -> JSON {"TPInfo":{...}}
def q_paper_sizes() -> bytes:      return cmd(0x05, 0x02)  # h.J -> TLV list of paper widths (mm)
def q_dpi() -> bytes:              return cmd(0x05, 0x04)  # h.B
def q_hotspot() -> bytes:          return cmd(0x05, 0x05)  # h.D -> heater dots
def q_density() -> bytes:          return cmd(0x05, 0x10)  # t0 group5 case16
def q_size_details() -> bytes:     return cmd(0x05, 0x28)  # h.K -> JSON {"TPSizeInfo":[{PaperWidth,HotSpot,OffsetStart}]}


def set_density(level: int) -> bytes:                       # h.o: 05 11 01 0100 level
    return cmd(0x05, 0x11, bytes((level & 0xFF,)))


def print_start() -> bytes:                                 # h.v0 -> h.A: 05 19 01 0000
    return cmd(0x05, 0x19)


def print_end() -> bytes:                                   # h.u0: 05 1A 01 0000
    return cmd(0x05, 0x1A)


def feed(amount: int = 0) -> bytes:                         # h.i0 (amount 0) / h.n(i)
    return cmd(0x05, 0x16, le16(amount))


def connect_queries() -> List[bytes]:
    """Order the app uses after RFCOMM connect (protocol 2 branch)."""
    return [q_protocol_version(), q_sn(), q_size_details(), q_thermal_info(),
            q_dpi(), q_hotspot(), q_max_packet_len(), q_paper_sizes(),
            q_sw_version(), q_product_type(), q_max_cache()]


# --------------------------------------------------------------------------- image
def image_to_rows(img) -> bytes:
    """1-bit raster, MSB first, 1 = black, rows padded to whole bytes
    (a/a.java:15-56). Accepts any PIL image; converts with threshold 128."""
    im = img.convert("L").point(lambda p: 255 if p >= 128 else 0, mode="1")
    raw = im.tobytes()                      # PIL '1': MSB first, 1 = white
    return bytes(b ^ 0xFF for b in raw)     # invert -> 1 = black (callers enforce width % 8 == 0)


def _rows(img, width_px: int) -> bytes:
    if img.width != width_px:
        raise ValueError(f"image width {img.width} != print width {width_px}; scale first")
    if width_px % 8:
        raise ValueError("print width must be a multiple of 8")
    return image_to_rows(img)


def chunk_size(print_width: int, max_len: int) -> int:
    """i/v1.java:1628-1643 B2(): smallest multiple of row bytes >= maxLen - 2*rowBytes."""
    w = print_width // 8
    n = 0
    while n < max_len - w - w:
        n += w
    if n <= 0:
        raise ValueError("max_len too small / not queried")
    return n


def data_frame(seq: int, chunk: bytes, print_width: int, offset_start: int) -> bytes:
    """dl/b.java:157-180 j() + p/h.java:390-398 j0():
         inner   = 01 | width/8 LE16 | offsetStart LE16 | 00 | len(chunk) LE16 | chunk
         outer   = seq(1-based) LE16 | len(inner) LE16 | inner
         payload = 05 1B 01 | len(outer) LE16 | outer
    """
    inner = b"\x01" + le16(print_width // 8) + le16(offset_start) + b"\x00" + le16(len(chunk)) + chunk
    outer = le16(seq) + le16(len(inner)) + inner
    return frame(b"\x05\x1B\x01" + le16(len(outer)) + outer)


def build_print_job(img, print_width: Optional[int] = None, offset_start: int = 0,
                    max_len: int = 1024, density: Optional[int] = None,
                    feed_after: bool = True) -> List[bytes]:
    """Ordered frames for one 1-bit image, mirroring i/v1.java n2()/o2():
       [set density] print_start, data frames..., print_end, feed(0).
    print_width / offset_start should come from q_size_details() (HotSpot/OffsetStart
    for the loaded paper width); max_len from q_max_packet_len()."""
    width = print_width or img.width
    data = _rows(img, width)
    step = chunk_size(width, max_len)
    frames: List[bytes] = []
    if density is not None:
        frames.append(set_density(density))
    frames.append(print_start())
    for i in range(0, len(data), step):
        frames.append(data_frame(i // step + 1, data[i:i + step], width, offset_start))
    frames.append(print_end())
    if feed_after:
        frames.append(feed(0))
    return frames


# --------------------------------------------------------------------------- parsing
def parse_frames(buf: bytes):
    """Split a receive buffer into decoded responses. Returns (list, leftover)."""
    out, i = [], 0
    while i + 4 <= len(buf):
        if buf[i] != 0xA5:
            i += 1
            continue
        ln = buf[i + 2] | (buf[i + 3] << 8)
        end = i + 4 + ln + 5
        if end > len(buf):
            break
        payload = buf[i + 4:i + 4 + ln]
        crc = int.from_bytes(buf[i + 4 + ln:i + 8 + ln], "little")
        r = {"raw": buf[i:end], "crc_ok": crc == crc32_key(payload) and buf[end - 1] == 0x5A}
        if len(payload) >= 5:
            r.update(group=payload[0], cmd=payload[1], dir=payload[2])
            content = payload[5:5 + (payload[3] | payload[4] << 8)]
            r["content"] = content
            if len(content) >= 3:
                r["status"] = content[0]
                vl = content[1] | content[2] << 8
                r["value"] = content[3:3 + vl]
        out.append(r)
        i = end
    return out, buf[i:]


# --------------------------------------------------------------------------- self-test
def _crc_table_check() -> None:
    # Same algorithm as n/b.java a(): table-driven reflected CRC32 seeded with key.
    tbl = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        tbl.append(c)
    assert tbl[1] == 1996959894 and tbl[255] == 755167117    # n/b.java table
    data = bytes(range(37))
    c = CRC_KEY ^ 0xFFFFFFFF
    for b in data:
        c = (c >> 8) ^ tbl[(b ^ c) & 0xFF]
    assert (c ^ 0xFFFFFFFF) == crc32_key(data)


if __name__ == "__main__":
    _crc_table_check()
    for f in connect_queries():
        print(f.hex(" "))
    try:
        from PIL import Image, ImageDraw
        w = 576
        im = Image.new("1", (w, 40), 1)
        ImageDraw.Draw(im).rectangle([0, 0, w - 1, 39], outline=0)
        job = build_print_job(im, max_len=1024)
        print(f"{len(job)} frames; first data frame: {job[1][:24].hex(' ')} ...")
    except ImportError:
        print("PIL not installed; skipped image demo")
