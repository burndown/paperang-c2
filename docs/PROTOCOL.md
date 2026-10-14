# Paperang C2 protocol reference

[中文版](PROTOCOL.zh-CN.md)

This document describes how to talk to a Paperang C2 thermal printer (sold in China as 作业帮喵喵机 C2) from your own code. The printer advertises over Bluetooth as `Paperang_C2_xxxx` and enumerates on USB as `34d6:01a2`.

The C2 speaks a frame format that starts with `0xA5` and ends with `0x5A`. This document calls it **protocol 2**. It is not the older Paperang `0x02 ... 0x03` framing that earlier open-source tools implement; a C2 ignores that framing completely (see [Dead ends](#dead-ends)).

> **Unofficial.** This is independent interoperability research done on the author's own device. It is not affiliated with, endorsed by, or supported by the printer's vendor. Product names and trademarks belong to their respective owners. The protocol was worked out from experiments on real hardware and from observing the behaviour of the vendor's own app. No vendor code is included or reproduced here.

## Test status and confidence labels

Everything marked **[FACT]** was verified on real hardware: one C2 unit, firmware `01.00.22`, paper-width setting 110 mm with a 4-inch (101.6 mm) roll loaded, driven over classic Bluetooth from macOS and from Linux. Everything marked **[INFERENCE]** was taken from the observed behaviour of the vendor's app and has not been confirmed on the printer. No other Paperang model, firmware version or transport has been tested.

## Transport

**Classic Bluetooth SPP [FACT].** The printer exposes an RFCOMM serial port on channel 1 (SDP service name `SPP slave`). Frames are written as raw bytes: no extra encryption, no extra segmentation layer.

**One host at a time [FACT].** The printer accepts a single Bluetooth connection. If a phone running the vendor's app is connected (even with the app in the background), other hosts cannot connect.

**macOS note [FACT].** macOS classifies the C2 as a printer-type device. The virtual serial port it creates (`/dev/cu.Paperang_C2_xxxx`) never connects; the host must open the RFCOMM channel itself through the IOBluetooth framework, and the process needs Bluetooth permission. On Linux a plain RFCOMM socket to channel 1 works.

**USB (not verified).** The USB interface is a printer-class interface with a bulk OUT endpoint `0x01` and a bulk IN endpoint `0x81`. Writes succeed, but the old Paperang framing and ESC/POS/TSPL/CPCL/ZPL all got no response. Protocol 2 frames have **not** been tried over USB, so whether USB works with this protocol is an open question.

## Framing [FACT]

```
A5 01 | len (LE16) | payload | crc32 (LE32) | 5A
```

`len` is the payload length. The CRC covers the payload only. It is the standard reflected CRC-32 (polynomial table `0xEDB88320`), but seeded with the fixed key `0x35769521` instead of the usual zero, which in Python is `zlib.crc32(payload, 0x35769521)`. Every reply received during testing passed this check. Unlike the old protocol, the key is fixed and there is no "set CRC key" handshake.

**Request payload:**

```
group (1) | cmd (1) | dir = 01 | dataLen (LE16) | data
```

**Response payload:**

```
group (1) | cmd (1) | dir = 02 | contentLen (LE16) | content
content = status (1) | valueLen (LE16) | value
```

`status` is `1` for success and `3` for an illegal command. Payloads with `dir = 01` coming *from* the printer are unsolicited device events. Commands with several parameters use TLV encoding: `tag (1) | len (LE16) | value`, repeated.

All multi-byte integers are little-endian.

## Minimal example

The frame `a5010500011501000041d235195a` is the probe: "query protocol / firmware version" (group `01`, cmd `15`, no data). **[INFERENCE]** The vendor's app sends it first on every connection and uses the presence of a reply to decide that the printer speaks protocol 2. The following self-contained snippet builds that frame and parses a reply of the expected shape. The reply bytes below were computed from the format described above for firmware `01.00.22`; they are not a captured trace.

```python
import struct, zlib

KEY = 0x35769521

def frame(payload: bytes) -> bytes:
    return (b"\xa5\x01" + struct.pack("<H", len(payload)) + payload
            + struct.pack("<I", zlib.crc32(payload, KEY)) + b"\x5a")

def request(group: int, cmd: int, data: bytes = b"") -> bytes:
    return frame(bytes((group, cmd, 1)) + struct.pack("<H", len(data)) + data)

probe = request(0x01, 0x15)
assert probe.hex() == "a5010500011501000041d235195a"

def parse(buf: bytes):
    assert buf[0] == 0xA5 and buf[-1] == 0x5A
    (n,) = struct.unpack_from("<H", buf, 2)
    payload = buf[4:4 + n]
    (crc,) = struct.unpack_from("<I", buf, 4 + n)
    assert crc == zlib.crc32(payload, KEY), "bad CRC"
    group, cmd, direction = payload[:3]
    content = payload[5:5 + struct.unpack_from("<H", payload, 3)[0]]
    status, vlen = content[0], struct.unpack_from("<H", content, 1)[0]
    return group, cmd, direction, status, content[3:3 + vlen]

reply = bytes.fromhex("a50110000115020b0001080030312e30302e3232873507995a")
print(parse(reply))   # (1, 21, 2, 1, b'01.00.22')
```

Open an RFCOMM connection to channel 1, write `probe`, read until a complete frame arrives, and pass it to `parse`.

## Command table

### Queries [FACT]

All of these returned a successful reply on the test unit.

| Query | group/cmd | Value |
|---|---|---|
| Protocol / firmware version | 01/15 | ASCII, e.g. `01.00.22` |
| Serial number | 01/02 | ASCII, e.g. `C200H0XXXXXXXX` |
| Software version | 01/07 | ASCII |
| Product type | 01/08 | TLV: tag 1 = category, tag 2 = model string `C2` |
| Battery | 01/0B | LE16; divide by 10 for percent |
| Max packet length | 01/14 | LE16; `1297` on the C2 |
| Max cache | 01/20 | Reply value `08 00` (8). Meaning unknown; the app stores it but does not appear to use it. |
| DPI | 05/04 | LE16; `300` on the C2 |
| Supported paper widths | 05/02 | TLV, each value LE16 in mm; `57`, `79`, `110` on the C2 |
| Heater dots | 05/05 | LE16; `1248` with the 110 mm setting |
| Density | 05/10 | 1 byte |
| Thermal head info | 05/01 | JSON `{"TPInfo": {...}}`, includes `TPCurrentSize` (current paper width setting, mm) and `TPDevDPI` |
| Per-width print parameters | 05/28 | JSON `{"TPSizeInfo": [{"PaperWidth", "HotSpot", "OffsetStart"}, ...]}` |

### Queries [INFERENCE]

The app also knows hardware version `01/06` and auto power-off time `01/09`. These are implemented in the reference code but their replies have not been checked on hardware.

### Print and control commands

| Command | group/cmd | Data | Notes |
|---|---|---|---|
| Set density | 05/11 | 1 byte level | **[INFERENCE]** Never sent to the test unit; whether it replies, and the valid range, are unknown. |
| Print start | 05/19 | none | **[FACT]** Reply status 1. |
| Print data | 05/1B | see below | **[FACT]** One reply (status 1) per data frame. |
| Print end | 05/1A | none | **[FACT]** Reply status 1. |
| Feed | 05/16 | LE16 amount | **[FACT]** with amount `0`; reply status 1. Other amounts untested. |

The connect sequence observed in the app **[INFERENCE]** queries, in order: `01/15`, `01/02`, `05/28`, `05/01`, `05/04`, `05/05`, `01/14`, `05/02`, `01/07`, `01/08`, `01/20`. A host does not need to replicate this exact order; the queries above work individually.

## Determining print width [FACT]

Do not hard-code 384 or 576 dots. Query `05/01` and read `TPInfo.TPCurrentSize` (the paper width the printer is set to, in mm), then query `05/28` and pick the `TPSizeInfo` entry whose `PaperWidth` matches. Its `HotSpot` is the number of dots per line and its `OffsetStart` goes into each data frame. On the test unit:

| PaperWidth (mm) | HotSpot (dots) | OffsetStart |
|---|---|---|
| 57 | 576 | 0 |
| 79 | 864 | 0 |
| 110 | 1248 | 0 |

**Physical paper may be narrower than reported.** With the printer set to 110 mm (1248 dots) but a 4-inch (101.6 mm) roll loaded, a test pattern of boxes at different positions showed that dot 0 sits at the left edge of the paper and content beyond roughly dot 1200 falls off the right edge (the right sides of boxes were missing, a glyph was cut in half). The firmware has no way to know the real roll width, so the host should limit the printable area to the physical paper rather than trusting `HotSpot` alone. The image sent must still be `HotSpot` dots wide; just leave the unreachable columns blank.

## Print sequence [FACT]

1. (Optional, unverified) set density `05/11`.
2. Print start `05/19`.
3. Data frames `05/1B`, sequence number starting at 1.
4. Print end `05/1A`.
5. Feed `05/16` with data `00 00`.

Send all of these back to back, then read and count the acknowledgements (see [Timing rules](#timing-rules-fact)).

### Data frame layout

```
payload = 05 1B 01 | outerLen (LE16) | outer
outer   = seq (LE16, starting at 1) | innerLen (LE16) | inner
inner   = 01 | width/8 (LE16) | offsetStart (LE16) | 00 | chunkLen (LE16) | chunk
```

The whole payload is then wrapped in the normal `A5 01 ... 5A` frame. `width` is the `HotSpot` value and `offsetStart` is the `OffsetStart` value from `05/28`. The meaning of the leading `01` and the `00` byte in `inner` is not known; they are sent as constants.

### Image format

The bitmap is 1 bit per dot, most significant bit first, **black = 1**, rows padded to whole bytes, no compression. Rows are concatenated top to bottom and split into chunks. Printing uncompressed data is verified; that the C2 never uses the app's compressed path is an **[INFERENCE]** (the app appears to exclude the C2 from it).

### Chunk size rule

With `rowBytes = width / 8` and `maxLen` from query `01/14`, the chunk size is the smallest multiple of `rowBytes` that is greater than or equal to `maxLen - 2 * rowBytes`. On the C2 at 1248 dots: `rowBytes = 156`, `maxLen = 1297`, `1297 - 312 = 985`, so each chunk is `7 * 156 = 1092` bytes (7 rows). The last chunk carries whatever rows remain.

## Timing rules [FACT]

These took the longest to find and matter more than anything else in this document.

**Acknowledgements mean "received", not "printed".** The replies to data frames, print end and feed all arrive before the paper has finished moving. There is no "print finished" event or status: the status queries `05/0D` and `01/20` returned the same values before, during and after a print.

**Closing the link too early drops unprinted rows.** If the Bluetooth link is closed while the printer still has unprinted data buffered, that data is discarded. In one measurement a 28 mm job closed right after the last acknowledgement lost its first frames, closed after 1.8 s it still lost a frame or two, and closed after 3.2 s it was complete. Keep the link open until the paper should be done. The reference code waits `1.5 s + length_mm / 8` seconds from the start of the job; 8 mm/s is deliberately slower than the roughly 10 mm/s observed.

**Reconnecting within about 1 s gets reset.** A new connection made 0.3 s after a disconnect always failed; after more than 1 s it worked. The reference code keeps at least 1.5 s between connections. Note that some host Bluetooth stacks keep the link up for a moment after the owning process exits, so "disconnect" should mean "the link is actually down", not "the process has closed its socket".

**Burst-send; do not lock-step.** The vendor's app writes start, all data frames, end and feed back to back and never waits for the individual acknowledgements. Waiting for each acknowledgement before sending the next frame left gaps between frames and lost frames in testing. Send everything, then read the replies and check that the number of data acknowledgements equals the number of data frames sent.

**No flow control is needed.** The printer's buffer absorbed a whole job of 195 data frames written in about 2.5 s without problems.

## Unverified / open questions

**Device authentication.** **[INFERENCE]** After connecting, the vendor's app sends `01/17` with a random string, forwards the reply to the vendor's server, then sends `01/1F`, and disconnects if that fails. **[FACT]** None of this was done during testing and the C2 printed normally, so authentication appears to be enforced by the app rather than the firmware. A future firmware might change that.

**Paper identification.** NFC paper tags and any server-side paper type check are not covered.

**Density and feed parameters.** The reply to `05/11`, the valid density range, and non-zero feed amounts are untested.

**Other firmware, models and app variants.** Only firmware `01.00.22` on one C2 was tested. The domestic (China) and international versions of the vendor's app may treat the C2 differently; only the behaviour of one app variant was observed.

**USB.** Protocol 2 over the USB printer-class interface has not been tried.

**Unknown constants.** The `01` and `00` bytes in the data frame's inner header and the meaning of the `01/20` value are not understood.

## Dead ends

The old Paperang protocol (`0x02 ... 0x03` frames, CRC key `0x35769521` or 0, 384/576-dot widths), ESC/POS, TSPL, CPCL and ZPL all got no reply at all from a C2, over both Bluetooth and USB. The turning point was noticing that the vendor's app sends the `0xA5` probe first on connection and only falls back to the old protocol if the printer does not answer it.
