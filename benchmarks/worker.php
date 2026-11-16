<?php
require __DIR__ . '/../php/byond-wire.php';
while (($line = fgets(STDIN)) !== false) {
    [$mode, $query] = explode("\t", rtrim($line, "\r\n"));
    $start = hrtime(true);
    try {
        $value = $mode === 'raw' ? \Byond\topic_raw($argv[1], (int)$argv[2], $query) : \Byond\topic($argv[1], (int)$argv[2], $query);
        $ms = (hrtime(true) - $start) / 1e6;
        $kind = $value === null ? 'null' : (is_float($value) ? 'number' : 'text');
        $size = $value === null ? 0 : (is_float($value) ? 4 : strlen($value));
        echo "$ms\t$kind\t$size\n";
    } catch (Throwable $e) {
        echo ((hrtime(true) - $start) / 1e6) . "\terror\t" . str_replace(["\r", "\n"], ' ', $e->getMessage()) . "\n";
    }
    fflush(STDOUT);
}
