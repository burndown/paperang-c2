# paperang-c2

[中文](README.zh-CN.md) · [Protocol reference](docs/PROTOCOL.md) · [LAN print server / AirPrint](docs/DEPLOY.md)

Print to a **Paperang C2** (作业帮喵喵机 C2, a 4-inch Bluetooth thermal printer) without the phone app, from a Mac or a Linux machine: a command line, a small web UI, and a one-command **LAN print server** so every phone and computer in the house can print to it, including from the iPhone/iPad **Print** dialog (AirPrint).

> **Unofficial.** Independent interoperability research on the author's own device. Not affiliated with, endorsed by, or supported by the printer's vendor; product names belong to their owners. No vendor code is included. Personal project, no warranty.

## Status: what is tested

Everything below was verified on **one C2 unit, firmware `01.00.22`**, with a **4-inch (101.6 mm) roll** while the printer reported 110 mm:

| Works (tested) | Not tested |
|---|---|
| Printing from macOS (Python 3.9, Apple silicon) and from Debian 13 (Python 3.13, Intel AX210 Bluetooth) | Windows, Raspberry Pi (should work, it is just BlueZ), other Linux distributions |
| CLI, web UI (desktop browser), Bluetooth address scan | Web UI on a phone (layout checked in a desktop browser only) |
| LAN print server on Debian 13 with systemd | Android / Windows printing to the AirPrint printer |
| AirPrint from an iPhone (found, printed) | macOS "Add Printer" with the AirPrint printer |
| 110 mm paper setting with a 4-inch roll | 57 mm and 79 mm paper, any other Paperang model or firmware |
| | USB (the C2 has a USB port but nothing has been verified over it), the density setting |

If you try it on something else, please open an issue with what you saw. See [docs/HARDWARE-TESTING.md](docs/HARDWARE-TESTING.md) for calibration pages you can print to check your own unit.

## Why this exists

The C2 does **not** speak the protocol of the older Paperang printers that existing open-source tools implement. It uses a newer frame format (`A5 … 5A`) and is silent to everything else, so those tools print nothing. [docs/PROTOCOL.md](docs/PROTOCOL.md) documents the protocol, the print sequence, and the timing rules that decide whether the paper comes out complete (closing the link too early silently drops rows).

## Quick start: print from your own computer

Needs Python 3.9+ and Bluetooth.

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
pip install .            # needs a recent pip: python3 -m pip install --upgrade pip   (an old pip 21.2 silently skips the command)
                         # or: pip install -r requirements.txt  and use  python3 -m paperang_c2
```

1. Switch the printer on and **close the vendor's app / Bluetooth on any phone or tablet**: the printer talks to one device at a time.
2. **macOS:** pair it once in System Settings → Bluetooth (macOS will say it is a printer; ignore that). **Linux:** nothing to pair or trust; `paperang-c2 scan` finds the address.
3. Run from a **terminal app** (on macOS the process needs Bluetooth permission, which only a terminal can ask for):

```bash
paperang-c2 scan                                  # shows the Bluetooth address
paperang-c2 info                                  # model, firmware, battery, paper width (macOS picks the paired printer)
paperang-c2 --addr AA:BB:CC:DD:EE:FF info         # or give the address (or set PAPERANG_ADDR)
paperang-c2 text "Hello, C2"                      # text, Chinese works; --size 56 --align center
paperang-c2 image photo.jpg                       # images; --mode threshold for text and line art
paperang-c2 test                                  # a small test page
paperang-c2 serve                                 # web UI on http://127.0.0.1:8765/
```

`--preview out.png` renders to a PNG without touching Bluetooth or paper. Printing waits ten to twenty seconds before disconnecting on purpose, see the timing rules.

From Python:

```python
from paperang_c2 import render
from paperang_c2.device import C2
from paperang_c2.transport import open_transport

