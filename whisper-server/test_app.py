import io
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

import app


class FakeModel:
    def transcribe(self, path, language=None, vad_filter=True):
        return iter([SimpleNamespace(start=0.0, end=1.234, text=" hello "), SimpleNamespace(start=1.3, end=2.0, text="world")]), SimpleNamespace(language="en", duration=2.0)


def multipart(fields, file_bytes):
    boundary = "XyZ"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.ogg"\r\nContent-Type: audio/ogg\r\n\r\n'.encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app._model = FakeModel()
        app.ALLOW_NO_KEY = True
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def post(self, body, ctype, headers=None):
        req = urllib.request.Request(self.url + "/v1/audio/transcriptions", data=body, headers={"Content-Type": ctype, **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_binary_audio_survives_parsing(self):
        import tempfile

        audio = bytes(range(256)) * 4 + b"\r\n--XyQ-not-a-boundary\r\n"
        body, ctype = multipart({"language": "ar"}, audio)
        with tempfile.TemporaryFile() as bf, tempfile.TemporaryFile() as out:
            bf.write(body)
            bf.flush()
            fields, name = app.parse_multipart_file(ctype, bf, out)
            out.seek(0)
            self.assertEqual((fields["language"], name, out.read()), ("ar", "a.ogg", audio))

    def test_verbose_json(self):
        body, ctype = multipart({"model": "x", "response_format": "verbose_json"}, b"OggS")
        status, data = self.post(body, ctype)
        self.assertEqual(status, 200)
        self.assertEqual((data["text"], data["language"], data["segments"][0]["end"]), ("hello world", "en", 1.23))

    def test_rejects_bad_requests(self):
        self.assertEqual(self.post(b"{}", "application/json")[0], 400)
        body, ctype = multipart({}, b"")
        self.assertEqual(self.post(body, ctype)[0], 400)
        with mock.patch.object(app, "ALLOW_NO_KEY", False):
            body, ctype = multipart({}, b"OggS")
            self.assertEqual(self.post(body, ctype)[0], 503, "no key configured: refuse")
        with mock.patch.object(app, "API_KEY", "secret"):
            body, ctype = multipart({}, b"OggS")
            self.assertEqual(self.post(body, ctype)[0], 401)
            self.assertEqual(self.post(body, ctype, {"Authorization": "Bearer secret"})[0], 200)


if __name__ == "__main__":
    unittest.main()
