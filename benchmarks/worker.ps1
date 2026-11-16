#Requires -Version 7.4
param([string]$HostName, [int]$Port)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../powershell/ByondWire.psm1')
$culture = [Globalization.CultureInfo]::InvariantCulture
while ($null -ne ($line = [Console]::ReadLine())) {
    $fields = $line.Split("`t")
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $value = Invoke-ByondTopic $HostName $Port $fields[1] -Raw:($fields[0] -eq 'raw')
        $watch.Stop()
        $kind = if ($null -eq $value) { 'null' } elseif ($value -is [single]) { 'number' } else { 'text' }
        if ($kind -eq 'text' -and $(if ($fields[0] -eq 'raw') { $value -isnot [byte[]] } else { $value -isnot [string] })) { throw 'Incorrect native text type' }
        $size = if ($kind -eq 'null') { 0 } elseif ($kind -eq 'number') { 4 } elseif ($value -is [byte[]]) { $value.Length } else { [Text.Encoding]::UTF8.GetByteCount($value) }
        [Console]::WriteLine("$($watch.Elapsed.TotalMilliseconds.ToString($culture))`t$kind`t$size")
    } catch {
        $watch.Stop()
        [Console]::WriteLine("$($watch.Elapsed.TotalMilliseconds.ToString($culture))`terror`t$($_.Exception.Message.Replace("`n", ' ').Replace("`r", ' '))")
    }
}
