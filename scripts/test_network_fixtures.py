"""Real local-socket regressions for bounded readiness and TCP fixture framing."""
from contextlib import contextmanager
import hashlib
import importlib
import importlib.util
import io
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'netguard'))
CONFIG = (b'{"schemaVersion":"0.1.0","officialIpv4":["8.8.8.8"],'
          b'"postgresIpv4":"172.28.0.2","keycloakIpv4":"172.28.0.3","webIpv4":"172.28.0.4"}')
DIGEST = hashlib.sha256(CONFIG).hexdigest().encode()


def response(body=DIGEST, status=b'200 OK', headers=None):
    headers = [b'Content-Length: ' + str(len(body)).encode()] if headers is None else headers
    return b'HTTP/1.0 ' + status + b'\r\n' + b'\r\n'.join(headers) + b'\r\n\r\n' + body


@contextmanager
def local_response(payload, trickle=None):
    """Bind the real fixed endpoint; no production URL/port injection or DNS."""
    stopped = threading.Event()
    failures = []
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 18081))
    listener.listen(1)
    listener.settimeout(0.1)

    def serve():
        try:
            while not stopped.is_set():
                try:
                    connection, _ = listener.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            with connection:
                connection.settimeout(0.5)
                request = b''
                while b'\r\n\r\n' not in request and len(request) < 1024:
                    chunk = connection.recv(1024 - len(request))
                    if not chunk:
                        return
                    request += chunk
                if request.split(b'\r\n')[0] not in (b'GET /ready HTTP/1.0', b'GET /ready HTTP/1.1'):
                    failures.append('health requested a different method/path')
                    return
                header, _, body = payload.partition(b'\r\n\r\n')
                if trickle == 'headers':
                    chunks = [bytes([byte]) for byte in header + b'\r\n\r\n'] + [body]
                elif trickle == 'body':
                    chunks = [header + b'\r\n\r\n'] + [bytes([byte]) for byte in body]
                else:
                    chunks = [payload]
                for chunk in chunks:
                    if stopped.is_set():
                        return
                    connection.sendall(chunk)
                    if trickle and stopped.wait(0.05):
                        return
        except OSError:
            # Deadline rejection closes the real client socket mid-response.
            pass

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        listener.close()
        worker.join(1)
        if worker.is_alive() or failures:
            raise AssertionError('controlled health responder did not terminate cleanly: ' + ','.join(failures))


class HealthDeadlineTests(unittest.TestCase):
    def call_health(self):
        module = importlib.import_module('guard')
        with patch.object(Path, 'open', mock_open(read_data=CONFIG)), \
             patch.object(sys, 'stderr', new_callable=io.StringIO) as error:
            started = time.monotonic()
            code = module.main(['health'])
            elapsed = time.monotonic() - started
        self.assertEqual(error.getvalue(), '' if code == 0 else 'network guard operation failed\n')
        return code, elapsed

    def test_slow_headers_cannot_extend_total_health_probe_beyond_one_second(self):
        with local_response(response(), trickle='headers'):
            code, elapsed = self.call_health()
        self.assertEqual((code, elapsed < 1.35), (1, True), f'health exit={code}, elapsed={elapsed:.3f}s')

    def test_slow_body_cannot_extend_total_health_probe_beyond_one_second(self):
        with local_response(response(), trickle='body'):
            code, elapsed = self.call_health()
        self.assertEqual((code, elapsed < 1.35), (1, True), f'health exit={code}, elapsed={elapsed:.3f}s')

    def test_fast_health_requires_exact_status_digest_and_bounded_unambiguous_framing(self):
        cases = [
            ('valid', response(), 0),
            ('redirect', response(status=b'301 Moved'), 1),
            ('wrong-status', response(status=b'201 Created'), 1),
            ('wrong-digest', response(body=b'b' * 64), 1),
            ('too-long-body', response(body=DIGEST + b'x'), 1),
            ('undeclared-extra-body', response(body=DIGEST + b'x', headers=[b'Content-Length: 64']), 1),
            ('short-body', response(body=DIGEST[:-1], headers=[b'Content-Length: 64']), 1),
            ('duplicate-length', response(headers=[b'Content-Length: 64', b'Content-Length: 64']), 1),
            ('oversize-headers', response(headers=[b'Content-Length: 64', b'X-Padding: ' + b'x' * 5000]), 1),
            ('chunked', response(headers=[b'Transfer-Encoding: chunked']), 1),
        ]
        for label, payload, expected in cases:
            with self.subTest(case=label), local_response(payload):
                code, elapsed = self.call_health()
                self.assertEqual(code, expected)
                self.assertLess(elapsed, 1.35)


