"""Serve the compiled UI and automation API together on localhost."""
import mimetypes
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .config import Settings, WORKSPACE
from .history_api import make_handler
from .ui_runs import RunManager

DIST = WORKSPACE / 'eurothermReviewerAutomationUI' / 'dist'


def make_web_handler(settings, manager, folder=DIST):
    base = make_handler(settings, manager)

    class WebHandler(base):
        def serve_get(self):
            route = urlparse(self.path).path
            if route.startswith('/api/'):
                return super().serve_get()
            requested = unquote(route).lstrip('/') or 'index.html'
            path = (folder / requested).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():
                self.send_error(404, 'Page not found')
                return
            try:
                payload = path.read_bytes()
            except OSError:
                self.send_error(503, 'Page unavailable')
                return
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(payload)
    return WebHandler


def main():
    if not (DIST / 'index.html').is_file():
        raise RuntimeError('Build the UI first: run npm run build in eurothermReviewerAutomationUI')
    settings = Settings.load()
    server = ThreadingHTTPServer(('127.0.0.1', 8765), make_web_handler(settings, RunManager(settings)))
    print('Eurotherm workspace: http://127.0.0.1:8765', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
