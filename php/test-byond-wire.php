<?php
// Built-in streams and subprocesses only: php php/test-byond-wire.php.
$script = __DIR__ . '/byond-wire.php';
$checks = 0;
function check($condition, $message) {
    global $checks;
    ++$checks;
    if (!$condition) throw new RuntimeException($message);
}
function frame($body) {
    return "\0\x83" . pack('n', strlen($body)) . $body;
}
function invoke($args, $code = null) {
    global $script;
    $command = $code === null ? [PHP_BINARY, $script, ...$args]
                             : [PHP_BINARY, '-r', $code, ...$args];
    $process = proc_open($command, [0 => ['pipe', 'r'], 1 => ['pipe', 'w'],
                                  2 => ['pipe', 'w']], $pipes);
    fclose($pipes[0]);
    return [$process, $pipes];
}
function result($process, $pipes) {
    $out = stream_get_contents($pipes[1]);
    $err = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    return [proc_close($process), $out, $err];
}
function exchange($query, $reply, $output = '', $exit = 0, $fragment = false,
                  $code = null, $delay = 0) {
    $listener = stream_socket_server('tcp://127.0.0.1:0', $errno, $error);
    $address = stream_socket_get_name($listener, false);
    $port = substr($address, strrpos($address, ':') + 1);
    [$process, $pipes] = invoke(['127.0.0.1', $port, $query], $code);
    $peer = stream_socket_accept($listener, 2);
    check($peer !== false, 'Client did not connect');
    stream_set_timeout($peer, 2);
    $request = '';
    $size = 4;
    while (strlen($request) < $size) {
        $chunk = fread($peer, $size - strlen($request));
        check($chunk !== false && $chunk !== '', 'Incomplete request');
        $request .= $chunk;
        if (strlen($request) === 4) $size += unpack('n', substr($request, 2))[1];
    }
    $normalized = str_starts_with($query, '?') ? $query : '?' . $query;
    check($request === frame(str_repeat("\0", 5) . $normalized . "\0"),
          'Incorrect request bytes');
    if ($query === 'status') check(substr($request, 0, 9) === hex2bin('0083000d0000000000'),
                                   'Incorrect canonical header');
    $start = hrtime(true);
    foreach ($fragment ? str_split($reply) : [$reply] as $chunk) {
        if ($delay) usleep($delay);
        if ($chunk !== '' && @fwrite($peer, $chunk) === false) break;
    }
    // Keep complete frames connected: clients must finish by length, not EOF.
    $complete = strlen($reply) >= 4 &&
                strlen($reply) >= 4 + unpack('n', substr($reply, 2, 2))[1];
    if (!$delay && !$complete) {
        fclose($peer);
        $peer = null;
    }
    [$status, $out, $err] = result($process, $pipes);
    if (is_resource($peer)) fclose($peer);
    fclose($listener);
    check($status === $exit, "Exit $status, expected $exit: $err");
    check($out === $output, 'Unexpected stdout');
    check($exit === 0 || $exit === 2 ? $err === '' : $err !== '', 'Unexpected stderr');
    return (hrtime(true) - $start) / 1e9;
}

