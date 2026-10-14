"""RFCOMM transport for macOS via IOBluetooth (PyObjC).

The printer shows up as a "Printer" class device, so the /dev/cu.* serial port
macOS creates for it never actually connects. Opening the RFCOMM channel through
IOBluetooth does. The calling process needs Bluetooth permission (run it from
Terminal, which can show the prompt) and must be on the main thread, because the
channel delegate is driven by the thread's run loop.
"""
from __future__ import annotations

import time

import objc
from Foundation import NSDate, NSObject, NSRunLoop
import IOBluetooth as IB

SPP_CHANNEL = 1          # the C2 exposes SDP service "SPP slave" on RFCOMM channel 1


def _spin(seconds: float) -> None:
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


class _Delegate(NSObject):
    def init(self):
        self = objc.super(_Delegate, self).init()
        self.status = None
        self.rx = bytearray()
        self.closed = False
        return self

    def rfcommChannelOpenComplete_status_(self, ch, status):
        self.status = status

    def rfcommChannelData_data_length_(self, ch, data, length):
        self.rx.extend(bytes(data)[:length])

    def rfcommChannelClosed_(self, ch):
        self.closed = True


def list_paired(prefix: str = "Paperang"):
    """[(address, name)] of paired Bluetooth devices whose name starts with prefix."""
    return [(d.addressString().replace("-", ":").upper(), d.name() or "") for d in (IB.IOBluetoothDevice.pairedDevices() or [])
            if (d.name() or "").startswith(prefix)]


def find_printer(prefix: str = "Paperang") -> str:
    """Address (AA-BB-..) of the first paired device whose name starts with prefix."""
    for dev in IB.IOBluetoothDevice.pairedDevices() or []:
        if (dev.name() or "").startswith(prefix):
            return dev.addressString()
    raise RuntimeError(
        f"no paired Bluetooth device named {prefix}*; pair it in System Settings first "
        "(turn off Bluetooth on any phone or tablet that holds the printer)"
    )


class MacRFCOMM:
    def __init__(self, address: str | None = None, channel: int = SPP_CHANNEL):
        self.address = address or find_printer()
        self.channel = channel
        self._dev = None
        self._ch = None
        self._delegate = None

    def open(self, timeout: float = 15.0) -> None:
        self._dev = IB.IOBluetoothDevice.deviceWithAddressString_(self.address)
        if self._dev is None:
            raise RuntimeError(f"bad Bluetooth address {self.address!r}")
        self._dev.openConnection()
        _spin(2.0)
        self._delegate = _Delegate.alloc().init()
        res = self._dev.openRFCOMMChannelAsync_withChannelID_delegate_(None, self.channel, self._delegate)
        self._ch = res[1] if isinstance(res, tuple) else None
        deadline = time.time() + timeout
        while self._delegate.status is None and time.time() < deadline:
            _spin(0.2)
        if self._delegate.status != 0 or self._ch is None:
            self.close()
            raise RuntimeError(
                f"could not open RFCOMM channel (status={self._delegate.status}). "
                "Is the printer on, in range, and not connected to a phone or tablet?"
            )

    def write(self, data: bytes) -> None:
        # IOBluetooth takes at most the channel MTU per call; chunk to stay under it.
        for i in range(0, len(data), 500):
            part = data[i:i + 500]
            rc = self._ch.writeSync_length_(part, len(part))
            if rc != 0:
                raise RuntimeError(f"RFCOMM write failed (IOReturn {rc:#x})")

    def poll(self, timeout: float = 0.05) -> bytes:
        """Spin the run loop for up to `timeout` seconds and return bytes received."""
        _spin(timeout)
        out = bytes(self._delegate.rx)
        self._delegate.rx.clear()
        return out

    @property
    def closed(self) -> bool:
        return bool(self._delegate and self._delegate.closed)

    def close(self, timeout: float = 8.0) -> None:
        try:
            if self._ch is not None:
                self._ch.closeChannel()
            if self._dev is not None:
                self._dev.closeConnection()
                # macOS keeps the baseband link up for a while after our process is done with it, and the
                # printer serves one host at a time: wait until it is really gone so a phone or another
                # host (e.g. a Linux bridge) can connect right afterwards.
                deadline = time.time() + timeout
                while self._dev.isConnected() and time.time() < deadline:
                    _spin(0.2)
        finally:
            self._ch = None
