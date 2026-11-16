param([switch]$Benchmark, [string]$ModulePath)
$ErrorActionPreference = 'Stop'
$module = if ($ModulePath) { $ModulePath } else { Join-Path $PSScriptRoot 'ByondWire.psm1' }
if (!(Test-Path $module)) { throw 'PowerShell library is missing' }
if (@(Import-Module $module -Force).Count) { throw 'Import printed output' }
$script:checks = 0
function Assert($Condition, $Name) {
    if (!$Condition) { throw "FAIL: $Name" }
    $script:checks++
}
function Assert-Throws([scriptblock]$Action, [string]$Name, [type]$Type = [Exception]) {
    try { & $Action; throw "Did not throw: $Name" }
    catch {
        if ($_.Exception.Message -like 'Did not throw:*') { throw }
        $errorValue = $_.Exception
        while ($errorValue.InnerException) { $errorValue = $errorValue.InnerException }
        Assert ($errorValue -is $Type) $Name
    }
}
function Start-Fixture([byte[]]$Frame, [int]$Delay = 0, [int]$Fragment = 0, [int]$Count = 1) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $worker = [powershell]::Create()
    $null = $worker.AddScript({
        param($Listener, $Frame, $Delay, $Fragment, $Count)
        $ErrorActionPreference = 'Stop'
        for ($i = 0; $i -lt $Count; $i++) {
            $accept = $Listener.AcceptTcpClientAsync()
            if (!$accept.Wait(10000)) { throw 'Fixture accept timed out' }
            $client = $accept.GetAwaiter().GetResult()
            try {
                $stream = $client.GetStream()
                $stream.ReadTimeout = 3000
                $header = [byte[]]::new(4)
                $stream.ReadExactly($header, 0, 4)
                $body = [byte[]]::new(($header[2] * 256 + $header[3]))
                $stream.ReadExactly($body, 0, $body.Length)
                if ($Delay) { Start-Sleep -Milliseconds $Delay }
                try {
                    if ($Fragment) {
                        foreach ($b in $Frame) {
                            $stream.WriteByte($b)
                            Start-Sleep -Milliseconds $Fragment
                        }
                    } else { $stream.Write($Frame, 0, $Frame.Length) }
                } catch { }
                # Complete frames keep the server open until the client closes.
                if ($Frame.Length -lt 4 + ($Frame[2] * 256 + $Frame[3])) {
                    $client.Client.Shutdown([Net.Sockets.SocketShutdown]::Send)
                }
                try { $closed = $stream.ReadByte() -eq -1 }
                catch {
                    $cause = $_.Exception
                    while ($cause.InnerException) { $cause = $cause.InnerException }
                    if ($cause -isnot [Net.Sockets.SocketException] -or $cause.SocketErrorCode -notin @([Net.Sockets.SocketError]::ConnectionReset, [Net.Sockets.SocketError]::ConnectionAborted)) { throw }
                    $closed = $true
                }
                if ($Count -eq 1) {
                    @{ Request = [Convert]::ToHexString($header + $body); Closed = $closed }
                }
            } finally { $client.Dispose() }
        }
    }).AddArgument($listener).AddArgument($Frame).AddArgument($Delay).AddArgument($Fragment).AddArgument($Count)
    @{ Listener = $listener; Worker = $worker; Pending = $worker.BeginInvoke(); Port = $listener.LocalEndpoint.Port }
}
function Complete-Fixture($Fixture) {
    try {
        $result = $Fixture.Worker.EndInvoke($Fixture.Pending)
        if ($Fixture.Worker.HadErrors) { throw $Fixture.Worker.Streams.Error[0] }
        return $result
    } finally { $Fixture.Listener.Stop(); $Fixture.Worker.Dispose() }
}
function With-Reply([string]$Hex, [scriptblock]$Action, [int]$Delay = 0, [int]$Fragment = 0) {
    $fixture = Start-Fixture ([Convert]::FromHexString($Hex)) $Delay $Fragment
    try { & $Action $fixture.Port }
    finally {
        $capture = Complete-Fixture $fixture
        Assert $capture.Closed 'socket closed after call'
    }
}
if ($Benchmark) {
    foreach ($size in @(256, 60000)) {
        $frame = [byte[]]::new($size + 6)
        $length = $size + 2
        $frame[1] = 131
        $frame[2] = $length -shr 8
        $frame[3] = $length -band 255
        $frame[4] = 6
        [Array]::Fill[byte]($frame, 97, 5, $size)
        $message = if ($size -eq 256) { 'status' } else { 'x' * 60000 }
        $times = for ($round = 0; $round -lt 5; $round++) {
            $iterations = if ($size -eq 256) { 80 } else { 30 }
            $fixture = Start-Fixture $frame -Count ($iterations + 5)
            try {
                $watch = [Diagnostics.Stopwatch]::new()
                for ($i = 0; $i -lt $iterations + 5; $i++) {
                    if ($i -eq 5) { $watch.Start() }
                    $value = Invoke-ByondTopic '127.0.0.1' $fixture.Port $message
                    if ($value -isnot [string] -or $value.Length -ne $size) { throw 'Benchmark result mismatch' }
                }
                $watch.Stop()
                $watch.Elapsed.TotalMilliseconds / $iterations
            } finally { $null = Complete-Fixture $fixture }
        }
        $median = ($times | Sort-Object)[2]
        '{0} bytes: median {1:F3} ms/request; rounds {2}' -f $size, $median, (($times | ForEach-Object { '{0:F3}' -f $_ }) -join ', ')
    }
    return
}
$vectors = 0
$vectorPath = Join-Path $PSScriptRoot '../tests/text-vectors.tsv'
if (!(Test-Path $vectorPath)) { $vectorPath = Join-Path $PSScriptRoot 'tests/text-vectors.tsv' }
foreach ($line in [IO.File]::ReadLines($vectorPath)) {
    if ($line.StartsWith('#')) { continue }
    $name, $hex, $expected = $line.Split("`t")
    foreach ($prefixCount in @(0, 16)) {
        $prefix = [byte[]]::new($prefixCount * 2)
        for ($i = 0; $i -lt $prefix.Length; $i += 2) { $prefix[$i] = 255; $prefix[$i + 1] = 21 }
        $bytes = [byte[]]($prefix + [Convert]::FromHexString($hex))
        if ($expected -eq '-') {
            Assert-Throws { ConvertFrom-ByondText $bytes } "decoder rejects $name"
        } else {
            $value = ConvertFrom-ByondText $bytes
            Assert ($value -is [string]) "string result $name"
            Assert ([Convert]::ToHexString([Text.Encoding]::UTF8.GetBytes($value)) -eq $expected) "decode $name"
        }
    }
    $vectors++
}
With-Reply '0083000906ff15636166c3a900' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status'
    Assert ($value -is [string] -and $value -ceq 'café') 'native decoded string'
} -Fragment 1
With-Reply '008300020600' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port ''
    Assert ($value -is [string] -and $value.Length -eq 0) 'empty text distinct from null'
}
With-Reply '008300020600' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status' -Raw
    Assert ($value -is [byte[]] -and $value.Length -eq 0) 'empty raw byte array'
}
With-Reply '00830003066100' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status' -Raw
    Assert ($value -is [byte[]] -and $value.Length -eq 1 -and $value[0] -eq 97) 'single raw byte array'
}
With-Reply '008300052a00000000' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status'
    Assert ($value -is [single] -and $value -eq 0) 'numeric zero distinct from null'
}
# Largest encodable request and reply; verifies 16-bit lengths and bulk copies.
$frame = [byte[]]::new(65539)
$frame[1] = 131; $frame[2] = 255; $frame[3] = 255; $frame[4] = 6
[Array]::Fill[byte]($frame, 97, 5, 65533)
$fixture = Start-Fixture $frame
try {
    $value = Invoke-ByondTopic '127.0.0.1' $fixture.Port ('x' * 65528)
    Assert ($value -is [string] -and $value.Length -eq 65533 -and $value -ceq ('a' * 65533)) 'maximum response text'
} finally { $capture = Complete-Fixture $fixture }
Assert ($capture.Request.Length -eq 131078 -and $capture.Request.StartsWith('0083FFFF00000000003F') -and $capture.Request.EndsWith('00')) 'maximum request bytes'
Assert $capture.Closed 'maximum exchange closes socket'
With-Reply '0083000100' {
    param($port)
    Assert ($null -eq (Invoke-ByondTopic '127.0.0.1' $port 'status')) 'successful null'
}
With-Reply '008300052a0000a03f' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status'
    Assert ($value -is [single] -and $value -eq 1.25) 'little endian native float'
}
With-Reply '0083000506ff008000' {
    param($port)
    $value = Invoke-ByondTopic '127.0.0.1' $port 'status' -Raw
    Assert ($value -is [byte[]] -and [Convert]::ToHexString($value) -eq 'FF0080') 'raw invalid UTF8 preserved'
}
With-Reply '0083000506c3ff1500' {
    param($port)
    Assert-Throws { Invoke-ByondTopic '127.0.0.1' $port 'status' } 'strict SDK decode failure'
}
foreach ($hex in @('0000000100', '00830000', '0083000106', '008300020601', '008300020001', '008300022a00', '0083000107', '008300040661')) {
    With-Reply $hex { param($port) Assert-Throws { Invoke-ByondTopic '127.0.0.1' $port 'status' } "invalid frame $hex" }
}
With-Reply '0083000100' {
    param($port)
    Assert-Throws { Invoke-ByondTopic '127.0.0.1' $port 'status' -TimeoutMilliseconds 50 } 'request timeout' ([TimeoutException])
} -Delay 200
With-Reply '0083000100' {
    param($port)
    Assert-Throws { Invoke-ByondTopic '127.0.0.1' $port 'status' -TimeoutMilliseconds 100 } 'single deadline across fragmented reads' ([TimeoutException])
} -Fragment 40
$fixture = Start-Fixture ([Convert]::FromHexString('0083000100'))
try { $null = Invoke-ByondTopic 'localhost' $fixture.Port 'café' }
finally { $capture = Complete-Fixture $fixture }
Assert ($capture.Request -eq '0083000C00000000003F636166C3A900') 'UTF8 byte length, prefix, terminator and hostname fallback'
$fixture = Start-Fixture ([Convert]::FromHexString('0083000100'))
try { $null = Invoke-ByondTopic '127.0.0.1' $fixture.Port '?status' }
finally { $capture = Complete-Fixture $fixture }
Assert ($capture.Request -eq '0083000D00000000003F73746174757300') 'canonical request preserves leading question mark'

