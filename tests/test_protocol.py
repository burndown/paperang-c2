import unittest

from PIL import Image

from paperang_c2 import protocol as p
from paperang_c2.device import parse_tlv
from paperang_c2 import render


class ProtocolTests(unittest.TestCase):
    def test_probe_frame_matches_hardware_capture(self):
        self.assertEqual(p.q_protocol_version().hex(), "a5010500011501000041d235195a")

    def test_parse_real_replies(self):
        # replies captured from a C2 (fw 01.00.22) on 2026-10-14
        fw = bytes.fromhex("a50110000115020b0001080030312e30302e3232873507995a")
        frames, rest = p.parse_frames(fw)
        self.assertEqual(rest, b"")
        self.assertTrue(frames[0]["crc_ok"])
        self.assertEqual(frames[0]["value"], b"01.00.22")
        # a serial-number reply, built here with a made-up serial (the CRC is computed, so it is valid)
        value = b"C200H0XXXXXXXX"
        payload = bytes((0x01, 0x02, 0x02)) + (3 + len(value)).to_bytes(2, "little") + b"\x01" + len(value).to_bytes(2, "little") + value
        frames, _ = p.parse_frames(p.frame(payload))
        self.assertTrue(frames[0]["crc_ok"])
        self.assertEqual(frames[0]["value"], value)

    def test_parse_split_reply(self):
        a = bytes.fromhex("a5010a0005040205000102002c019a1df4215a")
        frames, rest = p.parse_frames(a[:7])
        self.assertEqual((frames, rest), ([], a[:7]))
        frames, rest = p.parse_frames(rest + a[7:])
        self.assertEqual(int.from_bytes(frames[0]["value"], "little"), 300)

    def test_tlv(self):
        self.assertEqual(parse_tlv(bytes.fromhex("010100010202004332"))[2], b"C2")

    def test_print_job_shape(self):
        img = Image.new("1", (1248, 100), 1)
        job = p.build_print_job(img, print_width=1248, offset_start=0, max_len=1297, feed_after=False)
        self.assertEqual(job[0][4:7], b"\x05\x19\x01")          # start
        self.assertEqual(job[-1][4:7], b"\x05\x1a\x01")         # end
        self.assertTrue(all(f[4:7] == b"\x05\x1b\x01" for f in job[1:-1]))
        self.assertEqual(len(job[1:-1]), 15)                    # 100 rows * 156 B = 15600 B in 1092 B chunks


class RenderTests(unittest.TestCase):
    def test_text_width(self):
        self.assertEqual(render.text_to_image("你好\nabc", 1248).width, 1248)

    def test_text_is_actually_big(self):
        # regression: with no usable font the text used to shrink to a ~8 px bitmap font
        im = render.text_to_image("你好 C2", 1248, 56)
        x0, y0, x1, y1 = im.point(lambda v: 255 - v).getbbox()
        self.assertGreater(y1 - y0, 35)

    def test_no_font_is_an_error(self):
        old = render._FONT_CANDIDATES
        render._FONT_CANDIDATES = []
        try:
            with self.assertRaises(RuntimeError):
                render.load_font(56)
        finally:
            render._FONT_CANDIDATES = old

    def test_fit_image_scales_to_width(self):
        im = render.fit_image(Image.new("RGB", (500, 250), (120, 120, 120)), 1248)
        self.assertEqual(im.size, (1248, 624))
        self.assertEqual(im.mode, "1")

    def test_printable_area_for_the_4_inch_roll(self):
        # measured: dots beyond ~1200 fall off a 4-inch roll even though the head has 1248
        self.assertEqual(render.printable_area(1248, 300), (12, 1188))

    def test_printable_area_follows_the_paper_width(self):
        old = render.PAPER_WIDTH_MM
        render.PAPER_WIDTH_MM = 110.0
        try:
            self.assertEqual(render.printable_area(1248, 300), (12, 1236))   # capped by the head
        finally:
            render.PAPER_WIDTH_MM = old

    def test_for_paper_keeps_all_ink_on_the_paper(self):
        src = Image.new("L", (400, 200), 255)
        from PIL import ImageDraw
        ImageDraw.Draw(src).rectangle((0, 0, 399, 199), outline=0, width=6)   # a frame touching every edge
        out = render.for_paper(lambda w: render.fit_image(src, w, "threshold"), 1248)
        self.assertEqual(out.width, 1248)
        ink = out.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
        self.assertGreaterEqual(ink[0], 12)
        self.assertLessEqual(ink[2], 1188)
        self.assertGreater(ink[2] - ink[0], 1150)                           # and it still fills the usable width

    def test_place_keeps_mode(self):
        self.assertEqual(render.place(Image.new("1", (10, 3), 0), 40, 5).mode, "1")
        self.assertEqual(render.place(Image.new("L", (10, 3), 0), 40, 5).getpixel((0, 0)), 255)

    def test_height_guard(self):
        with self.assertRaises(ValueError):
            render.check_height(Image.new("1", (8, 7000)))


if __name__ == "__main__":
    unittest.main()
