"""Owner-only loopback gateway for Tailscale Serve. Never bind to LAN/WAN.

Tailscale Serve removes spoofed identity headers and sets its verified user.
This gateway trusts only that local proxy, denies missing/other identities,
and validates the browser origin before adapting requests to the local app.
"""
import argparse
import hashlib
import hmac
import http.client
import json
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
               'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}


def identity_hash(login):
    return hashlib.sha256(login.strip().casefold().encode('utf-8')).hexdigest()


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    origin = urlsplit(config['origin'])
    if (origin.scheme != 'https' or not origin.hostname or
            not origin.hostname.endswith('.ts.net') or origin.port not in (None, 443)
            or origin.path or origin.query or origin.fragment or origin.username or origin.password):
        raise ValueError('개인 접속 주소는 Tailscale의 HTTPS 주소여야 합니다.')
    digest = config.get('owner_hash', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('접속을 허용할 계정을 먼저 설정하세요.')
    return config


class PrivateHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log source filenames, query strings or account identities.

    def deny(self, status, message):
        # Drain small rejected bodies so Windows does not reset the connection
        # before the browser can receive the error response. Never wait on a
        # large or indefinitely streaming unauthorized upload.
        if status < 500 and self.command == 'POST':
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if 0 < size <= 64 * 1024 and not self.headers.get('Transfer-Encoding'):
                    self.connection.settimeout(1)
                    self.rfile.read(size)
            except (ValueError, OSError):
                pass
        body = json.dumps({'error': message}, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def forward(self):
        logins = self.headers.get_all('Tailscale-User-Login', [])
        if len(logins) != 1 or not hmac.compare_digest(identity_hash(logins[0]), self.server.config['owner_hash']):
            self.deny(403, 'Backspace 소유자의 Tailscale 계정으로 연결하세요.')
            return
        url = urlsplit(self.path)
        if not self.path.startswith('/') or self.path.startswith('//') or url.scheme or url.netloc:
            self.deny(400, '요청 주소를 확인하세요.')
            return
        if url.path.startswith('/auth/') or url.path == '/api/chatgpt/login':
            self.deny(403, 'ChatGPT 새 로그인은 Backspace가 실행 중인 PC에서 진행하세요. 기존 연결은 사용할 수 있습니다.')
            return
        origin = self.headers.get_all('Origin', [])
        if len(origin) > 1 or (origin and origin[0] != self.server.config['origin']):
            self.deny(403, '개인 Backspace 주소에서 요청하세요.')
            return
        if self.command == 'POST' and (self.headers.get('X-Backspace-Client') != 'web'
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self.deny(403, '현재 Backspace 화면에서 요청하세요.')
            return
        lengths = self.headers.get_all('Content-Length', [])
        try:
            size = int(lengths[0]) if lengths else 0
        except ValueError:
            size = -1
        maximum = 100 * 1024 * 1024 if url.path == '/api/upload' else 32 * 1024
        if (len(lengths) > 1 or self.headers.get('Transfer-Encoding') or size < 0
                or size > maximum or (self.command == 'POST' and size == 0)
                or (self.command == 'GET' and size != 0)):
            self.deny(413, '요청 크기를 확인하세요. 파일은 100MB 이하로 올릴 수 있습니다.')
            return
        upstream = http.client.HTTPConnection('127.0.0.1', self.server.backend_port, timeout=180)
        started = False
        try:
            self.connection.settimeout(120)
            connection_tokens = {v.strip().lower() for v in self.headers.get('Connection', '').split(',')}
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_HEADERS | connection_tokens | {'host', 'origin'}
                       and not k.lower().startswith(('tailscale-', 'x-forwarded-'))}
            headers['Host'] = f'127.0.0.1:{self.server.backend_port}'
            headers['Connection'] = 'close'
            if origin:
                headers['Origin'] = 'http://' + headers['Host']
            upstream.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers.items():
                upstream.putheader(name, value)
            upstream.endheaders()
            remaining = size
            while remaining:
                block = self.rfile.read(min(64 * 1024, remaining))
                if not block:
                    raise ConnectionError('Incomplete request')
                upstream.send(block)
                remaining -= len(block)
            response = upstream.getresponse()
            media_type = response.getheader('Content-Type', '').split(';')[0]
            encodings = self.headers.get('Accept-Encoding', '').lower().replace(' ', '').split(',')
            compress = ('gzip' in encodings and response.status == 200
                        and not response.getheader('Content-Encoding')
                        and not response.getheader('Content-Disposition')
                        and (media_type.startswith('text/') or media_type in ('application/json', 'application/javascript', 'image/svg+xml')))
            compressor = zlib.compressobj(level=5, wbits=31) if compress else None
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in HOP_HEADERS | {'server', 'date'} | ({'content-length', 'vary'} if compress else set()):
                    self.send_header(name, value)
            if compress:
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Vary', ', '.join(filter(None, [response.getheader('Vary'), 'Accept-Encoding'])))
            self.send_header('Connection', 'close')
            self.end_headers()
            started = True
            self.close_connection = True
            while block := response.read(64 * 1024):
                self.wfile.write(compressor.compress(block) if compressor else block)
            if compressor:
                self.wfile.write(compressor.flush())
        except (OSError, http.client.HTTPException):
            if not started:
                self.deny(502, 'PC에서 Backspace가 실행 중인지 확인하세요.')
            self.close_connection = True
        finally:
            upstream.close()

    do_GET = forward
    do_POST = forward


class PrivateServer(ThreadingHTTPServer):
    # HTTPS/2 clients request many scripts concurrently through Serve.
    request_queue_size = 64


def make_gateway(config, port=8788, backend_port=8786):
    server = PrivateServer(('127.0.0.1', port), PrivateHandler)
    server.config = config
    server.backend_port = backend_port
    return server


def main():
    parser = argparse.ArgumentParser(description='Backspace private Tailscale gateway')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    with make_gateway(config) as server:
        print('Backspace private gateway: 127.0.0.1:8788', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
