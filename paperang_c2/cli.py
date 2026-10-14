"""Command line: python -m paperang_c2 {scan,info,text,image,test,serve}"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image

from . import render


def _connect(args):
    from .device import C2
    from .transport import open_transport
    print("connecting ...", file=sys.stderr)
    t = open_transport(args.addr or os.environ.get("PAPERANG_ADDR"))
    return t, C2(t)


def _fmt_info(i) -> str:
    return (f"model {i.model}  serial {i.serial}  firmware {i.firmware}\n"
            f"battery {i.battery_percent:.0f}%  dpi {i.dpi}  max packet {i.max_packet}\n"
            f"paper {i.paper_mm} mm (supported {i.paper_sizes_mm})  print width {i.print_width} dots")


def _do_print(args, build) -> int:
    """build(info) -> PIL image. With --preview, no Bluetooth is used."""
    if args.preview:
        img = build(None)
        img.save(args.preview)
        print(f"preview written to {args.preview} ({img.width}x{img.height})")
        return 0
    t, c2 = _connect(args)
    try:
        info = c2.info()
        print(_fmt_info(info), file=sys.stderr)
        img = build(info)
        render.check_height(img, args.max_height)
        print(f"printing {img.width}x{img.height} dots ({img.height / info.dpi * 25.4:.0f} mm) ...", file=sys.stderr)
        c2.print_image(img, info, density=args.density,
                       progress=lambda a, b: print(f"\r  {a}/{b}", end="", file=sys.stderr))
        print("\ndone", file=sys.stderr)
    finally:
        t.close()
    return 0


def main(argv=None) -> int:
    try:
        return _main(argv)
    except (RuntimeError, ValueError, OSError) as e:      # printer unreachable, bad file, too tall ...
        print(f"error: {e}", file=sys.stderr)
        return 1


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="paperang_c2", description=__doc__)
    ap.add_argument("--addr", help="Bluetooth address (default: first paired Paperang*, or $PAPERANG_ADDR)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--density", type=int, help="print density (device default if omitted)")
        sp.add_argument("--preview", metavar="PNG", help="render to a PNG instead of printing (no Bluetooth)")
        sp.add_argument("--max-height", type=int, default=render.MAX_HEIGHT_DOTS)
        sp.add_argument("--width", type=int, default=1248, help="width for --preview (printing uses the printer's)")

    sub.add_parser("info", help="query the printer")
    sp = sub.add_parser("scan", help="find printers (paired ones on macOS, nearby ones on Linux)")
    sp.add_argument("--seconds", type=int, default=12, help="Linux: how long to listen")
    sp = sub.add_parser("text", help="print text")
    sp.add_argument("text", nargs="?", help="text; omit to read stdin")
    sp.add_argument("--size", type=int, default=56)
    sp.add_argument("--align", choices=["left", "center", "right"], default="left")
    sp.add_argument("--font")
    common(sp)
    sp = sub.add_parser("image", help="print an image file")
    sp.add_argument("file")
    sp.add_argument("--mode", choices=["dither", "threshold", "none"], default="dither")
    sp.add_argument("--rotate", action="store_true", help="rotate landscape images 90 degrees")
    sp.add_argument("--raw", action="store_true",
                    help="send the image exactly as it is, scaled only to the print width and NOT kept inside the "
                         "printable paper area (for calibration pages, see docs/HARDWARE-TESTING.md)")
    common(sp)
    sp = sub.add_parser("test", help="print a small test card")
    common(sp)
    sp = sub.add_parser("ipp-job", help="print one document received over IPP (used by deploy/paperang-ipp.sh)")
    sp.add_argument("file")
    sp.add_argument("--content-type", default=os.environ.get("CONTENT_TYPE", ""))
    sp.add_argument("--mode", choices=["dither", "threshold"])
    sp = sub.add_parser("serve", help="start the web UI")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="extra Host header to accept when serving on the LAN (repeatable); "
                         "there is no login, so only do this on a network you trust")

    args = ap.parse_args(argv)
    if args.cmd == "serve":
        from .server import serve
        serve(args.host, args.port, args.addr or os.environ.get("PAPERANG_ADDR"), args.allow_host)
        return 0
    if args.cmd == "ipp-job":
        from .ipp import run_job
        return run_job(args.file, args.content_type, args.addr or os.environ.get("PAPERANG_ADDR"), args.mode)
    if args.cmd == "scan":
        from .transport import scan
        found = scan(seconds=args.seconds)
        for addr, name in found:
            print(f"{addr}  {name}")
        if not found:
            print("no Paperang printer found: switch it on, keep it close, and close the phone app", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "info":
        t, c2 = _connect(args)
        try:
            print(_fmt_info(c2.info()))
        finally:
            t.close()
        return 0
    wid = lambda info: info.print_width if info else args.width
    if args.cmd == "text":
        txt = args.text if args.text is not None else sys.stdin.read()
        return _do_print(args, lambda i: render.for_paper(
            lambda w: render.text_to_image(txt, w, args.size, args.align, font_path=args.font), wid(i)))
    if args.cmd == "image":
        src = Image.open(args.file)
        if args.raw:
            return _do_print(args, lambda i: render.fit_image(src, wid(i), args.mode, args.rotate))
        return _do_print(args, lambda i: render.for_paper(
            lambda w: render.fit_image(src, w, args.mode, args.rotate), wid(i)))
    if args.cmd == "test":
        return _do_print(args, lambda i: render.for_paper(
            lambda w: render.text_to_image("Paperang C2\n喵喵机 测试页\n0123456789 ABCxyz", w, 64, "center"), wid(i)))
    return 1
