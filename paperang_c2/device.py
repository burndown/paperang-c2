"""High-level C2 operations on top of a byte transport (see bt_macos.MacRFCOMM)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import protocol as p


class PrinterError(RuntimeError):
    pass


@dataclass
class PrinterInfo:
    serial: str = ""
    firmware: str = ""
    model: str = ""
    battery_percent: float = 0.0
    dpi: int = 0
    max_packet: int = 0
    paper_mm: int = 0                       # currently loaded paper width
    paper_sizes_mm: List[int] = field(default_factory=list)
    print_width: int = 0                    # dots per line for the loaded paper (HotSpot)
    offset_start: int = 0
    raw: Dict[str, str] = field(default_factory=dict)


def parse_tlv(value: bytes) -> Dict[int, bytes]:
    out, i = {}, 0
    while i + 3 <= len(value):
        tag, ln = value[i], value[i + 1] | value[i + 2] << 8
        out[tag] = value[i + 3:i + 3 + ln]
        i += 3 + ln
    return out


class C2:
    def __init__(self, transport):
        self.t = transport
        self._buf = b""
        self.responses: List[dict] = []
        self._job_started: Optional[float] = None
        self._job_mm = 0.0

    # ---- low level -------------------------------------------------------------
    def _drain(self, timeout: float = 0.02) -> None:
        self._buf += self.t.poll(timeout)
        frames, self._buf = p.parse_frames(self._buf)
        for f in frames:
            if f.get("dir") == 2:
                self.responses.append(f)

    def _take(self, group: int, cmd: int) -> Optional[dict]:
        for i, r in enumerate(self.responses):
            if r.get("group") == group and r.get("cmd") == cmd:
                return self.responses.pop(i)
        return None

    def request(self, frame: bytes, group: int, cmd: int, timeout: float = 3.0) -> dict:
        self.t.write(frame)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._drain(0.05)
            r = self._take(group, cmd)
            if r is not None:
                if not r.get("crc_ok"):
                    raise PrinterError(f"bad checksum in reply to {group:02x}/{cmd:02x}")
                if r.get("status") != 1:
                    raise PrinterError(f"printer rejected {group:02x}/{cmd:02x} (status {r.get('status')})")
                return r
        raise PrinterError(f"no reply to {group:02x}/{cmd:02x} within {timeout}s")

    # ---- queries ---------------------------------------------------------------
    def info(self) -> PrinterInfo:
        v = lambda frame, g, c: self.request(frame, g, c)["value"]
        i = PrinterInfo()
        i.firmware = v(p.q_protocol_version(), 0x01, 0x15).decode("ascii", "replace")
        i.serial = v(p.q_sn(), 0x01, 0x02).decode("ascii", "replace")
        tl = parse_tlv(v(p.q_product_type(), 0x01, 0x08))
        i.model = tl.get(2, b"").decode("ascii", "replace")
        raw = int.from_bytes(v(p.q_battery(), 0x01, 0x0B), "little")
        i.battery_percent = raw / 10.0
        i.max_packet = int.from_bytes(v(p.q_max_packet_len(), 0x01, 0x14), "little")
        i.dpi = int.from_bytes(v(p.q_dpi(), 0x05, 0x04), "little")
        i.paper_sizes_mm = [int.from_bytes(x, "little") for _, x in sorted(parse_tlv(v(p.q_paper_sizes(), 0x05, 0x02)).items())]
        thermal = json.loads(v(p.q_thermal_info(), 0x05, 0x01).decode("utf-8"))
        sizes = json.loads(v(p.q_size_details(), 0x05, 0x28).decode("utf-8"))["TPSizeInfo"]
        i.paper_mm = int(thermal["TPInfo"]["TPCurrentSize"])
        for s in sizes:
            if s["PaperWidth"] == i.paper_mm:
                i.print_width, i.offset_start = int(s["HotSpot"]), int(s["OffsetStart"])
        if not i.print_width:
            raise PrinterError(f"no print width listed for {i.paper_mm} mm paper: {sizes}")
        i.raw = {"thermal": json.dumps(thermal, ensure_ascii=False), "sizes": json.dumps(sizes)}
        return i

    # ---- printing --------------------------------------------------------------
    # The printer acknowledges frames as it *receives* them, long before the paper has moved. If the link is
    # closed at that point it throws away whatever it has not printed yet (measured: a 28 mm job closed
    # 0.75 s after the last ack lost its first rows, closed after 1.8 s still lost a frame, after 3.2 s was
    # complete). So after sending we keep the link open until the paper should be done.
    LINGER_BASE = 1.5          # seconds of slack after the nominal print time
    PRINT_SPEED_MM_S = 8.0     # deliberately slower than the real ~10 mm/s so a long job is never cut short

    def print_image(self, img, info: PrinterInfo, density: Optional[int] = None,
                    progress: Optional[Callable[[int, int], None]] = None, linger: bool = True) -> None:
        """Send a 1-bit-style PIL image whose width equals info.print_width.

        The official app writes start, every data frame, end and feed back to back and never waits
        for the data acks. Waiting for each ack leaves gaps between frames and did lose frames
        in testing, so we burst, then read the acks. Pass linger=False when printing several pages
        in a row and call finish_printing() after the last one.
        """
        frames = p.build_print_job(img, print_width=info.print_width, offset_start=info.offset_start,
                                   max_len=info.max_packet, density=density, feed_after=False)
        frames.append(p.feed(0))
        n_data = sum(1 for f in frames if f[4:7] == b"\x05\x1b\x01")
        if self._job_started is None:
            self._job_started = time.time()
        self._job_mm += img.height / (info.dpi or 300) * 25.4
        sent = 0
        for f in frames:
            self.t.write(f)
            if f[4:7] == b"\x05\x1b\x01":
                sent += 1
                if progress:
                    progress(sent, n_data)
        # every frame is acknowledged; check them all once the burst is on its way
        self._expect_acks(n_data, (0x05, 0x1B), "data frame")
        for group, cmd, what in ((0x05, 0x19, "print start"), (0x05, 0x1A, "print end"), (0x05, 0x16, "feed")):
            self._expect_acks(1, (group, cmd), what, timeout=15.0)
        if density is not None:
            self._expect_acks(1, (0x05, 0x11), "density")
        if linger:
            self.finish_printing()

    def finish_printing(self) -> None:
        """Hold the link open until the paper should have finished moving, then forget the job."""
        if self._job_started is None:
            return
        deadline = self._job_started + self.LINGER_BASE + self._job_mm / self.PRINT_SPEED_MM_S
        self._job_started, self._job_mm = None, 0.0
        while time.time() < deadline:
            self._drain(0.1)

    def _expect_acks(self, count: int, which, what: str, timeout: float = 20.0) -> None:
        got, deadline = 0, time.time() + timeout
        while got < count and time.time() < deadline:
            self._drain(0.05)
            while True:
                r = self._take(*which)
                if r is None:
                    break
                if r.get("status") != 1:
                    raise PrinterError(f"printer rejected a {what} (status {r.get('status')})")
                got += 1
        if got < count:
            raise PrinterError(f"only {got}/{count} {what} acknowledgements arrived")

