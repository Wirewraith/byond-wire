<?php
require_once __DIR__ . '/byond-wire.php';
$checks = 0;
foreach (file(__DIR__ . '/../tests/text-vectors.tsv', FILE_IGNORE_NEW_LINES) as $line) {
    if (str_starts_with($line, '#')) continue;
    [$name, $hex, $expected] = explode("\t", $line);
    foreach (['', str_repeat("\xff\x15", 16)] as $prefix) {
        try {
            $value = \Byond\decode_text($prefix . hex2bin($hex));
            if ($expected === '-' || $value !== hex2bin($expected)) throw new Exception("Wrong decoded text: $name");
        } catch (InvalidArgumentException $error) {
            if ($expected !== '-') throw $error;
        }
        ++$checks;
    }
}
if (\Byond\decode_text(str_repeat('x', 65533)) !== str_repeat('x', 65533)) throw new Exception('Large response failed');
echo "$checks text vector checks passed\n";
