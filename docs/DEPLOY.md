# LAN print server (web UI, HTTP API, AirPrint)

[中文](DEPLOY.zh-CN.md)

The printer only speaks classic Bluetooth. To let everything on your network print to it, put a small Linux machine with a Bluetooth adapter near the printer and run two services on it:

| Service | What it gives you | Default port |
|---|---|---|
| `paperang-c2` | a web page, a small HTTP API | 8765 |
| `paperang-ipp` | an AirPrint / IPP Everywhere printer named **Paperang C2** (advertised over mDNS) | 8631 |

Tested on Debian 13 with an Intel AX210 Bluetooth adapter. Debian, Ubuntu and Raspberry Pi OS should work (the Raspberry Pi has not been tested). The machine must be within about 10 m of the printer, ideally without walls in between.

**There is no authentication.** Anyone on the network can print (and waste paper). Use it on a network you trust, or put it behind an authenticating reverse proxy.

ESP32 boards cannot do this job unless they support classic Bluetooth: the original ESP32 does, the S3, C3 and C6 do not (BLE only).

## One-command install (Debian / Ubuntu / Raspberry Pi OS)

```bash
git clone https://github.com/burndown/paperang-c2.git
cd paperang-c2
sudo ./deploy/install.sh
```

Before you run it: switch the printer on, put it next to the machine, and make sure no phone is connected to it. The script then:

1. installs `bluez`, `python3-pil`, `poppler-utils`, `fonts-noto-cjk` and (for AirPrint) `cups-ipp-utils` and `avahi-daemon`;
2. scans for the printer (about 15 s) to learn its Bluetooth address (no pairing or trust is needed; use `--addr` to skip the scan);
3. writes `/etc/default/paperang-c2` (printer address, paper width);
4. installs and starts the two systemd services, running as your normal user, from the cloned directory;
5. connects once to check that the printer answers, and prints the URLs.

The services run **from the directory you cloned into**, so do not delete or move it.

Options:

```
--addr AA:BB:CC:DD:EE:FF   skip the scan (use this if several printers are around, or the scan finds nothing)
--paper-mm 101.6           width of the roll you actually use (see below)
--port 8765                web UI port           --ipp-port 8631   AirPrint port
--user NAME                user the services run as (default: the user who ran sudo)
--allow-host NAME          extra host name the web UI accepts (repeatable), e.g. a reverse-proxy name
--no-web / --no-airprint   install only one of the two services
--dry-run                  show everything it would do and change nothing
--uninstall                remove the services (installed packages and /etc/default/paperang-c2 stay)
```

### Paper width

The firmware reports the paper-width *setting* (110 mm, 1248 dots). If your roll is narrower (a "4 inch" roll is 101.6 mm), the dots past the paper edge are printed into thin air, which cuts off the right side of frames and the last characters of each line. `--paper-mm` (stored as `PAPERANG_PAPER_WIDTH_MM`) tells the tools the real width; they keep content inside it with a 1 mm margin. To measure your roll, print the pages from [HARDWARE-TESTING.md](HARDWARE-TESTING.md).

## Using it

**Web UI:** `http://<machine>:8765/` (or `http://<hostname>.local:8765/`). Type text or pick/drop/paste an image, check the 1:1 preview, press Print. The page follows your browser language (English / Chinese).

**HTTP API** (JSON, `Content-Type: application/json`):

```bash
# text
curl -X POST http://<machine>:8765/api/print -H 'Content-Type: application/json' \
     -d '{"kind":"text","text":"Hello","size":56,"align":"center"}'

# image (base64 data URL), "mode": "threshold" for text and line art, "dither" for photos
curl -X POST http://<machine>:8765/api/print -H 'Content-Type: application/json' \
     -d "{\"kind\":\"image\",\"image\":\"data:image/png;base64,$(base64 < label.png | tr -d '\n')\",\"mode\":\"threshold\"}"

curl http://<machine>:8765/api/info           # connects and returns model, battery, paper width
curl -X POST http://<machine>:8765/api/preview -H 'Content-Type: application/json' -d '{"kind":"text","text":"x"}'
```

A request returns when the paper should be finished, usually ten to twenty seconds. Requests are served one at a time. The web server only accepts requests whose `Host` header is `localhost`, the machine's host name, `<hostname>.local` or its main IP (see `--allow-host`), and only `application/json` bodies; this stops a web page in a browser from silently printing, it is not authentication.