t = open_transport("AA:BB:CC:DD:EE:FF")          # None on macOS = first paired Paperang
try:
    c2 = C2(t)
    info = c2.info()                              # width, dpi, battery, ...
    img = render.for_paper(lambda w: render.text_to_image("Hello from Python", w), info.print_width, info.dpi)
    c2.print_image(img, info)                     # blocks until the paper should be done
finally:
    t.close()
```

## Quick start: a print server for the whole house

A Linux machine with Bluetooth near the printer (a mini PC, a Raspberry Pi, an old laptop) can share it on your LAN: a web page for any browser, a small HTTP API, and an **AirPrint** printer that shows up in the iPhone/iPad/Mac print dialog. Debian, Ubuntu and Raspberry Pi OS are supported by the installer.

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
sudo ./deploy/install.sh            # scans for the printer, installs packages and two systemd services
```

Then open `http://<that-machine>:8765/`, or on an iPhone pick **Paperang C2** in Share → Print. Details, options, updating, removing and a manual install for other systems: [docs/DEPLOY.md](docs/DEPLOY.md). ESP32 boards cannot be the bridge unless they have classic Bluetooth (the original ESP32 does; S3, C3 and C6 are BLE only).

**The server has no authentication. Use it on a network you trust.**

## Printing from an iPhone or iPad

Details in [docs/AIRPRINT.md](docs/AIRPRINT.md). The short version, learned the hard way:

- Make the picture **portrait** (taller than wide). iOS rotates landscape and near-square images by 90°.
- Choose **A4** (or Letter) as the paper size. With 4×6, iOS cropped the image to fill the page before it reached the server (A4 tested, Letter not).
- The server trims the page's white margins and scales the content to the paper width, so the page size you picked does not waste paper.

## Things that will bite you

- **One host at a time.** The printer accepts a single Bluetooth connection. A phone app that is open in the background blocks everything else. Two hosts that both use it need a couple of seconds between jobs.
- **Paper width.** The firmware reports the *setting* (110 mm = 1248 dots), not the roll. A 4-inch roll only exposes about the first 1200 dots; anything past that is printed off the paper. The tools keep content inside 12–1188 dots by default; set `PAPERANG_PAPER_WIDTH_MM` if your roll is wider. [How to measure yours.](docs/HARDWARE-TESTING.md)
- **Timing.** The printer acknowledges data when it *receives* it, not when it has printed it. Closing the Bluetooth link before the paper is done makes it throw away unprinted rows, and reconnecting within a second of a disconnect gets the connection reset. The code handles both; if you write your own client read [the timing rules](docs/PROTOCOL.md#timing-rules-fact).
- **macOS permission.** On macOS the process needs Bluetooth permission, so run it from a terminal app, not from a background job (a background process is killed by the system without a message).

## Project layout

```
paperang_c2/protocol.py    frames and commands (pure functions that return bytes)
paperang_c2/device.py      queries and the print flow (burst send, ack check, linger)
paperang_c2/bt_macos.py    RFCOMM over IOBluetooth (PyObjC)
paperang_c2/bt_linux.py    RFCOMM over a plain BlueZ socket
paperang_c2/transport.py   picks the transport, serialises jobs with a lock, reconnect gap, scan
paperang_c2/render.py      text / image -> 1-bit bitmap, printable area
paperang_c2/raster.py      decoder for AirPrint's URF and PWG raster
paperang_c2/ipp.py         turns an AirPrint job into print jobs (crop margins, scale to paper)
paperang_c2/server.py      web UI + HTTP API       paperang_c2/web/index.html
deploy/                    install.sh, systemd unit templates, IPP printer config
tools/testpages.py         calibration pages
docs/                      protocol reference, deployment, AirPrint, hardware testing
tests/                     unit tests (python3 -m unittest discover -s tests)
```

## Roadmap

Open items, roughly in order of usefulness: auto-rotate landscape screenshots for AirPrint; shorten the (deliberately conservative) wait after a job; find a real "print finished" signal; check whether protocol 2 also works over USB; verify the density command and the 57 / 79 mm paper settings; test on other Paperang models.

## License

MIT, see [LICENSE](LICENSE).