class StreamFramingTests(unittest.TestCase):
    def reader(self):
        spec = importlib.util.spec_from_file_location('network_test_fixture', ROOT / 'scripts/network-fixtures/fixture.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, 'read_exact', None)), 'missing exact TCP frame reader')
        return module.read_exact

    def test_tick_reader_preserves_a_coalesced_next_frame(self):
        read_exact = self.reader()
        sender, receiver = socket.socketpair()
        with sender, receiver:
            receiver.settimeout(0.5)
            sender.sendall(b'ticktick')
            self.assertEqual(read_exact(receiver, 4), b'tick')
            self.assertEqual(read_exact(receiver, 4), b'tick')

    def test_tick_reader_assembles_segmented_bytes(self):
        read_exact = self.reader()
        sender, receiver = socket.socketpair()
        with sender, receiver:
            receiver.settimeout(0.5)
            sender.sendall(b't')
            def remainder():
                time.sleep(0.02)
                sender.sendall(b'ick')
            worker = threading.Thread(target=remainder, daemon=True)
            worker.start()
            try:
                self.assertEqual(read_exact(receiver, 4), b'tick')
            finally:
                worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_tick_reader_rejects_eof_mid_frame(self):
        read_exact = self.reader()
        sender, receiver = socket.socketpair()
        with sender, receiver:
            receiver.settimeout(0.5)
            sender.sendall(b'ti')
            sender.shutdown(socket.SHUT_WR)
            with self.assertRaises(ValueError):
                read_exact(receiver, 4)


class RequestErrorSanitizationTests(unittest.TestCase):
    def request_failure(self, boundary, failure):
        module = importlib.import_module('guard')
        data = CONFIG[:-1] + b',"allowOfficial":true}'
        readback = (ROOT / 'scripts/network-fixtures/nft-readback-1.1.5.json').read_text()
        nft_results = [subprocess.CompletedProcess(['nft'], 0, '', ''),
                       subprocess.CompletedProcess(['nft'], 0, readback, '')]

        def serve_one(server, poll_interval):
            # Preserve actual server accept, handler construction, request
            # dispatch, error handling and shutdown; only bound the service loop.
            with socket.create_connection(('127.0.0.1', 18081), timeout=1) as client:
                client.sendall(b'GET /ready HTTP/1.0\r\nHost: localhost\r\n\r\n')
                server._handle_request_noblock()

        owner, method = boundary
        with patch.object(Path, 'open', mock_open(read_data=data)), \
             patch.object(module.subprocess, 'run', side_effect=nft_results), \
             patch.object(module.http.server.HTTPServer, 'serve_forever', new=serve_one), \
             patch.object(owner, method, side_effect=failure), \
             patch.object(sys, 'stderr', new_callable=io.StringIO) as error:
            self.assertEqual(module.main(['serve']), 0)
        self.assertEqual(error.getvalue(), 'network guard request failed\n')
        self.assertNotIn('Traceback', error.getvalue())
        self.assertNotIn('synthetic-private', error.getvalue())
        self.assertNotIn('127.0.0.1', error.getvalue())

    def test_request_dispatch_sanitizes_connection_reset_during_request_read(self):
        self.request_failure((socket.SocketIO, 'readinto'),
                             ConnectionResetError('synthetic-private-read-detail'))

    def test_request_dispatch_sanitizes_broken_pipe_during_response_write(self):
        self.request_failure((socketserver._SocketWriter, 'write'),
                             BrokenPipeError('synthetic-private-write-detail'))


class WrapperCountMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('network_wrapper_fixture', ROOT / 'scripts/test-agent-network.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def call_wrapper(self, output, *, success=False, probes=30):
        harness = self.module.Harness.__new__(self.module.Harness)
        harness.platform = 'synthetic-platform-image'
        with patch.object(harness, 'create', return_value='synthetic-wrapper-container'), \
             patch.object(harness, 'attach', return_value=(output, 0 if success else 1)):
            harness.wrapper('synthetic-namespace', 'count-markers', 'a' * 64,
                            success=success, probes=probes, hostile=False)

    def test_wrapper_accepts_exact_unique_counts(self):
        cases = [
            ('bounded-failure', 'probes=30\nintervals=29', False, 30),
            ('wc-whitespace', 'probes= 30 \nintervals=\t29 ', False, 30),
            ('admitted-java', '-jar\n/opt/archguard/platform.jar\nprobes=1\nintervals=0', True, 1),
            ('preflight-failure', 'probes=0\nintervals=0', False, 0),
        ]
        for label, output, success, probes in cases:
            with self.subTest(case=label):
                self.call_wrapper(output, success=success, probes=probes)

    def test_wrapper_rejects_300_probes_and_299_intervals_for_30_and_29(self):
        with self.assertRaisesRegex(AssertionError, 'bounded probe count count-markers'):
            self.call_wrapper('probes=300\nintervals=299')

    def test_wrapper_rejects_count_prefixes(self):
        cases = [
            ('probe-prefix', 'probes=300\nintervals=29', False, 30, 'bounded probe count'),
            ('interval-prefix', 'probes=30\nintervals=299', False, 30, 'bounded intervals'),
            ('one-probe-prefix', '-jar\n/opt/archguard/platform.jar\nprobes=10\nintervals=0',
             True, 1, 'bounded probe count'),
        ]
        for label, output, success, probes, assertion in cases:
            with self.subTest(case=label), self.assertRaisesRegex(AssertionError, assertion + ' count-markers'):
                self.call_wrapper(output, success=success, probes=probes)

    def test_wrapper_rejects_duplicate_missing_and_malformed_markers(self):
        cases = [
            ('duplicate-probes', 'probes=30\nprobes=30\nintervals=29', 'bounded probe count'),
            ('duplicate-intervals', 'probes=30\nintervals=29\nintervals=29', 'bounded intervals'),
            ('missing-probes', 'intervals=29', 'bounded probe count'),
            ('missing-intervals', 'probes=30', 'bounded intervals'),
            ('malformed-probes', 'probes:30\nintervals=29', 'bounded probe count'),
            ('malformed-intervals', 'probes=30\nintervals:29', 'bounded intervals'),
            ('noninteger-probes', 'probes=thirty\nintervals=29', 'bounded probe count'),
            ('noninteger-intervals', 'probes=30\nintervals=twenty-nine', 'bounded intervals'),
            ('suffixed-probes', 'probes=30x\nintervals=29', 'bounded probe count'),
            ('suffixed-intervals', 'probes=30\nintervals=29x', 'bounded intervals'),
        ]
        for label, output, assertion in cases:
            with self.subTest(case=label), self.assertRaisesRegex(AssertionError, assertion + ' count-markers'):
                self.call_wrapper(output)


if __name__ == '__main__':
    unittest.main()
