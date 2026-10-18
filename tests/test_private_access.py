import http.client
import gzip
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backspace_mvp.private_access import identity_hash, load_config, make_gateway
from scripts.start_private_access import serve_conflicts


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def handle_request(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.calls.append((self.path, dict(self.headers), body))
        value = b'export-bytes' if self.command == 'GET' else body
        self.send_response(200)
        self.send_header('Content-Length', str(len(value)))
        if self.path == '/data':
            self.send_header('Content-Type', 'application/json')
        else:
            self.send_header('Content-Disposition', 'attachment; filename="model.json"')
        self.end_headers()
        self.wfile.write(value)

    do_GET = handle_request
    do_POST = handle_request


class PrivateAccessTests(unittest.TestCase):
    def setUp(self):
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.backend.calls = []
        self.config = {'origin': 'https://test.example.ts.net', 'owner_hash': identity_hash('owner@example.test')}
        self.gateway = make_gateway(self.config, 0, self.backend.server_port)
        for server in (self.backend, self.gateway):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

    def request(self, method='GET', path='/api/data?mode=workspace', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def owner(self, **extra):
        return {'Tailscale-User-Login': 'owner@example.test', **extra}

    def test_missing_or_other_identity_never_reaches_backend(self):
        for headers in ({}, {'Tailscale-User-Login': 'someone@example.test'}):
            self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertFalse(self.backend.calls)
        self.assertEqual(self.gateway.server_address[0], '127.0.0.1')

    def test_allowed_download_preserves_bytes_and_attachment(self):
        status, body, headers = self.request(path='/api/export?kind=model', headers=self.owner())
        self.assertEqual((status, body), (200, b'export-bytes'))
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="model.json"')
        sent = self.backend.calls[-1][1]
        self.assertEqual(sent['Host'], f'127.0.0.1:{self.backend.server_port}')
        self.assertNotIn('Tailscale-User-Login', sent)

    def test_compression_preserves_data_and_leaves_downloads_unmodified(self):
        headers = self.owner(**{'Accept-Encoding': 'gzip, deflate'})
        status, body, response = self.request(path='/data', headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(gzip.decompress(body), b'export-bytes')
        self.assertEqual(response['Content-Encoding'], 'gzip')
        self.assertNotIn('Content-Length', response)
        _, body, response = self.request(path='/api/export', headers=headers)
        self.assertEqual(body, b'export-bytes')
        self.assertNotIn('Content-Encoding', response)

    def test_cross_site_and_unmarked_changes_are_denied(self):
        for extra in ({'Origin': 'https://evil.example', 'X-Backspace-Client': 'web'},
                      {'Origin': self.config['origin']},
                      {'X-Backspace-Client': 'web', 'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.request('POST', '/api/jobs', b'{}', self.owner(**extra))[0], 403)
        self.assertFalse(self.backend.calls)

    def test_upload_stream_and_same_origin_adaptation(self):
        body = b'abc123' * 30000
        headers = self.owner(**{'Origin': self.config['origin'], 'X-Backspace-Client': 'web',
                               'Content-Type': 'application/octet-stream'})
        status, returned, _ = self.request('POST', '/api/upload?filename=example.txt', body, headers)
        self.assertEqual((status, returned), (200, body))
        self.assertEqual(self.backend.calls[-1][2], body)
        self.assertEqual(self.backend.calls[-1][1]['Origin'], f'http://127.0.0.1:{self.backend.server_port}')

    def test_oversize_and_remote_login_are_blocked(self):
        self.assertEqual(self.request('POST', '/api/jobs', b'x'*32769,
            self.owner(**{'X-Backspace-Client': 'web'}))[0], 413)
        for path in ('/api/chatgpt/login', '/auth/callback?code=example'):
            self.assertEqual(self.request(path=path, headers=self.owner())[0], 403)
        self.assertFalse(self.backend.calls)

    def test_invalid_host_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'private.json'
            p.write_text(json.dumps(self.config), encoding='utf-8')
            self.assertEqual(load_config(p), self.config)
            for origin in ('http://test.example.ts.net', 'https://example.com',
                           'https://test.example.ts.net/path', 'https://test.example.ts.net@evil.com'):
                p.write_text(json.dumps({**self.config, 'origin': origin}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(p)

    def test_launcher_preserves_other_services_and_rejects_public_funnel(self):
        origin = self.config['origin']
        current = {'TCP': {'443': {'HTTPS': True}},
                   'Web': {'test.example.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8788'}}}}}
        self.assertFalse(serve_conflicts({}, origin))
        self.assertFalse(serve_conflicts(current, origin))
        self.assertTrue(serve_conflicts({**current, 'AllowFunnel': {'test.example.ts.net:443': True}}, origin))
        self.assertTrue(serve_conflicts({'TCP': {'443': {'TCPForward': 'localhost:1234'}}}, origin))
        current['Web']['test.example.ts.net:443']['Handlers']['/']['Proxy'] = 'http://127.0.0.1:3000'
        self.assertTrue(serve_conflicts(current, origin))