foreach ($timeout in @(0, -1, 2147483648, [double]::NaN, [double]::PositiveInfinity, 1.5)) {
    Assert-Throws { Invoke-ByondTopic '127.0.0.1' 1 'status' -TimeoutMilliseconds $timeout } "invalid timeout $timeout" ([ArgumentException])
}
foreach ($bad in @(@('', 1, 'status'), @('127.0.0.1', 0, 'status'), @('127.0.0.1', 65536, 'status'), @('127.0.0.1', 1, "a`0b"), @('127.0.0.1', 1, ('x' * 65529)))) {
    Assert-Throws { Invoke-ByondTopic $bad[0] $bad[1] $bad[2] } 'invalid input rejected before connecting' ([ArgumentException])
}
function Run-Cli([string[]]$Arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new((Join-Path $PSHOME 'pwsh.exe'))
    if (!$IsWindows) { $start.FileName = Join-Path $PSHOME 'pwsh' }
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($arg in (@('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'cli.ps1')) + $Arguments)) { $start.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::Start($start)
    try {
        $output = [IO.MemoryStream]::new()
        $copy = $process.StandardOutput.BaseStream.CopyToAsync($output)
        $stderr = $process.StandardError.ReadToEndAsync()
        if (!$process.WaitForExit(10000)) {
            $process.Kill($true)
            throw 'CLI process timed out'
        }
        $null = $copy.GetAwaiter().GetResult()
        @{ Code = $process.ExitCode; Bytes = $output.ToArray(); Error = $stderr.GetAwaiter().GetResult() }
    } finally { $output.Dispose(); $process.Dispose() }
}
foreach ($case in @(
    @('0083000606ff15610a00', 'FF15610A', 0),
    @('008300020600', '', 0),
    @('0083000100', '', 2),
    @('008300052a0000a03f', '312E3235', 0),
    @('0083000107', '', 1)
)) {
    With-Reply $case[0] {
        param($port)
        $result = Run-Cli @('127.0.0.1', "$port", 'status')
        Assert ($result.Code -eq $case[2]) 'CLI exit status'
        Assert ([Convert]::ToHexString($result.Bytes) -eq $case[1]) 'CLI exact stdout'
        Assert (($result.Error.Length -gt 0) -eq ($case[2] -eq 1)) 'CLI stderr'
    }
}
With-Reply '0083000100' {
    param($port)
    $result = Run-Cli @('127.0.0.1', "$port", 'status', '50')
    Assert ($result.Code -eq 124 -and $result.Bytes.Length -eq 0 -and $result.Error.Length -gt 0) 'CLI timeout status'
} -Delay 200
$result = Run-Cli @()
Assert ($result.Code -eq 1 -and $result.Bytes.Length -eq 0 -and $result.Error.Length -gt 0) 'CLI usage error'
"PASS: $checks checks; $vectors shared text vectors"
