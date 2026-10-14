# AirPrint (iPhone / iPad / Mac)

The `paperang-ipp` service makes the printer show up as an **IPP Everywhere** (AirPrint-compatible) printer called **Paperang C2**. It is the stock `ippeveprinter` from CUPS: it receives the document that iOS or macOS rasterised, and calls `deploy/paperang-ipp.sh`, which decodes the page, crops and scales it, and prints it over Bluetooth. Install it with [`deploy/install.sh`](../deploy/install.sh), see [DEPLOY.md](DEPLOY.md).

Tested with an iPhone (the printer was found and printed). Not tested: iPad, macOS "Add Printer", Android, Windows.

## Rules for good results (learned from real print jobs)

| Do | Why |
|---|---|
| Make the picture **portrait** (taller than wide) | iOS rotates landscape and near-square images by 90° before sending. A 1248×1242 picture came out rotated; a 1248×1809 one did not. The tool cannot undo this: the rotation is already in the page it receives. |
| Choose **A4** (or Letter) as the paper size | With 4×6 iOS used "fill page": it rotated, enlarged and **cropped** the image, and the cropped-off parts never reached the server (3½×5 is presumably the same, untested). With A4 it used "fit page" and kept everything (Letter untested). |
| Don't worry about margins | The server trims the white margins of each page and scales the content to the paper width (up to 2× enlargement), and drops the empty rest of the page, so an A4 page does not waste an A4 length of paper. |

The paper-size list in the iOS dialog is iOS's own (3½×5, 4×6, Letter, A4, A6). The printer advertises a single 110×220 mm size, which iOS does not offer.

What the server does with a page can be switched off with `PAPERANG_CROP=0` in `/etc/default/paperang-c2` (then only the empty bottom of the page is trimmed).

## What iOS sends (so you can debug)

`touch /tmp/paperang-ipp.dry` on the server, print from the phone, and read `/tmp/paperang-ipp.dry.log` and `/tmp/paperang-ipp.dry.d/`. Nothing is printed while the file exists; remove it to print again. In our tests the job was:

- document format `image/urf` (Apple raster), 8-bit gray, gzip-compressed in transit; A4 is 2480×3507 at 300 dpi;
- job attributes: `media-col` with the chosen size and 6.35 mm margins, `print-quality=high`, `print-color-mode=monochrome`; **no** `orientation-requested`, so rotation is decided by iOS;
- the job is created with Create-Job + Send-Document, and the phone polls the printer's attributes every 3 s while the print dialog is open.

`paperang_c2/raster.py` decodes URF and PWG raster (1-, 8- and 24-bit). It was checked against files made by Ghostscript's `pwgraster` and `urf` devices (the two decode to identical pages) and against real iPhone jobs.

## Quirks of `ippeveprinter` (CUPS 2.4.10) that cost time

- The binary is `/usr/sbin/ippeveprinter`, not on a normal user's `PATH`.
- Once you pass `-a printer.conf`, you cannot also use `-f`, `-m`, `-M` or `-s`: it silently prints its usage text and exits. Put those settings (model, speed, formats) in the conf instead.
- Do not declare `document-format-supported` in the conf: the server adds its own (`application/octet-stream`, `image/pwg-raster`, `image/urf`) and the attribute then appears twice, which fails strict checking. The defaults are exactly what iOS and macOS send.
- Check the printer without a phone, from any machine with CUPS tools: `ipptool -tv ipp://<server>:8631/ipp/print get-printer-attributes.test`, and send a test job with `ipptool -t -f page.urf -d filetype=image/urf ipp://<server>:8631/ipp/print print-job.test` (the `.test` files ship with CUPS, in `/usr/share/cups/ipptool/` on Linux and macOS).
- mDNS: the printer is announced as service `Paperang C2` of type `_ipp._tcp` with the subtypes `_print` and `_universal`. The iPhone found it this way; whether the `_universal` subtype is required was not tested. Check with `dns-sd -B _ipp._tcp` (macOS) or `avahi-browse -rt _ipp._tcp` (Linux).
