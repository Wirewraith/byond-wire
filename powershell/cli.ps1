#Requires -Version 7.4
$ErrorActionPreference = 'Stop'
try {
    if ($args.Count -lt 3 -or $args.Count -gt 4) {
        throw 'Usage: cli.ps1 <address> <port> <message> [timeout-ms]'
    }
    Import-Module (Join-Path $PSScriptRoot 'ByondWire.psm1')
    $timeout = if ($args.Count -eq 4) { [double]::Parse($args[3], [Globalization.CultureInfo]::InvariantCulture) } else { 5000 }
    $value = Invoke-ByondTopic $args[0] ([double]::Parse($args[1], [Globalization.CultureInfo]::InvariantCulture)) $args[2] -TimeoutMilliseconds $timeout -Raw
    if ($null -eq $value) { exit 2 }
    $bytes = if ($value -is [byte[]]) { ,$value } else {
        ,[Text.Encoding]::ASCII.GetBytes($value.ToString('G9', [Globalization.CultureInfo]::InvariantCulture))
    }
    $output = [Console]::OpenStandardOutput()
    try { $output.Write($bytes, 0, $bytes.Length); $output.Flush() }
    finally { $output.Dispose() }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $errorValue = $_.Exception
    while ($errorValue.InnerException) { $errorValue = $errorValue.InnerException }
    if ($errorValue -is [TimeoutException]) { exit 124 }
    exit 1
}
