import unittest

from PIL import Image

from paperang_c2 import protocol as p
from paperang_c2.device import C2, PrinterError, PrinterInfo


def reply(group, cmd, status=1, value=b""):
    payload = bytes((group, cmd, 2)) + (3 + len(value)).to_bytes(2, "little") + bytes((status,)) + len(value).to_bytes(2, "little") + value
    return p.frame(payload)


class FakePrinter:
    """Acks every frame. Records the order of writes and polls."""
    def __init__(self, ack_data=True, bad_status=None):
        self.ack_data, self.bad_status = ack_data, bad_status
        self.out, self.events, self.log = b"", [], []

    def write(self, data):
        group, cmd = data[4], data[5]
        self.events.append("D" if (group, cmd) == (0x05, 0x1B) else "c")
        self.log.append((group, cmd))
        if (group, cmd) == (0x05, 0x1B) and not self.ack_data:
            return
        status = self.bad_status if (group, cmd) == (0x05, 0x1B) and self.bad_status else 1
        self.out += reply(group, cmd, status)

    def poll(self, timeout=0.0):
        self.events.append("p")
        data, self.out = self.out, b""
        return data


class PrintFlowTests(unittest.TestCase):
    INFO = PrinterInfo(print_width=1248, max_packet=1297, dpi=300)

    def setUp(self):
        self._saved = (C2.LINGER_BASE, C2.PRINT_SPEED_MM_S)
        C2.LINGER_BASE, C2.PRINT_SPEED_MM_S = 0.0, 1e9      # no real waiting in these tests

    def tearDown(self):
        C2.LINGER_BASE, C2.PRINT_SPEED_MM_S = self._saved

    def test_frames_are_sent_back_to_back(self):
        # the C2 drops frames if we leave gaps between them (measured), so nothing may be read or awaited mid-burst
        fake = FakePrinter()
        C2(fake).print_image(Image.new("1", (1248, 300), 1), self.INFO)
        w = "".join(fake.events)
        first, last = w.index("c"), w.rindex("D")
        self.assertNotIn("p", w[first:w.rindex("c") + 1])
        self.assertEqual(fake.log[0], (0x05, 0x19))                    # start first
        self.assertEqual(fake.log[-2:], [(0x05, 0x1A), (0x05, 0x16)])  # end, then feed
        self.assertEqual(sum(1 for e in fake.events if e == "D"), 43)  # ceil(300 rows / 7 rows per 1092 B chunk)

    def test_missing_data_acks_raise(self):
        import paperang_c2.device as d
        fake = FakePrinter(ack_data=False)
        orig, t = d.time.time, [0.0]
        d.time.time = lambda: (t.__setitem__(0, t[0] + 5) or t[0])      # fast-forward the timeout
        try:
            with self.assertRaises(PrinterError):
                C2(fake).print_image(Image.new("1", (1248, 300), 1), self.INFO)
        finally:
            d.time.time = orig

    def test_rejected_data_frame_raises(self):
        with self.assertRaises(PrinterError):
            C2(FakePrinter(bad_status=3)).print_image(Image.new("1", (1248, 100), 1), self.INFO)


class LingerTests(unittest.TestCase):
    """The link must stay open until the paper is done: closing early makes the printer drop unprinted rows."""
    INFO = PrinterInfo(print_width=1248, max_packet=1297, dpi=300)

    def _run(self, heights, linger_last=True):
        import paperang_c2.device as d
        clock = [1000.0]
        orig = d.time.time
        d.time.time = lambda: clock[0]
        fake = FakePrinter()
        real_poll = fake.poll
        fake.poll = lambda timeout=0.0: (clock.__setitem__(0, clock[0] + max(timeout, 0.01)) or real_poll(timeout))
        try:
            c = C2(fake)
            for i, h in enumerate(heights):
                last = i == len(heights) - 1
                c.print_image(Image.new("1", (1248, h), 1), self.INFO, linger=(linger_last if last else False))
            if not linger_last:
                c.finish_printing()
            return clock[0] - 1000.0
        finally:
            d.time.time = orig

    def test_waits_for_the_paper(self):
        mm = 300 / 300 * 25.4                                   # 300 rows at 300 dpi = 25.4 mm
        elapsed = self._run([300])
        self.assertGreaterEqual(elapsed, C2.LINGER_BASE + mm / C2.PRINT_SPEED_MM_S - 1e-6)

    def test_longer_jobs_wait_longer(self):
        self.assertGreater(self._run([1200]), self._run([300]) + 5)

    def test_multi_page_waits_once_for_the_total(self):
        pages = self._run([300, 300, 300])
        single = self._run([900])
        self.assertAlmostEqual(pages, single, delta=0.6)        # not three separate lingers


if __name__ == "__main__":
    unittest.main()
