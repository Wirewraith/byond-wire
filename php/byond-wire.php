<?php
namespace Byond;

use InvalidArgumentException;
use RuntimeException;
use Throwable;
// PHP 8+, built-ins only. Exit: 0 value, 1 error, 2 null, 124 timeout.
// Remove tested BYOND markers and validate UTF-8. HTML remains intact.
function decode_text(string $data): string {
    if (!str_contains($data, "\xff")) {
        if (preg_match('//u', $data) !== 1) throw new InvalidArgumentException('Invalid UTF-8 text');
        return $data;
    }
    // ASCII separators prevent broken UTF-8 fragments from joining across markers.
    if (preg_match('//u', str_replace("\xff", "\0", $data)) !== 1)
        throw new InvalidArgumentException('Invalid UTF-8 text');
    $text = preg_replace('/\xff[\x06-\x09\x12\x15-\x19\x1f-\x26]/', '', $data);
    if (str_contains($text, "\xff")) throw new InvalidArgumentException('Unknown or truncated BYOND text marker');
    return $text;
}

function topic_timeout(float $deadline): float {
    $seconds = $deadline - hrtime(true) / 1e9;
    if ($seconds <= 0) throw new RuntimeException('Topic request timed out', 124);
    return $seconds;
}

function topic_prepare($socket, float $deadline): void {
    $seconds = topic_timeout($deadline);
    $whole = (int)$seconds;
    stream_set_timeout($socket, $whole, max(1, (int)(($seconds - $whole) * 1e6)));
}

function topic_read($socket, int $count, float $deadline): string {
    $result = '';
    while ($count > 0) {
        topic_prepare($socket, $deadline);
        $chunk = @fread($socket, $count);
        if (stream_get_meta_data($socket)['timed_out'])
            throw new RuntimeException('Topic request timed out', 124);
        topic_timeout($deadline);
        if ($chunk === false || $chunk === '')
            throw new RuntimeException('Incomplete Topic response');
        $result .= $chunk;
        $count -= strlen($chunk);
    }
    return $result;
}

function topic(string $host, int $port, string $query, float $timeout = 5): string|float|null {
    $value = topic_raw($host, $port, $query, $timeout);
    return is_string($value) ? decode_text($value) : $value;
}

function topic_raw(string $host, int $port, string $query, float $timeout = 5): string|float|null {
    if ($host === '' || str_contains($host, "\0") || $port < 1 || $port > 65535)
        throw new InvalidArgumentException('Invalid address or port');
    if (!is_finite($timeout) || $timeout <= 0 || $timeout > 2147483647)
        throw new InvalidArgumentException('Timeout must be positive and at most 2147483647 seconds');
    if (!str_starts_with($query, '?')) $query = '?' . $query;
    if (str_contains($query, "\0")) throw new InvalidArgumentException('Query contains NUL');
    $length = strlen($query) + 6;
    if ($length > 65535) throw new InvalidArgumentException('Query exceeds two-byte frame length');
    $request = pack('nnx5', 0x83, $length) . $query . "\0";
    $deadline = hrtime(true) / 1e9 + $timeout;
    if (str_contains($host, ':') && $host[0] !== '[') $host = '[' . $host . ']';
    $socket = @stream_socket_client("tcp://$host:$port", $errno, $error, topic_timeout($deadline));
    if ($socket === false) {
        topic_timeout($deadline);
        throw new RuntimeException($error ?: 'Connection failed');
    }
    try {
        $offset = 0;
        while ($offset < strlen($request)) {
            topic_prepare($socket, $deadline);
            $sent = @fwrite($socket, substr($request, $offset));
            if (stream_get_meta_data($socket)['timed_out'])
                throw new RuntimeException('Topic request timed out', 124);
            topic_timeout($deadline);
            if ($sent === false || $sent === 0) throw new RuntimeException('Incomplete Topic request');
            $offset += $sent;
        }
        $header = topic_read($socket, 4, $deadline);
        if (substr($header, 0, 2) !== "\0\x83") throw new RuntimeException('Non-Topic response');
        $length = unpack('n', substr($header, 2))[1];
        if (!$length) throw new RuntimeException('Empty Topic body');
        $body = topic_read($socket, $length, $deadline);
    } finally {
        fclose($socket);
    }
    if ($body === "\0") return null;
    if ($body[0] === "\x06" && $length >= 2 && $body[$length - 1] === "\0")
        return substr($body, 1, -1);
    if ($body[0] === "\x2a" && $length === 5) return unpack('g', substr($body, 1))[1];
    throw new RuntimeException('Invalid Topic response');
}

function main(array $args): int {
    try {
        if (count($args) !== 4) throw new InvalidArgumentException("Usage: $args[0] <address> <port> <message>");
        if ($args[2] === '' || strspn($args[2], '0123456789') !== strlen($args[2])) throw new InvalidArgumentException('Invalid port');
        $value = topic_raw($args[1], (int)$args[2], $args[3]);
        if ($value === null) return 2;
        echo is_float($value) ? sprintf('%.9g', $value) : $value;
        return 0;
    } catch (Throwable $error) {
        fwrite(STDERR, $error->getMessage() . "\n");
        return $error->getCode() === 124 ? 124 : 1;
    }
}

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) exit(main($argv));