try {
    check(is_file($script), 'PHP implementation is missing');
    exchange('status', hex2bin('0083000406686900'), 'hi');
    foreach ([['?', "\x06\0", '', 0], ['status', "\0", '', 2],
              ['status', "\x06ab\n\\\xff\0\n\0", "ab\n\\\xff\0\n", 0],
              ['status', hex2bin('2a0000803f'), '1', 0],
              ['status', hex2bin('2a00000000'), '0', 0],
              ['status', hex2bin('2a000020c0'), '-2.5', 0],
              ['status', "\x06" . str_repeat('x', 65533) . "\0", str_repeat('x', 65533), 0]] as [$query, $body, $out, $exit]) {
        exchange($query, frame($body), $out, $exit);
    }
    foreach (['?status', '??status', '', 'café',
              'status\'; printf MARKER; #$(id)`id`\\n\\c',
              str_repeat('x', 280), str_repeat('x', 65528), '?' . str_repeat('x', 65528)] as $query) {
        exchange($query, frame("\0"), '', 2);
    }
    foreach (['', "\0\x83\0", "\xff\xff\0\1\0", frame(''), frame("\x06"),
              frame("\x06ab"), frame("\x07"), frame("\0\0"), frame("\x2a\0"),
              "\0\x83\0\x0a\x06abc"] as $reply) {
        exchange('status', $reply, '', 1);
    }
    check(exchange('status', frame("\x06hello\0"), 'hello', 0, true, null, 3000) < 1,
          'Client waited for EOF');
    foreach ([[], ['host'], ['', '4999', 'status'], ['127.0.0.1', '0', 'status'],
              ['127.0.0.1', '65536', 'status'], ['127.0.0.1', 'x', 'status'],
              ['127.0.0.1', '1', str_repeat('x', 65529)],
              ['127.0.0.1', '1', str_repeat('é', 32765)]] as $args) {
        [$status, $out, $err] = result(...invoke($args));
        check($status === 1 && $out === '' && $err !== '', 'Invalid arguments accepted');
    }
    // Bound but not listening: deterministic connection refusal.
    $reserved = stream_socket_server('tcp://127.0.0.1:0', $errno, $error, STREAM_SERVER_BIND);
    $address = stream_socket_get_name($reserved, false);
    [$status, $out, $err] = result(...invoke(['127.0.0.1', substr(strrchr($address, ':'), 1), 'status']));
    fclose($reserved);
    check($status === 1 && $out === '' && $err !== '', 'Connection refusal not reported');
    $include = 'require ' . var_export($script, true) . ';';
    [$status, $out, $err] = result(...invoke([], 'namespace Byond;
        function stream_socket_client(...$args) { throw new \\LogicException("Socket opened"); }
        ' . $include . '
        foreach (["topic", "topic_raw"] as $name) {
            foreach ([NAN, INF, -INF, 0, -1, 2147483648, 1e100, PHP_FLOAT_MAX] as $timeout) {
                try { $call = "Byond\\\\" . $name; $call("127.0.0.1", 1, "status", $timeout); exit(3); }
                catch (\\InvalidArgumentException $e) {}
            }
        }'));
    check($status === 0 && $out === '' && $err === '', 'Invalid timeout reached socket creation');
    exchange('status', frame("\x06ok\0"), 'ok', 0, false,
        $include . 'echo \\Byond\\topic($argv[1], (int)$argv[2], $argv[3], 2147483647);');
    [$status, $out, $err] = result(...invoke([], $include . '
        try { \Byond\topic("127.0.0.1", 1, "status\0ignored"); exit(3); }
        catch (InvalidArgumentException $e) { exit(0); }'));
    check($status === 0 && $out === '' && $err === '', 'Embedded NUL not rejected by API');
    foreach ([["\x06\xff\0", "\xff"], ["\x06\0", ''], ["\0", null],
              [hex2bin('2a000020c0'), -2.5]] as [$body, $expected]) {
        $code = $include . '$value = \\Byond\\topic_raw($argv[1], (int)$argv[2], $argv[3]);'
              . 'if ($value !== ' . var_export($expected, true) . ') exit(3);';
        exchange('status', frame($body), '', 0, true, $code);
    }
    foreach ([["\x06\xff\x16caf\xc3\xa9\0", 'café'], ["\x06\0", ''], ["\0", null],
              [hex2bin('2a000020c0'), -2.5]] as [$body, $expected]) {
        $defaultText = $include . '$value = \\Byond\\topic($argv[1], (int)$argv[2], $argv[3]);'
            . 'if ($value !== ' . var_export($expected, true) . ') exit(3);';
        exchange('status', frame($body), '', 0, true, $defaultText);
    }
    foreach (["\xff", "\xff\x1b", "\xc3\xff\x15\xa9"] as $text) {
        $decodeError = $include . '
            try { \\Byond\\topic($argv[1], (int)$argv[2], $argv[3]); exit(3); }
            catch (InvalidArgumentException $e) { fwrite(STDERR, $e->getMessage()); exit(1); }';
        exchange('status', frame("\x06" . $text . "\0"), '', 1, true, $decodeError);
    }
    $deadline = $include . '
        try { \Byond\topic($argv[1], (int)$argv[2], $argv[3], .12); exit(3); }
        catch (RuntimeException $e) { fwrite(STDERR, $e->getMessage()); exit($e->getCode()); }';
    check(exchange('status', frame("\x06hello\0"), '', 124, true, $deadline, 30000) < .6,
          'Total deadline was extended by fragments');
    check(exchange('status', '', '', 124, false, null, 1) >= 4.5,
          'Default timeout was not five seconds');
    echo "$checks checks passed\n";
    require __DIR__ . '/test-text.php';
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
}
