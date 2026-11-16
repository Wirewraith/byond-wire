"""Standard-library wire tests: python3 -m unittest discover -s python."""
import contextlib
import importlib.util
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('cli.py')


@contextlib.contextmanager
def server(reply, fragment=False, hold=False, delay=0):
    request = bytearray()
    errors = []
    stop = threading.Event()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(2)
        port = listener.getsockname()[1]

        def serve():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(2)
                    size = 4
                    while len(request) < size:
                        chunk = conn.recv(size - len(request))
                        if not chunk:
                            return
                        request.extend(chunk)
                        if len(request) == 4:
                            size += int.from_bytes(request[2:4], 'big')
                    chunks = (bytes([b]) for b in reply) if fragment else (reply,)
                    for chunk in chunks:
                        if stop.wait(delay):
                            return
                        conn.sendall(chunk)
                    if hold:
                        stop.wait(2)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            yield port, request
        finally:
            stop.set()
            thread.join(3)
            if thread.is_alive():
                raise AssertionError('Test server did not stop')
            if errors:
                raise errors[0]


def frame(body):
    return b'\x00\x83' + struct.pack('>H', len(body)) + body


class TopicTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, timeout=7)

    def exchange(self, query, reply, expected=b'', code=0, **options):
        with server(reply, **options) as (port, request):
            result = self.invoke('127.0.0.1', port, query)
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout, expected)
        query_bytes = (query if query.startswith('?') else '?' + query).encode()
        self.assertEqual(bytes(request), frame(b'\0' * 5 + query_bytes + b'\0'))
        if code == 1:
            self.assertTrue(result.stderr)
        else:
            self.assertEqual(result.stderr, b'')

    def test_default_api_returns_decoded_strings(self):
        import byond_wire
        for body, expected in [(b'\x06\xff\x16caf\xc3\xa9\0', 'café'),
                               (b'\x06\0', ''), (b'\0', None),
                               (bytes.fromhex('2a000020c0'), -2.5)]:
            with server(frame(body)) as (port, _):
                self.assertEqual(byond_wire.topic('127.0.0.1', port, 'status'), expected)
        for data in [b'\xff', b'\xff\x1b', b'\xc3\xff\x15\xa9']:
            with server(frame(b'\x06' + data + b'\0')) as (port, _):
                with self.assertRaises(ValueError):
                    byond_wire.topic('127.0.0.1', port, 'status')

    def test_importable_api(self):
        import byond_wire
        for body, expected in [(b'\x06\xff\0', b'\xff'), (b'\x06\0', b''),
                               (b'\0', None), (bytes.fromhex('2a000020c0'), -2.5)]:
            with server(frame(body)) as (port, request):
                self.assertEqual(byond_wire.topic_raw('127.0.0.1', port, 'status'), expected)
            self.assertEqual(request, frame(b'\0' * 5 + b'?status\0'))
        result = subprocess.run([sys.executable, '-c', 'import byond_wire'],
                                cwd=SCRIPT.parent, capture_output=True, timeout=2)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def test_canonical_request(self):
        with server(bytes.fromhex('00 83 00 04 06 68 69 00')) as (port, request):
            result = self.invoke('127.0.0.1', port, 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'hi')
        self.assertEqual(request, bytes.fromhex(
            '00 83 00 0d 00 00 00 00 00 3f 73 74 61 74 75 73 00'))

    def test_values(self):
        for body, output, code in [
            (b'\x06\0', b'', 0), (b'\0', b'', 2),
            (b'\x06ab\n\\\xff\n\0', b'ab\n\\\xff\n', 0),
            (bytes.fromhex('2a 00 00 80 3f'), b'1', 0),
            (bytes.fromhex('2a 00 00 00 00'), b'0', 0),
            (bytes.fromhex('2a 00 00 20 c0'), b'-2.5', 0),
            (b'\x06' + b'x' * 65533 + b'\0', b'x' * 65533, 0),
        ]:
            with self.subTest(length=len(body), tag=body[:1]):
                self.exchange('status', frame(body), output, code)

    def test_query_data_and_boundaries(self):
        for query in ['?status', '??status', 'café', '',
                      r"status'; printf MARKER; #$(printf MARKER)`id`\n\c*?[a-z]",
                      'x' * 280, 'x' * 65528, '?' + 'x' * 65528]:
            with self.subTest(length=len(query)):
                self.exchange(query, frame(b'\0'), code=2)

    def test_malformed_replies(self):
        for reply in [b'', b'\0\x83\0', b'\xff\xff\0\1\0',
                      frame(b''), frame(b'\x06'), frame(b'\x06ab'),
                      frame(b'\x07'), frame(b'\0\0'), frame(b'\x2a\0'),
                      b'\0\x83\0\x0a\x06abc']:
            with self.subTest(reply=reply):
                self.exchange('status', reply, code=1)

    def test_fragmentation_and_persistent_connection(self):
        self.exchange('status', frame(b'\x06hello\0'), b'hello',
                      fragment=True, delay=.003, hold=True)

    def test_bad_arguments(self):
        for args in [(), ('host',), ('', '4999', 'status'),
                     ('127.0.0.1', '0', 'status'),
                     ('127.0.0.1', '65536', 'status'),
                     ('127.0.0.1', 'x', 'status'),
                     ('127.0.0.1', '1', 'x' * 65529),
                     ('127.0.0.1', '1', 'é' * 32765)]:
            with self.subTest(args_length=len(args)):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, b'')
                self.assertTrue(result.stderr)
                self.assertNotIn(b'Traceback', result.stderr)
        result = self.invoke('127.0.0.1', '1', 'x' * 65529)
        self.assertIn(b'two-byte frame length', result.stderr)

    def test_refused_connection(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            result = self.invoke('127.0.0.1', reserved.getsockname()[1], 'status')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)

    def test_cli_timeout(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            process = subprocess.Popen(
                [sys.executable, str(SCRIPT), '127.0.0.1',
                 str(listener.getsockname()[1]), 'status'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                listener.settimeout(2)
                with listener.accept()[0]:
                    stdout, stderr = process.communicate(timeout=7)
                self.assertEqual(process.returncode, 124, stderr)
                self.assertEqual(stdout, b'')
                self.assertIn(b'timed out', stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_legacy_socket_timeout_is_normalized(self):
        import byond_wire

        class LegacyTimeout(OSError):
            pass

        # Before Python 3.10, socket.timeout was separate from TimeoutError.
        with patch.object(socket, 'timeout', LegacyTimeout), \
             patch.object(byond_wire, 'connect', side_effect=LegacyTimeout('timed out')):
            for call in (byond_wire.topic, byond_wire.topic_raw):
                with self.subTest(call=call.__name__), self.assertRaises(TimeoutError):
                    call('127.0.0.1', 4999, 'status')

    def test_embedded_nul_query(self):
        spec = importlib.util.spec_from_file_location('byond_wire', SCRIPT)
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        with self.assertRaises(ValueError):
            client.topic('127.0.0.1', 1, 'status\0ignored')

    def test_invalid_timeouts_fail_before_dns_or_socket_creation(self):
        import byond_wire
        for call in (byond_wire.topic, byond_wire.topic_raw):
            for timeout in (float('nan'), float('inf'), -float('inf'), 0, -1,
                            2147483648, 1e100, None, '5'):
                with self.subTest(call=call.__name__, timeout=timeout), \
                     patch('socket.getaddrinfo', side_effect=AssertionError('DNS attempted')), \
                     patch('socket.socket', side_effect=AssertionError('Socket created')):
                    with self.assertRaises(ValueError):
                        call('127.0.0.1', 4999, 'status', timeout)

    def test_invalid_ports_fail_before_dns_or_socket_creation(self):
        import byond_wire
        for call in (byond_wire.topic, byond_wire.topic_raw):
            for port in (True, False, 1.5, float('nan'), float('inf'), 0, -1,
                         65536, '4999', None):
                with self.subTest(call=call.__name__, port=port), \
                     patch('socket.getaddrinfo', side_effect=AssertionError('DNS attempted')), \
                     patch('socket.socket', side_effect=AssertionError('Socket created')):
                    with self.assertRaises(ValueError):
                        call('127.0.0.1', port, 'status')

    def test_maximum_timeout_can_complete(self):
        import byond_wire
        with server(frame(b'\x06ok\0')) as (port, _):
            self.assertEqual(byond_wire.topic('127.0.0.1', port, 'status', 2147483647), 'ok')

    def test_connection_attempts_share_deadline(self):
        import byond_wire
        elapsed = [0.0]
        sockets = []

        class SlowSocket:
            closed = False

            def __init__(self, *args):
                sockets.append(self)

            def settimeout(self, timeout):
                self.timeout = timeout

            def connect(self, address):
                elapsed[0] += min(.06, self.timeout)
                raise TimeoutError('Endpoint timed out')

            def close(self):
                self.closed = True

        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 4999)),
                     (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.2', 4999))]
        with patch('socket.getaddrinfo', return_value=addresses), \
             patch('socket.socket', SlowSocket), \
             patch('time.monotonic', side_effect=lambda: elapsed[0]):
            with self.assertRaises(TimeoutError):
                byond_wire.topic('example.invalid', 4999, 'status', timeout=.1)
        self.assertLessEqual(elapsed[0], .100001)
        self.assertTrue(all(sock.closed for sock in sockets))

    def test_expired_dns_budget_does_not_open_socket(self):
        import byond_wire
        elapsed = [0.0]

        def resolve(*args):
            elapsed[0] = .2
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 4999))]

        with patch('socket.getaddrinfo', side_effect=resolve), \
             patch('socket.socket') as create_socket, \
             patch('time.monotonic', side_effect=lambda: elapsed[0]):
            with self.assertRaises(TimeoutError):
                byond_wire.topic('example.invalid', 4999, 'status', timeout=.1)
            create_socket.assert_not_called()

    def test_connection_falls_back_after_socket_creation_error(self):
        import byond_wire
        original_socket = socket.socket

        def create_socket(family, *args, **kwargs):
            if family == socket.AF_INET6:
                raise OSError('IPv6 is unavailable')
            return original_socket(family, *args, **kwargs)

        with server(frame(b'\x06ok\0')) as (port, _):
            addresses = [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', port, 0, 0)),
                         (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
            with patch('socket.getaddrinfo', return_value=addresses), \
                 patch('socket.socket', side_effect=create_socket):
                self.assertEqual(byond_wire.topic('example.invalid', port, 'status'), 'ok')

    def test_connection_falls_back_to_next_address(self):
        import byond_wire
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            with server(frame(b'\x06ok\0')) as (port, request):
                addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', reserved.getsockname()),
                             (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
                with patch('socket.getaddrinfo', return_value=addresses):
                    self.assertEqual(byond_wire.topic('example.invalid', port, 'status'), 'ok')
            self.assertEqual(request, frame(b'\0' * 5 + b'?status\0'))

    def test_decode_text_vectors(self):
        import byond_wire
        vectors = SCRIPT.parent.parent / 'tests' / 'text-vectors.tsv'
        if not vectors.exists():
            vectors = SCRIPT.parent / 'tests' / 'text-vectors.tsv'
        for line in vectors.read_text().splitlines():
            if line.startswith('#'):
                continue
            name, encoded, expected = line.split('\t')
            data = bytes.fromhex(encoded)
            with self.subTest(name=name):
                if expected == '-':
                    with self.assertRaises(ValueError):
                        byond_wire.decode_text(data)
                else:
                    self.assertEqual(byond_wire.decode_text(data), bytes.fromhex(expected).decode())
        self.assertEqual(byond_wire.decode_text(b'x' * 65533), 'x' * 65533)

    def test_total_deadline(self):
        spec = importlib.util.spec_from_file_location('byond_wire', SCRIPT)
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        start = time.monotonic()
        with server(frame(b'\x06hello\0'), fragment=True, delay=.03) as (port, _):
            with self.assertRaises(TimeoutError):
                client.topic('127.0.0.1', port, 'status', timeout=.12)
        self.assertLess(time.monotonic() - start, .5)


if __name__ == '__main__':
    unittest.main()
