"""Check socket write boundaries using Linux x86-64 ptrace; no timing thresholds."""
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


def trace(command):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.ptrace.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    libc.ptrace.restype = ctypes.c_long

    def ptrace(request, pid, address=None, data=None):
        ctypes.set_errno(0)
        value = libc.ptrace(request, pid, address, data)
        error = ctypes.get_errno()
        if value == -1 and error:
            raise OSError(error, os.strerror(error))
        return value

    child = os.fork()
    if child == 0:
        with open(os.devnull, 'wb') as output:
            os.dup2(output.fileno(), 1)
        try:
            ptrace(0, 0)  # TRACEME
            os.kill(os.getpid(), signal.SIGSTOP)
            os.execvp(command[0], command)
        except OSError:
            os._exit(77)

    writes, alive, exit_code = [], {child}, None
    registers = (ctypes.c_ulonglong * 27)()
    try:
        _, status = os.waitpid(child, 0)
        if os.WIFEXITED(status):
            return [], os.WEXITSTATUS(status)
        # TRACESYSGOOD | TRACEFORK | TRACEVFORK | TRACECLONE | TRACEEXEC | EXITKILL
        ptrace(0x4200, child, None, 1 | 2 | 4 | 8 | 16 | 0x100000)
        ptrace(24, child)  # SYSCALL
        while alive:
            pid, status = os.waitpid(-1, 0x40000000)  # __WALL
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                alive.discard(pid)
                if pid == child:
                    exit_code = os.waitstatus_to_exitcode(status)
                continue
            alive.add(pid)
            sig = os.WSTOPSIG(status)
            if sig == signal.SIGTRAP | 0x80:
                ptrace(12, pid, None, ctypes.byref(registers))  # GETREGS
                # orig_rax=write; rax=-ENOSYS identifies syscall entry.
                if registers[15] == 1 and registers[10] == (1 << 64) - errno.ENOSYS:
                    fd, address, count = registers[14], registers[13], registers[12]
                    if os.readlink(f'/proc/{pid}/fd/{fd}').startswith('socket:'):
                        data = bytearray()
                        for offset in range(0, count, 8):
                            word = ptrace(2, pid, address + offset)  # PEEKDATA
                            data.extend((word & ((1 << 64) - 1)).to_bytes(8, 'little'))
                        writes.append(bytes(data[:count]).hex())
            deliver = 0 if sig in (signal.SIGTRAP, signal.SIGTRAP | 0x80, signal.SIGSTOP) else sig
            ptrace(24, pid, None, deliver)
        return writes, exit_code
    finally:
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@unittest.skipUnless(sys.platform == 'linux' and platform.machine() == 'x86_64',
                     'socket syscall tracing requires Linux x86-64')
class RequestWriteTests(unittest.TestCase):
    def test_timeout_removes_staged_request(self):
        for library in (False, True):
            with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                listener.settimeout(8)

                def serve():
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(8)
                        while connection.recv(65536):
                            pass  # Hold the response until the client closes on timeout.

                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                endpoint = ['127.0.0.1', str(listener.getsockname()[1]), 'who']
                command = (['bash', '-c', '. "$1"; shift; byond_topic "$@"', 'test',
                            str(ROOT / 'bash/byond-wire.sh')] if library else
                           ['bash', str(ROOT / 'bash/cli.sh')]) + endpoint
                env = os.environ.copy()
                env['TMPDIR'] = directory
                result = subprocess.run(command, capture_output=True, env=env, timeout=8)
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive(), 'socket remained open after timeout')
                self.assertEqual(result.returncode, 124)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(list(Path(directory).iterdir()), [], 'staged request leaked')

    def test_connection_failure_removes_staged_request(self):
        with socket.socket() as reserved, tempfile.TemporaryDirectory() as directory:
            reserved.bind(('127.0.0.1', 0))  # Bound but not listening: connection refused.
            env = os.environ.copy()
            env['TMPDIR'] = directory
            for library in (False, True):
                endpoint = ['127.0.0.1', str(reserved.getsockname()[1]), 'who']
                command = (['bash', '-c', '. "$1"; shift; byond_topic "$@"', 'test',
                            str(ROOT / 'bash/byond-wire.sh')] if library else
                           ['bash', str(ROOT / 'bash/cli.sh')]) + endpoint
                result = subprocess.run(command, capture_output=True, env=env, timeout=8)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(list(Path(directory).iterdir()), [], 'staged request leaked')

    def test_newline_bytes_do_not_split_small_requests(self):
        # Exercise a newline in each length byte and inside literal query text.
        for query in ('who', 'x' * 259, 'x' * 2553, 'a\nb'):
            for library in (False, True):
                with self.subTest(query_length=len(query), library=library):
                    self.check_request(query, library)

    def check_request(self, query, library):
        query_bytes = ('?' + query).encode()
        body = b'\0' * 5 + query_bytes + b'\0'
        expected = b'\0\x83' + len(body).to_bytes(2, 'big') + body
        received = bytearray()
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(10)

            def serve():
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(10)
                    while len(received) < len(expected):
                        chunk = connection.recv(len(expected) - len(received))
                        if not chunk:
                            return
                        received.extend(chunk)
                    connection.sendall(b'\0\x83\0\2\6\0')

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            endpoint = ['127.0.0.1', str(listener.getsockname()[1]), query]
            command = (['bash', '-c', '. "$1"; shift; byond_topic "$@"', 'test',
                        str(ROOT / 'bash/byond-wire.sh')] if library else
                       ['bash', str(ROOT / 'bash/cli.sh')]) + endpoint
            env = os.environ.copy()
            env['TMPDIR'] = directory
            process = subprocess.Popen([sys.executable, __file__, '--trace', *command],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=env, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=15)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                thread.join(timeout=11)
            if process.returncode == 77:
                self.skipTest('ptrace is unavailable')
            self.assertEqual(process.returncode, 0, stderr.decode())
            writes, exit_code = json.loads(stdout)
            self.assertEqual(exit_code, 0, stderr.decode())
            self.assertEqual(bytes(received), expected)
            self.assertEqual(list(Path(directory).iterdir()), [], 'temporary file leaked')
            self.assertEqual(writes, [expected.hex()], 'request must reach the socket in one write')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--trace':
        result = trace(sys.argv[2:])
        print(json.dumps(result))
        sys.exit(77 if result[1] == 77 else 0)
    unittest.main()