**AirPrint:** pick **Paperang C2** in the print dialog of an iPhone, iPad or Mac. Read [AIRPRINT.md](AIRPRINT.md) first: images must be portrait and the paper size should be A4.

## Behind a reverse proxy / on a sub-domain

The web UI only accepts requests whose `Host` header it knows (see above), so a proxy that passes the original
host name through needs that name allowed. Example for nginx, serving it as `printer.example.lan`:

```bash
sudo ./deploy/install.sh --addr AA:BB:CC:DD:EE:FF --allow-host printer.example.lan     # re-run is safe
```

```nginx
server {
    listen 80;
    server_name printer.example.lan;
    client_max_body_size 50m;                      # image uploads are sent as base64 JSON
    location / {
        proxy_pass http://127.0.0.1:8765;          # use an IP:port, not a host name
        proxy_http_version 1.1;
        proxy_set_header Host $host;               # must be a name passed to --allow-host
        proxy_read_timeout 300s;                   # a print request takes ten to twenty seconds
    }
}
```

The AirPrint printer is not proxied: phones find it over mDNS on its own port.

## Operating it

```bash
systemctl status paperang-c2 paperang-ipp
journalctl -u paperang-c2 -u paperang-ipp -f          # live logs
sudo systemctl restart paperang-c2 paperang-ipp
cat /etc/default/paperang-c2                          # printer address, paper width, AirPrint cropping
```

**Update:** `git pull && sudo systemctl restart paperang-c2 paperang-ipp` (run `sudo ./deploy/install.sh` again if `deploy/` changed).

**Debug AirPrint without wasting paper:** `touch /tmp/paperang-ipp.dry`. While that file exists, jobs from phones are not printed; their attributes go to `/tmp/paperang-ipp.dry.log` and the document to `/tmp/paperang-ipp.dry.d/`. Delete the file to print again. Documents are not kept otherwise.

## Manual install (other distributions)

You need: Python 3.9+, Pillow, BlueZ (`bluetoothctl`), `fonts-noto-cjk` or another CJK font, `pdftoppm` (poppler) for PDF input, and for AirPrint `ippeveprinter` (CUPS 2.4, package `cups-ipp-utils` on Debian) and avahi.

```bash
bluetoothctl scan on                       # find the address, then Ctrl-C (no pairing or trust is needed)
PAPERANG_ADDR=AA:BB:CC:DD:EE:FF python3 -m paperang_c2 info          # must print the model
PAPERANG_ADDR=AA:BB:CC:DD:EE:FF python3 -m paperang_c2 serve --host 0.0.0.0 --port 8765 --allow-host myserver.local
```

Then adapt the templates in `deploy/*.service.in` (replace `@USER@`, `@DIR@`, `@PYTHON@`, `@PORT@`, `@IPP_PORT@`, `@IPPEVE@`, `@ALLOW_HOST_ARGS@`) and `deploy/paperang-c2.env.example` (to `/etc/default/paperang-c2`).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `could not open RFCOMM … timed out` / `Host is down` | Printer off or asleep (it powers itself off after about 30 minutes; press the button), out of range, or still connected to a phone or another computer. Close the phone app, wait a few seconds, try again. |
| `Connection reset by peer` right after a previous job | A reconnect within about a second of a disconnect. The tools wait 1.5 s themselves; this happens if two different machines use the printer back to back. Wait a few seconds. |
| First rows of the print are missing | The link was closed before the paper finished. Do not shorten the wait in `device.py` unless you measured it; see the timing rules in PROTOCOL.md. |
| Right edge of frames / last character of lines missing | The roll is narrower than the printer's setting. Set `--paper-mm` / `PAPERANG_PAPER_WIDTH_MM`. |
| Text is tiny or Chinese is missing | No CJK font on the machine (`fonts-noto-cjk`). The tools fail with an error instead of printing a tiny bitmap font. |
| iPhone does not list "Paperang C2" | Phone and server must be on the same subnet and the router must not block mDNS (client isolation). Check `systemctl status avahi-daemon paperang-ipp`. |
| iPhone prints rotated or cropped | See AIRPRINT.md: portrait image, paper A4. |
| Web UI says `bad host` (HTTP 403) | You opened it with a name or address that is not allowed. Add it with `--allow-host` (re-run the installer with `--allow-host NAME`). |
| Nothing happens when printing from a phone, no error | `ls /tmp/paperang-ipp.dry` — the debug switch is on. Delete the file. |
