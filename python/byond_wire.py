#!/usr/bin/env python3
"""Standard library only. Exit: 0 value, 1 error, 2 null, 124 network timeout."""
import socket
import struct
import sys
import time


def decode_text(data):
    """Remove tested BYOND markers and strictly decode the UTF-8 runs."""
    if b'\xff' not in data:
        return data.decode('utf-8')
    parts = data.split(b'\xff')
    text = [parts[0].decode('utf-8')]
    for part in parts[1:]:
        if not part or part[0] not in b'\x06\x07\x08\x09\x12\x15\x16\x17\x18\x19\x1f\x20\x21\x22\x23\x24\x25\x26':
            raise ValueError('Unknown or truncated BYOND text marker')
        text.append(part[1:].decode('utf-8'))
    return ''.join(text)


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('Topic request timed out')
    return seconds


def read_exact(sock, count, deadline):
    chunks = []
    while count:
        sock.settimeout(remaining(deadline))
        chunk = sock.recv(count)
        if not chunk:
            raise EOFError('Incomplete Topic response')
        chunks.append(chunk)
        count -= len(chunk)
    return b''.join(chunks)


def connect(host, port, deadline):
    remaining(deadline)
    error = None
    for family, kind, protocol, _, address in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        seconds = remaining(deadline)
        sock = None
        try:
            sock = socket.socket(family, kind, protocol)
            sock.settimeout(seconds)
            sock.connect(address)
            return sock
        except BaseException as failure:
            if sock is not None:
                sock.close()
            if not isinstance(failure, OSError):
                raise
            error = failure
    raise error or OSError('Address resolved to no endpoints')


def topic(host, port, query, timeout=5):
    value = topic_raw(host, port, query, timeout)
    return decode_text(value) if isinstance(value, bytes) else value


def topic_raw(host, port, query, timeout=5):
    if not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid address or port')
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 2147483647:
        raise ValueError('Timeout must be positive and at most 2147483647 seconds')
    if not query.startswith('?'):
        query = '?' + query
    query_bytes = query.encode('utf-8')
    if b'\0' in query_bytes:
        raise ValueError('Query contains NUL')
    length = len(query_bytes) + 6
    if length > 65535:
        raise ValueError('Query exceeds two-byte frame length')
    request = struct.pack('>HH5x', 0x83, length) + query_bytes + b'\0'
    deadline = time.monotonic() + timeout
    try:
        with connect(host, port, deadline) as sock:
            sock.settimeout(remaining(deadline))
            sock.sendall(request)
            header = read_exact(sock, 4, deadline)
            if header[:2] != b'\0\x83':
                raise ValueError('Non-Topic response')
            length = struct.unpack('>H', header[2:])[0]
            if length == 0:
                raise ValueError('Empty Topic body')
            body = read_exact(sock, length, deadline)
    except socket.timeout as error:
        raise TimeoutError('Topic request timed out') from error
    if body == b'\0':
        return None
    if body[:1] == b'\x06' and len(body) >= 2 and body.endswith(b'\0'):
        return body[1:-1]
    if body[:1] == b'\x2a' and len(body) == 5:
        return struct.unpack('<f', body[1:])[0]
    raise ValueError('Invalid Topic response')


def main():
    try:
        if len(sys.argv) != 4:
            raise ValueError(f'Usage: {sys.argv[0]} <address> <port> <message>')
        result = topic_raw(sys.argv[1], int(sys.argv[2]), sys.argv[3])
        if result is None:
            return 2
        if isinstance(result, bytes):
            sys.stdout.buffer.write(result)
        else:
            sys.stdout.buffer.write(format(result, '.9g').encode('ascii'))
        sys.stdout.buffer.flush()
        return 0
    except TimeoutError:
        print('Topic request timed out', file=sys.stderr)
        return 124
    except (OSError, ValueError, EOFError) as error:
        print(error, file=sys.stderr)
        return 1

