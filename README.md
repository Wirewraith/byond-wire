# BYOND Wire

Small, standalone clients for BYOND game servers.

## Examples

- Each language provides a reusable Topic library and a CLI, using standard libraries or the listed shell utilities.
- Library results are decoded strings, numbers, or null. Empty text is distinct from null; errors are returned or raised without printing or exiting.
- Default calls follow the [text encoding rules](PROTOCOL.md#text-encoding). Raw calls preserve text bytes and formatting markers. Parse application-specific fields in the caller.
- CLI stdout preserves text bytes and prints numbers without a trailing newline. Exit codes: `0` value (including empty text), `1` error, `2` null, `124` timeout.
- Shell functions return byte streams. Use `byond_decode_text` to decode them; redirect stdout to preserve NULs and trailing newlines that command substitution loses.
- Each request owns its connection and uses one deadline for connection attempts and I/O. The default is five seconds; Go and Rust require an explicit duration. Shell deadlines are fixed.
- Blocking OS DNS may outlast the deadline. Numeric addresses avoid DNS.

### Bash

Requires Bash, GNU coreutils, and standard POSIX text utilities (`grep`, `sed`, `tr`).

```sh
bash bash/cli.sh 127.0.0.1 4999 status
```

Library:

```bash
. ./bash/byond-wire.sh
if byond_topic 127.0.0.1 4999 status >response.bin; then
  byond_decode_text <response.bin
else
  code=$? # 1 error, 2 null, 124 timeout
fi
```

The function isolates shell options, variables, traps, and file descriptors from its caller.
Tests require Bash, `socat`, and GNU coreutils. Run CLI tests with
`bash bash/test-cli.sh`, both sourced-library suites with `bash bash/test-import.sh`,
and both text filters with `bash bash/test-text.sh`.
The optional socket-write regression, `python3 bash/test-write.py`, requires
Linux x86-64, Python 3, and permission to trace child processes. It checks newline
bytes in request lengths/queries, library and CLI writes, and temporary-file cleanup.

### Shell (POSIX)

Requires `nc` (netcat) and standard POSIX utilities, including `grep`, `sed`, and `tr`.

```sh
sh shell/cli.sh 127.0.0.1 4999 status
```

Library:

```sh
. ./shell/byond-wire.sh
if byond_topic 127.0.0.1 4999 status >response.bin; then
  byond_decode_text <response.bin
else
  code=$?
fi
```

Each call runs in a child shell so timeout signals and cleanup remain isolated.
Run CLI tests with `sh shell/test-cli.sh` (same test dependencies as Bash).

### Python

Requires Python 3.9 or later. Install the library and CLI with `python3 -m pip install byond-wire`.
Ports must be integers from `1` to `65535` (booleans are rejected).
Timeouts are positive numbers up to `2147483647` seconds;
invalid values raise `ValueError` before DNS or socket creation.

```sh
python3 python/cli.py 127.0.0.1 4999 status
```

Import the installed module, or copy `python/byond_wire.py` onto your Python import path:

```python
from byond_wire import topic, topic_raw

response = topic("127.0.0.1", 4999, "status", timeout=5)
# str, float, or None; failures raise exceptions, including TimeoutError.
raw = topic_raw("127.0.0.1", 4999, "status")  # bytes, float, or None
```

Run regression tests with `python3 -m unittest discover -s python`.

### Node.js

Requires Node.js 18 or later. Uses built-in modules; tests use `node:test`.
Install the library and CLI with `npm install byond-wire` (use `npm install -g byond-wire` for a global CLI).

```sh
node nodejs/byond-wire.js 127.0.0.1 4999 status
```

```js
const topic = require('byond-wire'); // Or require('./nodejs/byond-wire.js') from a checkout.

async function main() {
  const response = await topic('127.0.0.1', 4999, 'status', 5000);
  // string, number, or null; failures reject the Promise.
  const raw = await topic.raw('127.0.0.1', 4999, 'status'); // Buffer, number, or null
  return response;
}
main().catch(console.error);
```

Timeouts must be finite numbers from `1` to `2147483647` milliseconds; unsupported
values reject with `RangeError` before connecting. Expired requests reject with
`error.code === 'ETIMEDOUT'`.
Run regression tests with `node --test nodejs/test-byond-wire.js`.

### Go

```sh
go run ./go/cmd/byond-wire 127.0.0.1 4999 status
```

Install the library or CLI:

```sh
go get github.com/Wirewraith/byond-wire/go/byond
go install github.com/Wirewraith/byond-wire/go/cmd/byond-wire@latest
```

For local development, add `replace github.com/Wirewraith/byond-wire/go => /absolute/path/to/byond-wire/go` to the consuming project's `go.mod`.

```go
import (
    "github.com/Wirewraith/byond-wire/go/byond"
    "time"
)

// Inside your function:
response, err := byond.Topic("127.0.0.1", "4999", "status", 5*time.Second)
// Handle err first. On success, switch on response.Kind:
// byond.Text: response.Text (string)
// byond.Number: response.Number (float32)
// byond.Null: no payload
raw, err := byond.TopicRaw("127.0.0.1", "4999", "status", 5*time.Second)
// raw.Text is []byte when raw.Kind == byond.Text. Handle err first.
```

`DecodeText` decodes raw text separately. Timeouts must be positive; network timeout
errors implement `net.Error`. The root `go.work` supports the CLI command above.
Run regression tests with `cd go && go test ./...`.

### Rust

Uses the Rust 2021 edition. No Cargo dependencies. Add `byond-wire = "0.1"`
to your Cargo dependencies; install the CLI with `cargo install byond-wire`.

```sh
rustc --edition=2021 -O rust/cli.rs -o /tmp/byond-wire-rust
/tmp/byond-wire-rust 127.0.0.1 4999 status
```

For a Cargo consumer, add this local dependency:

```toml
[dependencies]
byond-wire = { path = "/absolute/path/to/byond-wire/rust" }
```

```rust
use byond_wire::{topic, topic_raw, Response};
use std::time::Duration;

// Inside a function returning std::io::Result<()>:
let response = topic("127.0.0.1", "4999", "status", Duration::from_secs(5))?;
match response {
    Response::Text(text) => { /* String */ }
    Response::Number(value) => { /* f32 */ }
    Response::Null => { /* successful null response */ }
}
let raw = topic_raw("127.0.0.1", "4999", "status", Duration::from_secs(5))?;
// RawResponse::Text contains Vec<u8>.
```

`decode_text` decodes raw text separately. Timeouts must be positive and fit in an
`Instant`; failures return `std::io::Error`. Socket timeouts can be `TimedOut` or
`WouldBlock`. Standalone consumers can include `rust/byond-wire.rs` as a module.
Run library and CLI tests with `cargo test --manifest-path rust/Cargo.toml`.

### PHP

Requires PHP 8 or later. Install with `composer require wirewraith/byond-wire`;
the CLI is `vendor/bin/byond-wire`.

```sh
php php/byond-wire.php 127.0.0.1 4999 status
```

```php
require_once 'vendor/autoload.php'; // Or require_once 'php/byond-wire.php' from a checkout.

$response = \Byond\topic('127.0.0.1', 4999, 'status', 5);
// Decoded string, float, or null; failures throw exceptions.
$raw = \Byond\topic_raw('127.0.0.1', 4999, 'status'); // Original binary string, float, or null
```

Functions live in the `Byond` namespace. Timeouts are positive numbers up to
`2147483647` seconds; invalid values throw `InvalidArgumentException`. Timeout
exceptions have code `124`. Run tests with `php php/test-byond-wire.php`.

### PowerShell

Requires PowerShell 7.4 or later. Install with `Install-PSResource ByondWire`
(or `Install-Module ByondWire -Scope CurrentUser`).

```sh
pwsh -NoProfile -File powershell/cli.ps1 127.0.0.1 4999 status
```

```powershell
Import-Module ByondWire # Or Import-Module ./powershell/ByondWire.psd1 from a checkout.

$response = Invoke-ByondTopic 127.0.0.1 4999 status -TimeoutMilliseconds 5000
# string, single (float32), or $null; failures throw, including TimeoutException.
$raw = Invoke-ByondTopic 127.0.0.1 4999 status -Raw
# byte[], single, or $null; empty byte arrays remain byte arrays.
$text = ConvertFrom-ByondText $raw # For byte-array responses only.
```

- Timeouts must be whole milliseconds from `1` to `2147483647`. One deadline covers address fallback, connection, and I/O; blocking OS DNS may exceed it.
- Optional fourth CLI argument: timeout in milliseconds.
- Run regression tests: `pwsh -NoProfile -File powershell/test-byond-wire.ps1`.
- Run loopback benchmarks: `pwsh -NoProfile -File powershell/test-byond-wire.ps1 -Benchmark`.
- From WSL, use Windows PowerShell 7 via `pwsh.exe`. Unsigned scripts on WSL UNC paths may require the process-only execution-policy override:

```sh
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$PWD/powershell/cli.ps1")" 127.0.0.1 4999 status
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$PWD/powershell/test-byond-wire.ps1")"
```

### C# / .NET

Requires .NET 10. No runtime package dependencies. Install the library with
`dotnet add package ByondWire`; install the CLI with `dotnet tool install -g ByondWire.Cli`.

```sh
dotnet run --project csharp/cli -- 127.0.0.1 4999 status
```

Reference the library from a consuming project:

```sh
dotnet add reference /absolute/path/to/byond-wire/csharp/ByondWire.csproj
```

```csharp
using ByondWire;

object? response = await Client.TopicAsync("127.0.0.1", 4999, "status", TimeSpan.FromSeconds(5));
// string, float, or null; failures throw exceptions, including TimeoutException.
object? raw = await Client.TopicRawAsync("127.0.0.1", 4999, "status");
// byte[], float, or null; text bytes retain formatting metadata.
```

- `Client.DecodeText(bytes)` decodes raw text separately using the [encoding rules](PROTOCOL.md#text-encoding).
- Timeouts must be from `1` to `2147483647` milliseconds. One deadline covers DNS, address fallback, connection, and I/O.
- DNS cancellation cannot stop native OS resolver work already in progress; numeric addresses avoid DNS.
- Run the package-free library and CLI regression suite: `dotnet run --project csharp/tests -c Release`.
- Run loopback benchmarks: `dotnet run --project csharp/tests -c Release -- --benchmark`.

## Releases

See [RELEASING.md](RELEASING.md) for package versions, publishing setup, and release instructions.

## Performance

See [benchmark results](PERFORMANCE.md) and [benchmark instructions](benchmarks/README.md).
