"""
Serve the Flutter web build and proxy its API calls to the live site.

WHY A PROXY RATHER THAN POINTING THE APP STRAIGHT AT PRODUCTION

A Flutter web app served from 127.0.0.1 calling https://mudassirllc.com is a
cross-origin request, and the site's CORS allowlist is empty by default (see
api/middleware.py) - so the browser discards every response and the app shows
nothing. The usual workarounds are both bad: adding localhost to the production
allowlist widens what the live site accepts, and launching Chrome with
--disable-web-security turns the protection off for every site you then visit.

Serving the app and the API from ONE origin removes the problem instead of
suppressing it. The browser sees only 127.0.0.1; this process talks to
production server-to-server, where CORS does not apply.

Only for local development. Nothing here is meant to be deployed.

    python tool/dev_server.py [--port 8010] [--target https://mudassirllc.com]
"""

import argparse
import http.server
import os
import socketserver
import urllib.error
import urllib.parse
import urllib.request

PROXY_PREFIXES = ('/api/', '/media/')


class Handler(http.server.SimpleHTTPRequestHandler):
    target = 'https://mudassirllc.com'

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_PATCH(self):
        self._route('PATCH')

    def do_DELETE(self):
        self._route('DELETE')

    def do_OPTIONS(self):
        self._route('OPTIONS')

    def _route(self, method):
        if self.path.startswith(PROXY_PREFIXES):
            self._proxy(method)
        elif method == 'GET':
            # Flutter web is a single-page app: a deep link has no file on disk
            # and must be answered with index.html or a refresh 404s.
            if not os.path.exists(self.translate_path(self.path).rstrip('/')):
                self.path = '/'
            super().do_GET()
        else:
            self.send_error(405)

    def _proxy(self, method):
        url = self.target.rstrip('/') + self.path

        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None

        request = urllib.request.Request(url, data=body, method=method)
        # Forward the headers the API actually needs. Host is deliberately not
        # copied: it would still say 127.0.0.1 and production would reject it
        # as a disallowed host.
        for header in ('Authorization', 'Content-Type', 'Accept'):
            value = self.headers.get(header)
            if value:
                request.add_header(header, value)
        request.add_header('User-Agent', 'MudassirApp-DevProxy/1.0')

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                status = response.status
                content_type = response.headers.get(
                    'Content-Type', 'application/json')
        except urllib.error.HTTPError as error:
            # A 401 or a 400 is a real answer the app knows how to handle, so it
            # is passed through rather than turned into a proxy error.
            payload = error.read()
            status = error.code
            content_type = error.headers.get('Content-Type', 'application/json')
        except Exception as error:                      # noqa: BLE001
            payload = f'{{"detail": "dev proxy could not reach {self.target}: {error}"}}'.encode()
            status = 502
            content_type = 'application/json'

        # Rewrite absolute media URLs to this origin.
        #
        # Flutter WEB loads images with XMLHttpRequest, which is subject to
        # CORS — so https://mudassirllc.com/media/... is blocked from a
        # 127.0.0.1 page and every product shows a broken thumbnail. Android and
        # iOS use a plain HTTP client with no CORS concept and are unaffected,
        # so this is a browser-only artifact of previewing the app on the web.
        #
        # Pointing the URLs at this proxy makes them same-origin, and the /media/
        # prefix above forwards them on. The app itself needs no change.
        if 'json' in content_type and payload:
            payload = payload.replace(
                self.target.rstrip('/').encode() + b'/media/', b'/media/')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        # One readable line per request; the default logs the whole request line.
        print('  %s' % (fmt % args))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8010)
    parser.add_argument('--target', default='https://mudassirllc.com')
    parser.add_argument('--web-root', default='build/web')
    args = parser.parse_args()

    Handler.target = args.target
    os.chdir(args.web_root)

    # THREADED, not the default single-threaded server.
    #
    # A catalogue page asks for a dozen thumbnails at once. A server that
    # handles one request at a time resets the rest, and the app shows broken
    # images that look like a bug in the app rather than in this script.
    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with ThreadedServer(('127.0.0.1', args.port), Handler) as server:
        print(f'App    : http://127.0.0.1:{args.port}/')
        print(f'API    : proxied to {args.target}/api/v1/')
        print('Ctrl-C to stop.\n')
        server.serve_forever()


if __name__ == '__main__':
    main()
