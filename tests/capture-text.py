#!/usr/bin/env python3
"""Validate captured macro vectors against a real BYOND compiler and daemon."""
import argparse
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    installed = Path('/mnt/c/Program Files (x86)/BYOND/bin')
    parser.add_argument('--compiler', default=shutil.which('DreamMaker') or str(installed / 'dm.exe'))
    parser.add_argument('--daemon', default=shutil.which('DreamDaemon') or str(installed / 'dd.exe'))
    parser.add_argument('--port', type=int, default=5101)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent / 'python'))
    from byond_wire import decode_text

    def executable_path(path, executable):
        if executable.lower().endswith('.exe') and sys.platform == 'linux':
            return subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
        return str(path)

    def exact(conn, count):
        data = bytearray()
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                raise EOFError('Incomplete probe response')
            data.extend(chunk)
        return bytes(data)

    def topic(query):
        body = b'\0' * 5 + query.encode('ascii') + b'\0'
        with socket.create_connection(('127.0.0.1', args.port), timeout=3) as conn:
            conn.sendall(b'\0\x83' + struct.pack('>H', len(body)) + body)
            header = exact(conn, 4)
            if header[:2] != b'\0\x83':
                raise ValueError('Non-Topic probe response')
            reply = exact(conn, int.from_bytes(header[2:], 'big'))
        if reply[:1] != b'\x06' or reply[-1:] != b'\0':
            raise ValueError('Expected a text probe response')
        return reply[1:-1]

    def normalize_refs(data):
        return re.sub(rb'\[0x[0-9a-fA-F]+\]', b'[ref]', data)

    with tempfile.TemporaryDirectory(prefix='byond-text-') as directory:
        work = Path(directory)
        source = (root / 'text-macros.dme').read_text()
        identity = ('byond-wire text-macro-probe/' + secrets.token_hex(16)).encode('ascii')
        rendered = source.replace('byond-wire text-macro-probe', identity.decode('ascii'))
        (work / 'text-macros.dme').write_text(rendered)
        shutil.copyfile(root / 'text-macro-icon.png', work / 'text-macro-icon.png')
        compiled = subprocess.run([args.compiler, executable_path(work / 'text-macros.dme', args.compiler)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)
        labels = set(re.findall(r'if\("([^"]+)"\)', source))
        with (work / 'daemon.log').open('wb') as log:
            process = subprocess.Popen([args.daemon, executable_path(work / 'text-macros.dmb', args.daemon),
                                        str(args.port), '-invisible', '-ultrasafe'],
                                       stdout=log, stderr=subprocess.STDOUT)
            owned = False
            try:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError((work / 'daemon.log').read_text(errors='replace'))
                    try:
                        if topic('?probe-id') == identity:
                            owned = True
                            break
                    except OSError:
                        pass
                    time.sleep(.1)
                if not owned:
                    raise TimeoutError('Probe world did not become ready')
                version = topic('?probe-version').decode('ascii')
                checks = 0
                for line in (root / 'text-vectors.tsv').read_text().splitlines():
                    if line.startswith('#'):
                        continue
                    name, encoded, expected = line.split('\t')
                    if name not in labels:
                        continue
                    raw = topic('?' + name)
                    if normalize_refs(raw) != normalize_refs(bytes.fromhex(encoded)):
                        raise AssertionError(f'{name}: wire bytes changed: {raw.hex()}')
                    if normalize_refs(decode_text(raw).encode()) != normalize_refs(bytes.fromhex(expected)):
                        raise AssertionError(f'{name}: decoded text changed')
                    checks += 1
                if checks != len(labels):
                    raise AssertionError('Missing live macro vectors')
                print(f'BYOND {version}: {checks} live macro vectors passed')
            finally:
                try:
                    if owned and process.poll() is None and topic('?probe-id') == identity:
                        topic('?shutdown')
                finally:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)


if __name__ == '__main__':
    main()
