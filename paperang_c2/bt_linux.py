"""RFCOMM transport for Linux (BlueZ) using only the standard library.

Tested on Debian 13 with an Intel AX210 adapter. No pairing and no "trust" is needed, and BlueZ does
not even have to know the device: connecting to the address is enough (checked with the device removed
from BlueZ). `paperang-c2 scan` finds the address.
"""
from __future__ import annotations

import select
import socket

SPP_CHANNEL = 1


class LinuxRFCOMM:
    def __init__(self, address: str | None = None, channel: int = SPP_CHANNEL):
        if not address:
            raise RuntimeError("on Linux pass --addr AA:BB:CC:DD:EE:FF (or set PAPERANG_ADDR)")
        self.address = address.replace("-", ":")
        self.channel = channel
        self._s: socket.socket | None = None
        self.closed = False

    def open(self, timeout: float = 15.0) -> None:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(timeout)
        try:
            s.connect((self.address, self.channel))
        except OSError as e:
            s.close()
            raise RuntimeError(f"could not open RFCOMM to {self.address}: {e}. Paired? On? Not held by a phone?") from e
        s.setblocking(False)
        self._s = s

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            _, w, _ = select.select([], [self._s], [], 5.0)
            if not w:
                raise RuntimeError("RFCOMM write timed out")
            view = view[self._s.send(view):]

    def poll(self, timeout: float = 0.05) -> bytes:
        r, _, _ = select.select([self._s], [], [], timeout)
        if not r:
            return b""
        try:
            data = self._s.recv(4096)
        except BlockingIOError:
            return b""
        if not data:
            self.closed = True
        return data

    def close(self) -> None:
        if self._s is not None:
            self._s.close()
            self._s = None
