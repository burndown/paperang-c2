"""Tiny local web UI. Single-threaded on purpose: IOBluetooth needs the main thread's run loop."""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image

from . import render

WEB = os.path.join(os.path.dirname(__file__), "web")
STATE = {"addr": None, "info": None}
DEFAULT_WIDTH = 1248
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _connect():
    from .device import C2
    from .transport import open_transport
    t = open_transport(STATE["addr"])
    return t, C2(t)


def _info_dict(i) -> dict:
    return {k: getattr(i, k) for k in ("model", "serial", "firmware", "battery_percent", "dpi", "max_packet",
                                       "paper_mm", "paper_sizes_mm", "print_width")}


def _render(body: dict, width: int):
    if body.get("kind") == "image":
        raw = base64.b64decode(body["image"].split(",", 1)[-1])
        src = Image.open(io.BytesIO(raw))
        img = render.for_paper(lambda w: render.fit_image(src, w, body.get("mode", "dither"), bool(body.get("rotate"))), width)
    else:
        text = body.get("text", "")
        if not text.strip():
            raise ValueError("nothing to print")
        img = render.for_paper(lambda w: render.text_to_image(text, w, int(body.get("size", 56)), body.get("align", "left")), width)
    render.check_height(img)
    return img


def _png_data_url(img) -> str:
    buf = io.BytesIO()
    img.convert("1").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class Handler(BaseHTTPRequestHandler):
    server_version = "paperang-c2"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def _send(self, code: int, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype != "image/png" else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if self.path in ("/", "/index.html"):
            with open(os.path.join(WEB, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if self.path == "/api/info":
            try:
                t, c2 = _connect()
                try:
                    info = c2.info()
                finally:
                    t.close()
                STATE["info"] = info
                return self._send(200, _info_dict(info))
            except Exception as e:  # noqa: BLE001
                return self._send(502, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(415, {"error": "json only"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40_000_000:
            return self._send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/preview":
                width = STATE["info"].print_width if STATE["info"] else DEFAULT_WIDTH
                img = _render(body, width)
                return self._send(200, {"png": _png_data_url(img), "width": img.width, "height": img.height,
                                        "mm": round(img.height / (STATE["info"].dpi if STATE["info"] else 300) * 25.4)})
            if self.path == "/api/print":
                t, c2 = _connect()
                try:
                    info = c2.info()
                    STATE["info"] = info
                    img = _render(body, info.print_width)
                    density = body.get("density")
                    c2.print_image(img, info, density=int(density) if density not in (None, "") else None)
                finally:
                    t.close()
                return self._send(200, {"ok": True, "height": img.height})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._send(400 if isinstance(e, ValueError) else 502, {"error": str(e)})
        self._send(404, {"error": "not found"})


def serve(host: str, port: int, addr: str | None, allow_hosts=()) -> None:
    STATE["addr"] = addr
    ALLOWED_HOSTS.update(allow_hosts)
    srv = HTTPServer((host, port), Handler)
    print(f"Paperang C2 web UI: http://{host}:{port}/   (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
