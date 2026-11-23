import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError

from reviewer.web import make_web_handler


class WebTests(TestCase):
    def test_compiled_ui_is_served_and_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dist = root / 'dist'
            dist.mkdir()
            (dist / 'index.html').write_text('<html>Workspace</html>')
            (root / 'secret.txt').write_text('private')
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_web_handler(None, None, dist))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                with urlopen(base + '/') as response:
                    self.assertIn(b'Workspace', response.read())
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/%2e%2e/secret.txt')
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
