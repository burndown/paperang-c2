import json
import socket
import threading
import unittest
import urllib.request

from paperang_c2 import server


def _ipv6_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::1", 0))
        s.close()
        return True
    except OSError:
        return False


class ServerTests(unittest.TestCase):
    def _serve(self, host):
        srv = server.make_server(host, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def _get(self, url, host_header=None):
        req = urllib.request.Request(url, headers={"Host": host_header} if host_header else {})
        return urllib.request.urlopen(req, timeout=5)

    def test_index_over_ipv4(self):
        port = self._serve("0.0.0.0")
        self.assertEqual(self._get(f"http://127.0.0.1:{port}/").status, 200)

    @unittest.skipUnless(_ipv6_available(), "no IPv6 loopback here")
    def test_wildcard_also_listens_on_ipv6(self):
        port = self._serve("0.0.0.0")
        self.assertEqual(self._get(f"http://[::1]:{port}/").status, 200)

    def test_foreign_host_header_is_refused(self):
        port = self._serve("0.0.0.0")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get(f"http://127.0.0.1:{port}/", host_header="evil.example")
        self.assertEqual(cm.exception.code, 403)

    def test_preview_needs_no_printer(self):
        port = self._serve("0.0.0.0")
        body = json.dumps({"kind": "text", "text": "hi", "size": 56}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/preview", data=body,
                                     headers={"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=5).read())
        self.assertEqual(data["width"], 1248)

    def test_json_only(self):
        port = self._serve("0.0.0.0")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/print", data=b"x=1",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 415)


if __name__ == "__main__":
    unittest.main()
