"""Pick the Bluetooth transport for this OS, and make sure only one job talks to the printer at a time."""
from __future__ import annotations

import fcntl
import os
import sys
import tempfile
import time

LOCK_PATH = os.path.join(tempfile.gettempdir(), "paperang-c2.lock")
CLOSED_PATH = LOCK_PATH + ".closed"
# The printer resets the link if it is reconnected right after a disconnect (measured: 0.3 s fails,
# 1 s works), e.g. the web UI's "query" followed at once by "print". Keep a safe gap between connections.
RECONNECT_GAP = 1.5


class _Locked:
    """Holds an exclusive file lock for the life of the connection.

    The printer serves one Bluetooth host at a time and drops the link if two jobs
    interleave, and several things on one machine can print (web UI, AirPrint, CLI).
    """

    def __init__(self, inner, lock_timeout: float):
        self._inner = inner
        self._lock_timeout = lock_timeout
        self._fd = None

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def open(self) -> None:
        self._fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
        deadline = time.time() + self._lock_timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise RuntimeError("the printer is busy with another job (lock timeout)")
                time.sleep(0.3)
        try:
            wait = RECONNECT_GAP - (time.time() - os.stat(CLOSED_PATH).st_mtime)
        except OSError:
            wait = 0.0
        if wait > 0:
            time.sleep(wait)
        try:
            self._inner.open()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            if self._fd is not None:
                try:
                    with open(CLOSED_PATH, "a"):
                        os.utime(CLOSED_PATH)           # remember when we let go of the printer
                except OSError:
                    pass
                os.close(self._fd)          # closing the fd releases the flock
                self._fd = None


def open_transport(address: str | None = None, lock_timeout: float = 120.0):
    if sys.platform == "darwin":
        from .bt_macos import MacRFCOMM
        inner = MacRFCOMM(address)
    elif sys.platform.startswith("linux"):
        from .bt_linux import LinuxRFCOMM
        inner = LinuxRFCOMM(address)
    else:
        raise RuntimeError(f"unsupported platform {sys.platform}")
    t = _Locked(inner, lock_timeout)
    t.open()
    return t


def scan(prefix: str = "Paperang", seconds: int = 12):
    """[(address, name)] of printers: paired ones on macOS, devices heard nearby (BlueZ) on Linux."""
    if sys.platform == "darwin":
        from .bt_macos import list_paired
        return list_paired(prefix)
    if sys.platform.startswith("linux"):
        import re
        import subprocess
        subprocess.run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"],
                       capture_output=True, text=True, timeout=seconds + 15)
        out = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=15).stdout
        found = []
        for m in re.finditer(r"^Device ([0-9A-Fa-f:]{17}) (.+)$", out, re.M):
            if m.group(2).startswith(prefix):
                found.append((m.group(1).upper(), m.group(2)))
        return found
    raise RuntimeError(f"unsupported platform {sys.platform}")
