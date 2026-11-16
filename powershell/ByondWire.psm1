#Requires -Version 7.4
$script:Utf8 = [Text.UTF8Encoding]::new($false, $true)

$script:MarkerRegex = [regex]::new('\xFF[\x06-\x09\x12\x15-\x19\x1F-\x26]')

function ConvertFrom-ByondText {
    param([AllowEmptyCollection()][byte[]]$Bytes)
    $i = [Array]::IndexOf[byte]($Bytes, 255)
    if ($i -lt 0) { return $script:Utf8.GetString($Bytes) }
    $text = [Text.StringBuilder]::new()
    $start = 0
    $markers = 0
    do {
        $null = $text.Append($script:Utf8.GetString($Bytes, $start, $i - $start))
        $i++
        if ($i -eq $Bytes.Length -or $Bytes[$i] -notin @(6,7,8,9,18,21,22,23,24,25,31,32,33,34,35,36,37,38)) {
            throw [FormatException]::new('Unknown or truncated BYOND text marker')
        }
        $start = $i + 1
        $i = [Array]::IndexOf[byte]($Bytes, 255, $start)
        if (++$markers -eq 8 -and $i -ge 0) {
            $binary = [Text.Encoding]::Latin1.GetString($Bytes)
            $clean = $script:MarkerRegex.Replace($binary, '')
            if ($clean.IndexOf([char]255) -ge 0) { throw [FormatException]::new('Unknown or truncated BYOND text marker') }
            # ASCII separators prevent broken UTF-8 fragments from joining across markers.
            $null = $script:Utf8.GetCharCount([Text.Encoding]::Latin1.GetBytes($binary.Replace([char]255, [char]0)))
            return $script:Utf8.GetString([Text.Encoding]::Latin1.GetBytes($clean))
        }
    } while ($i -ge 0)
    $null = $text.Append($script:Utf8.GetString($Bytes, $start, $Bytes.Length - $start))
    return $text.ToString()
}

function Read-ByondBytes($Stream, [int]$Count, $Cancellation) {
    $bytes = [byte[]]::new($Count)
    $offset = 0
    while ($offset -lt $Count) {
        $read = $Stream.ReadAsync($bytes, $offset, $Count - $offset, $Cancellation.Token).GetAwaiter().GetResult()
        if (!$read) { throw [IO.EndOfStreamException]::new('Incomplete Topic response') }
        $offset += $read
    }
    return ,$bytes
}

function Invoke-ByondTopic {
    param(
        [string]$Address,
        [double]$Port,
        [AllowEmptyString()][string]$Message,
        [double]$TimeoutMilliseconds = 5000,
        [switch]$Raw
    )
    if ([string]::IsNullOrWhiteSpace($Address) -or $Port -lt 1 -or $Port -gt 65535 -or $Port % 1 -ne 0) {
        throw [ArgumentException]::new('Invalid address or port')
    }
    if ($TimeoutMilliseconds -lt 1 -or $TimeoutMilliseconds -gt [int]::MaxValue -or $TimeoutMilliseconds % 1 -ne 0) {
        throw [ArgumentException]::new('Timeout must be 1..2147483647 whole milliseconds')
    }
    if (!$Message.StartsWith('?')) { $Message = '?' + $Message }
    $query = $script:Utf8.GetBytes($Message)
    $length = $query.Length + 6
    if ($length -gt 65535 -or $Message.Contains([char]0)) {
        throw [ArgumentException]::new('Query contains NUL or exceeds 65535 frame bytes')
    }
    $request = [byte[]]::new($length + 4)
    $request[1] = 131
    $request[2] = $length -shr 8
    $request[3] = $length -band 255
    $query.CopyTo($request, 9)
    $cancellation = [Threading.CancellationTokenSource]::new([int]$TimeoutMilliseconds)
    $client = $null
    try {
        # Blocking OS DNS may exceed the deadline.
        $addresses = [Net.Dns]::GetHostAddresses($Address)
        $failure = $null
        foreach ($ip in $addresses) {
            $cancellation.Token.ThrowIfCancellationRequested()
            $client = [Net.Sockets.TcpClient]::new($ip.AddressFamily)
            try {
                $null = $client.ConnectAsync($ip, [int]$Port, $cancellation.Token).AsTask().GetAwaiter().GetResult()
                break
            } catch {
                $failure = $_.Exception
                $client.Dispose()
                $client = $null
            }
        }
        $cancellation.Token.ThrowIfCancellationRequested()
        if (!$client) { throw ($failure ?? [IO.IOException]::new('No resolved endpoints')) }
        $stream = $client.GetStream()
        $null = $stream.WriteAsync($request, 0, $request.Length, $cancellation.Token).GetAwaiter().GetResult()
        $header = Read-ByondBytes $stream 4 $cancellation
        $length = [int]$header[2] * 256 + $header[3]
        if ($header[0] -ne 0 -or $header[1] -ne 131 -or !$length) {
            throw [FormatException]::new('Invalid Topic header')
        }
        $body = Read-ByondBytes $stream $length $cancellation
        if ($body[0] -eq 0 -and $length -eq 1) { return $null }
        if ($body[0] -eq 6 -and $length -ge 2 -and $body[-1] -eq 0) {
            $bytes = [byte[]]::new($length - 2)
            [Array]::Copy($body, 1, $bytes, 0, $bytes.Length)
            if ($Raw) { return ,$bytes }
            return ConvertFrom-ByondText $bytes
        }
        if ($body[0] -eq 42 -and $length -eq 5) {
            if (![BitConverter]::IsLittleEndian) { [Array]::Reverse($body, 1, 4) }
            return [BitConverter]::ToSingle($body, 1)
        }
        throw [FormatException]::new('Invalid Topic response')
    } catch {
        if ($cancellation.IsCancellationRequested) { throw [TimeoutException]::new('Topic request timed out') }
        throw
    } finally {
        if ($client) { $client.Dispose() }
        $cancellation.Dispose()
    }
}

Export-ModuleMember -Function Invoke-ByondTopic, ConvertFrom-ByondText
