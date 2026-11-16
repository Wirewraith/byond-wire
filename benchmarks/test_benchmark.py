import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('benchmark', Path(__file__).with_name('run.py'))

class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.util.module_from_spec(SPEC)
        try:
            SPEC.loader.exec_module(cls.module)
        except FileNotFoundError:
            cls.module = None

    def test_summary_counts_failures_and_excludes_their_times(self):
        self.assertIsNotNone(self.module, 'benchmark runner is not implemented')
        result = self.module.summarize([
            {'ms': 10, 'size': 12}, {'ms': 20, 'size': 30},
            {'ms': 5000, 'error': 'timeout', 'timeout': True}])
        self.assertEqual(result, {'median': 15, 'p95': None, 'ok': 2,
                                 'failures': 1, 'timeouts': 1, 'sizes': [12, 30]})

    def test_p95_uses_nearest_rank_after_twenty_successes(self):
        self.assertIsNotNone(self.module, 'benchmark runner is not implemented')
        result = self.module.summarize([{'ms': n, 'size': 4} for n in range(1, 21)])
        self.assertEqual(result['p95'], 19)

    def test_cli_validation_preserves_null_and_empty_text(self):
        self.assertIsNotNone(self.module, 'benchmark runner is not implemented')
        self.assertEqual(self.module.validate_cli(2, b'', 'null'), 0)
        self.assertEqual(self.module.validate_cli(0, b'', 'text'), 0)
        self.assertEqual(self.module.validate_cli(0, b'1.5', 'number'), 4)
        for code, value, kind in [(0, b'', 'null'), (2, b'x', 'null'),
                                  (0, b'no', 'number'), (0, b'\xff', 'text')]:
            with self.subTest(code=code, value=value, kind=kind):
                with self.assertRaises(ValueError):
                    self.module.validate_cli(code, value, kind)

    def test_rotation_gives_each_implementation_first_place(self):
        self.assertIsNotNone(self.module, 'benchmark runner is not implemented')
        self.assertEqual([self.module.rotate(['a', 'b', 'c'], n)[0]
                          for n in range(3)], ['a', 'b', 'c'])

class WorkerIntegrationTests(unittest.TestCase):
    """Real native library and CLI adapters against a controlled TCP server."""
    @classmethod
    def setUpClass(cls):
        import socketserver
        import struct
        import tempfile
        import threading
        import time
        cls.module = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.module)
        cls.build = tempfile.TemporaryDirectory(prefix='byond-worker-test-')
        cls.entries = cls.module.prepare(Path(cls.build.name))
        vector = next(line.split('\t') for line in (cls.module.ROOT / 'tests/text-vectors.tsv').read_text().splitlines()
                      if line.startswith('bare-proper\t'))
        cls.raw_vector, cls.decoded_vector = bytes.fromhex(vector[1]), bytes.fromhex(vector[2])

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                def read(n):
                    data = b''
                    while len(data) < n:
                        chunk = self.request.recv(n - len(data))
                        if not chunk:
                            raise EOFError()
                        data += chunk
                    return data
                header = read(4)
                if header[:2] != b'\x00\x83':
                    raise ValueError('invalid signature')
                request = read(int.from_bytes(header[2:], 'big'))
                if request[:5] != b'\0' * 5 or request[-1:] != b'\0':
                    raise ValueError('invalid request framing')
                query = request[5:-1].lstrip(b'?')
                query = {b'status': b'281', b'ping': b'number', b'who': b'0',
                         b'type=version': b'null'}.get(query, query)
                if query == b'number':
                    body = b'\x2a' + struct.pack('<f', 1.5)
                elif query == b'null':
                    body = b'\0'
                elif query == b'vector':
                    body = b'\x06' + cls.raw_vector + b'\0'
                elif query == b'stall':
                    time.sleep(6)
                    return
                else:
                    size = int(query)
                    body = b'\x06' + b'x' * size + b'\0'
                self.request.sendall(b'\0\x83' + len(body).to_bytes(2, 'big') + body)
        cls.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.address = ['127.0.0.1', str(cls.server.server_address[1])]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.build.cleanup()

    def test_native_library_workers_and_cli_contracts(self):
        for name, entry in self.entries.items():
            if 'unavailable' in entry:
                self.assertEqual(entry['unavailable'], 'runtime/tool not installed')
                print(f'Unavailable: {name}: {entry["unavailable"]}')
                continue
            worker = self.module.Worker(entry['worker'] + self.address)
            try:
                for query, kind, size in [('281', 'text', 281), ('65533', 'text', 65533),
                                          ('0', 'text', 0), ('number', 'number', 4), ('null', 'null', 0)]:
                    for mode in ['decoded', 'raw']:
                        with self.subTest(name=name, mode=mode, query=query):
                            result = worker.request(mode, query, kind)
                            self.assertEqual((result['kind'], result['size']), (kind, size))
                            self.assertGreaterEqual(result['ms'], 0)
                    with self.subTest(name=name, mode='cli', query=query):
                        result = self.module.cli_request(entry['cli'] + self.address + [query], kind)
                        self.assertEqual((result['kind'], result['size']), (kind, size))
                for mode, value in [('raw', self.raw_vector), ('decoded', self.decoded_vector)]:
                    with self.subTest(name=name, mode=mode, query='vector'):
                        self.assertEqual(worker.request(mode, 'vector', 'text')['size'], len(value))
                self.assertEqual(self.module.cli_request(entry['cli'] + self.address + ['vector'], 'text')['size'], len(self.raw_vector))
            finally:
                worker.close()

    def test_rust_socket_timeout_is_classified(self):
        entry = self.entries['Rust']
        if 'unavailable' in entry:
            self.skipTest(entry['unavailable'])
        worker = self.module.Worker(entry['worker'] + self.address)
        try:
            with self.assertRaises(TimeoutError):
                worker.request('raw', 'stall', 'text')
        finally:
            worker.close()

    def test_runner_writes_real_samples_and_report(self):
        import json
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'observations.json'
            report = Path(directory) / 'summary.md'
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('run.py')),
                '--host', self.address[0], '--port', self.address[1], '--only', 'Python',
                '--samples', '1', '--warmups', '1', '--pause', '0',
                '--output', str(output), '--report', str(report)], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            data = json.loads(output.read_text())
            self.assertEqual(len(data['samples']), 10)
            self.assertEqual({s['round'] for s in data['samples']}, {1})
            self.assertTrue(all('error' not in s for s in data['samples']))
            self.assertIn('](<observations.json>)', report.read_text())
            self.assertIn('281', report.read_text())

class WatchdogTests(unittest.TestCase):
    def test_partial_worker_line_cannot_bypass_watchdog(self):
        import sys
        module = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(module)
        module.WATCHDOG = .1
        worker = module.Worker([sys.executable, '-c',
                               'import os,time; os.write(1,b"1\\ttext\\t"); time.sleep(1)'])
        try:
            with self.assertRaises(TimeoutError):
                worker.request('raw', 'status', 'text')
        finally:
            worker.close()

if __name__ == '__main__':
    unittest.main()
