"""Direction B: HTTP transport robustness.

Verifies the already-shipped retry policy actually covers the WinError 10053
family (ConnectionAbortedError / ConnectionResetError -> ConnectionError ->
URLError), that retries reuse a byte-identical body and request id, that business
rejections (HTTPError) are never retried, and that the opt-in pre-flight health
probe is a plain TCP check.
"""
import http.client
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import backend as backend_module
from backend import HTTPBackend


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FlakyOpener:
    """Raises the given errors, then succeeds; records every attempt."""

    def __init__(self, errors, payload):
        self.errors = list(errors)
        self.payload = payload
        self.attempts = []

    def open(self, request, timeout=None):
        self.attempts.append({'body': request.data, 'url': request.full_url})
        if self.errors:
            raise self.errors.pop(0)
        return _FakeResponse(self.payload)


def _make_backend(tmpdir, opener):
    with patch.object(backend_module.HTTPBackend, '_open_log', lambda self: None, create=True):
        pass
    be = HTTPBackend.__new__(HTTPBackend)
    be.robot_id = 'r1'
    be.url = 'http://127.0.0.1:2026'
    be.virtual_time = 0.
    be.log = io.StringIO()
    be.deadline = 1e18
    be.session = 'sess'
    be.seq = 0
    be.opener = opener
    return be


class HttpRetryTests(unittest.TestCase):
    def _payload(self):
        return {'accepted': True, 'virtual_time_s': 0.0, 'remaining_real_duration_s': 900}

    def test_winerror_10053_family_is_retried_with_identical_body(self):
        errors = [ConnectionAbortedError(10053, 'aborted'),
                  ConnectionResetError(10054, 'reset'),
                  urllib.error.URLError('wrapped')]
        opener = _FlakyOpener(errors, self._payload())
        be = _make_backend(None, opener)
        with patch.object(backend_module.time, 'sleep', lambda s: None):
            result = be.post('/enter', {})
        self.assertTrue(result['accepted'])
        self.assertEqual(len(opener.attempts), 4)
        bodies = {a['body'] for a in opener.attempts}
        self.assertEqual(len(bodies), 1, 'retry must reuse a byte-identical body/request_id')
        self.assertTrue(json.loads(bodies.pop())['request_id'].startswith('sess-'))

    def test_incomplete_read_is_retried(self):
        opener = _FlakyOpener([http.client.IncompleteRead(b'x')], self._payload())
        be = _make_backend(None, opener)
        with patch.object(backend_module.time, 'sleep', lambda s: None):
            be.post('/enter', {})
        self.assertEqual(len(opener.attempts), 2)

    def test_http_error_is_not_retried(self):
        class _Rejecting:
            def __init__(self):
                self.calls = 0

            def open(self, request, timeout=None):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 400, 'bad', {}, None)

        opener = _Rejecting()
        be = _make_backend(None, opener)
        with self.assertRaises(urllib.error.HTTPError):
            be.post('/enter', {})
        self.assertEqual(opener.calls, 1)

    def test_transport_error_exhaustion_surfaces(self):
        opener = _FlakyOpener([ConnectionAbortedError(10053, 'x')] * 6, self._payload())
        be = _make_backend(None, opener)
        with patch.object(backend_module.time, 'sleep', lambda s: None):
            with self.assertRaises(ConnectionAbortedError):
                be.post('/enter', {})
        self.assertEqual(len(opener.attempts), 6)

    def test_health_probe_uses_tcp_only_and_retries(self):
        calls = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_create_connection(addr, timeout=None):
            calls.append(addr)
            if len(calls) == 1:
                raise OSError('refused')
            return _Ctx()

        with patch.object(backend_module.socket, 'create_connection', fake_create_connection), \
             patch.object(backend_module.time, 'sleep', lambda s: None):
            self.assertTrue(backend_module.health_check('http://127.0.0.1:2026'))
        self.assertEqual(calls[0], ('127.0.0.1', 2026))
        self.assertEqual(len(calls), 2)

    def test_health_probe_reports_unreachable(self):
        with patch.object(backend_module.socket, 'create_connection',
                          side_effect=OSError('refused')), \
             patch.object(backend_module.time, 'sleep', lambda s: None):
            with self.assertRaises(ConnectionError):
                backend_module.health_check('http://127.0.0.1:2026', attempts=2)


if __name__ == '__main__':
    unittest.main()
