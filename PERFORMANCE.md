# Performance

- Target: `goondev.goonhub.com:26900`; queries are application-specific.
- Run (Linux/WSL): 2026-11-16T20:23:29.810386+00:00 to 2026-11-16T20:38:59.465507+00:00; Windows: 2026-11-16T21:23:27.4490474Z to 2026-11-16T21:25:24.5749615Z (UTC).
- Machine: Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.39; CPU: Intel(R) Core(TM) Ultra 9 185H.
- Location/network: User workstation; Linux/WSL2 and native Windows PowerShell; geographic location not supplied. Resolved addresses: 15.235.86.196.
- Revision: uncommitted checkout (no HEAD); exact source SHA-256 hashes are in the [JSON results](<benchmarks/results.json>) and [Windows metadata](powershell-windows.json).
- 20 measured rounds, 1 warmup rounds per cell; 0.25 s pause after every request, including discovery and warmup.
- Sequential requests; each owns a new TCP connection. Implementation, mode, and query order rotate between rounds. Warmup results are excluded.
- Library cells time the native API call after process startup/import. CLI cells include process startup, imports, output capture, and exit; compilation is excluded.
- Libraries use decoded strings or raw text bytes. Shell decoded calls include the separate text filter; shell raw calls return byte streams. CLI output remains raw.
- Shell library timings include temporary-file I/O and GNU date timestamp-process overhead; their text/number labels follow discovery because shell APIs return byte streams.
- Numeric/null sizes are 4/0. Text sizes count returned UTF-8 bytes in decoded mode and original text bytes in raw/CLI mode; framing and the terminator are excluded.
- Five-second library/CLI deadline; a separate 12-second watchdog covers startup and IPC. Blocking OS DNS can exceed the library deadline; the normal resolver/cache is used.
- Cells: median / p95 milliseconds. p95 uses nearest rank and requires 20 successful samples; `—` means insufficient samples. Failures are excluded from latency statistics and retained in JSON.
- Results describe this machine-to-server path and server load during the run. They do not isolate language speed. Dynamic response contents are not compared byte-for-byte.
- Native library result types and lengths are checked; CLI exit status, numeric output, and raw text decoding are checked. A type change from discovery is a failure.
- Reproduce: `python3 benchmarks/run.py` (all installed runtimes; standard libraries only). Details and every observation: [JSON results](<benchmarks/results.json>) and [Windows samples](powershell-windows.csv).

## Observed queries

| Query | Discovered type | Initial payload bytes | Note |
| --- | --- | ---: | --- |
| `status` | text | 312 |  |
| `ping` | number | 4 |  |
| `who` | text | 0 |  |
| `type=version` | number | 4 |  |

## Runtimes

| Implementation | Runtime | Execution platform |
| --- | --- | --- |
| Bash | GNU bash, version 5.2.21(1)-release (x86_64-pc-linux-gnu) | Linux |
| POSIX shell | OpenBSD netcat (Debian patchlevel 1.226-1ubuntu2) | Linux |
| Python | Python 3.12.3 | Linux |
| Node.js | v24.22.2 | Linux |
| Go | go version go1.22.2 linux/amd64 | Linux |
| Rust | rustc 1.95.0 (59807616e 2026-04-14) | Linux |
| PHP | PHP 8.5.12 (cli) (built: Oct 21 2026 14:37:30) (NTS) | Linux |
| PowerShell | 7.7.0 (.NET 11.0.0) | Windows (native) |
| C# | 10.0.403 | Linux |

## Library: decoded

| Implementation | `status` | `ping` | `who` | `type=version` |
| --- | ---: | ---: | ---: | ---: |
| Bash | 224.00 / 287.98 | 219.78 / 229.18 | 228.45 / 239.40 | 224.01 / 296.05 |
| POSIX shell | 227.10 / 241.94 | 222.35 / 232.99 | 223.47 / 239.67 | 222.01 / 230.79 |
| Python | 205.46 / 217.38 | 207.87 / 229.20 | 207.60 / 289.92 | 207.67 / 217.59 |
| Node.js | 212.38 / 222.26 | 207.09 / 215.42 | 212.04 / 243.71 | 205.86 / 215.02 |
| Go | 208.06 / 219.56 | 208.15 / 222.95 | 207.73 / 223.26 | 207.19 / 321.32 |
| Rust | 208.67 / 214.32 | 208.68 / 221.93 | 210.55 / 218.38 | 206.55 / 219.76 |
| PHP | 206.05 / 214.37 | 206.63 / 216.27 | 206.81 / 213.22 | 211.78 / 229.02 |
| PowerShell | 161.23 / 167.58 | 163.86 / 170.17 | 163.33 / 165.91 | 163.09 / 170.90 |
| C# | 208.58 / 218.07 | 208.81 / 218.78 | 209.06 / 219.17 | 209.80 / 218.39 |

| Implementation / query | Successes | Failures | Timeouts | Result bytes (min–max) |
| --- | ---: | ---: | ---: | ---: |
| Bash / `status` | 20 | 0 | 0 | 312–312 |
| Bash / `ping` | 20 | 0 | 0 | 4–4 |
| Bash / `who` | 20 | 0 | 0 | 0–0 |
| Bash / `type=version` | 20 | 0 | 0 | 4–4 |
| POSIX shell / `status` | 20 | 0 | 0 | 312–312 |
| POSIX shell / `ping` | 20 | 0 | 0 | 4–4 |
| POSIX shell / `who` | 20 | 0 | 0 | 0–0 |
| POSIX shell / `type=version` | 20 | 0 | 0 | 4–4 |
| Python / `status` | 20 | 0 | 0 | 312–312 |
| Python / `ping` | 20 | 0 | 0 | 4–4 |
| Python / `who` | 20 | 0 | 0 | 0–0 |
| Python / `type=version` | 20 | 0 | 0 | 4–4 |
| Node.js / `status` | 20 | 0 | 0 | 312–312 |
| Node.js / `ping` | 20 | 0 | 0 | 4–4 |
| Node.js / `who` | 20 | 0 | 0 | 0–0 |
| Node.js / `type=version` | 20 | 0 | 0 | 4–4 |
| Go / `status` | 20 | 0 | 0 | 312–312 |
| Go / `ping` | 20 | 0 | 0 | 4–4 |
| Go / `who` | 20 | 0 | 0 | 0–0 |
| Go / `type=version` | 20 | 0 | 0 | 4–4 |
| Rust / `status` | 20 | 0 | 0 | 312–312 |
| Rust / `ping` | 20 | 0 | 0 | 4–4 |
| Rust / `who` | 20 | 0 | 0 | 0–0 |
| Rust / `type=version` | 20 | 0 | 0 | 4–4 |
| PHP / `status` | 20 | 0 | 0 | 312–312 |
| PHP / `ping` | 20 | 0 | 0 | 4–4 |
| PHP / `who` | 20 | 0 | 0 | 0–0 |
| PHP / `type=version` | 20 | 0 | 0 | 4–4 |
| PowerShell / `status` | 20 | 0 | 0 | — |
| PowerShell / `ping` | 20 | 0 | 0 | 4–4 |
| PowerShell / `who` | 20 | 0 | 0 | — |
| PowerShell / `type=version` | 20 | 0 | 0 | 4–4 |
| C# / `status` | 20 | 0 | 0 | 312–312 |
| C# / `ping` | 20 | 0 | 0 | 4–4 |
| C# / `who` | 20 | 0 | 0 | 0–0 |
| C# / `type=version` | 20 | 0 | 0 | 4–4 |

## Library: raw text

| Implementation | `status` | `who` |
| --- | ---: | ---: |
| Bash | 220.33 / 230.89 | 219.51 / 230.19 |
| POSIX shell | 221.27 / 242.95 | 221.93 / 228.59 |
| Python | 206.02 / 221.78 | 206.36 / 211.38 |
| Node.js | 207.21 / 216.06 | 207.51 / 218.01 |
| Go | 207.49 / 218.26 | 206.19 / 212.22 |
| Rust | 206.30 / 217.25 | 209.32 / 217.20 |
| PHP | 207.54 / 219.95 | 206.97 / 217.72 |
| PowerShell | 163.51 / 169.93 | 162.80 / 171.77 |
| C# | 207.88 / 218.86 | 205.89 / 214.59 |

| Implementation / query | Successes | Failures | Timeouts | Result bytes (min–max) |
| --- | ---: | ---: | ---: | ---: |
| Bash / `status` | 20 | 0 | 0 | 312–312 |
| Bash / `who` | 20 | 0 | 0 | 0–0 |
| POSIX shell / `status` | 20 | 0 | 0 | 312–312 |
| POSIX shell / `who` | 20 | 0 | 0 | 0–0 |
| Python / `status` | 20 | 0 | 0 | 312–312 |
| Python / `who` | 20 | 0 | 0 | 0–0 |
| Node.js / `status` | 20 | 0 | 0 | 312–312 |
| Node.js / `who` | 20 | 0 | 0 | 0–0 |
| Go / `status` | 20 | 0 | 0 | 312–312 |
| Go / `who` | 20 | 0 | 0 | 0–0 |
| Rust / `status` | 20 | 0 | 0 | 312–312 |
| Rust / `who` | 20 | 0 | 0 | 0–0 |
| PHP / `status` | 20 | 0 | 0 | 312–312 |
| PHP / `who` | 20 | 0 | 0 | 0–0 |
| PowerShell / `status` | 20 | 0 | 0 | — |
| PowerShell / `who` | 20 | 0 | 0 | — |
| C# / `status` | 20 | 0 | 0 | 312–312 |
| C# / `who` | 20 | 0 | 0 | 0–0 |

## CLI

| Implementation | `status` | `ping` | `who` | `type=version` |
| --- | ---: | ---: | ---: | ---: |
| Bash | 222.63 / 242.79 | 220.68 / 234.93 | 222.62 / 283.84 | 219.16 / 230.17 |
| POSIX shell | 222.94 / 235.40 | 224.64 / 230.67 | 225.48 / 342.95 | 227.01 / 236.31 |
| Python | 232.35 / 315.74 | 231.71 / 258.10 | 230.56 / 348.72 | 231.81 / 266.29 |
| Node.js | 240.17 / 260.25 | 240.90 / 248.75 | 243.63 / 277.74 | 240.73 / 258.39 |
| Go | 210.01 / 221.15 | 214.44 / 220.91 | 209.97 / 220.52 | 211.24 / 226.20 |
| Rust | 209.86 / 216.09 | 212.80 / 216.88 | 209.55 / 223.91 | 210.89 / 227.60 |
| PHP | 235.58 / 346.68 | 232.84 / 326.53 | 232.93 / 300.32 | 235.16 / 322.25 |
| PowerShell | 502.57 / 522.79 | 505.94 / 521.32 | 497.63 / 518.18 | 497.29 / 522.46 |
| C# | 269.28 / 369.73 | 265.67 / 276.93 | 264.93 / 309.12 | 262.81 / 274.14 |

| Implementation / query | Successes | Failures | Timeouts | Result bytes (min–max) |
| --- | ---: | ---: | ---: | ---: |
| Bash / `status` | 20 | 0 | 0 | 312–312 |
| Bash / `ping` | 20 | 0 | 0 | 4–4 |
| Bash / `who` | 20 | 0 | 0 | 0–0 |
| Bash / `type=version` | 20 | 0 | 0 | 4–4 |
| POSIX shell / `status` | 20 | 0 | 0 | 312–312 |
| POSIX shell / `ping` | 20 | 0 | 0 | 4–4 |
| POSIX shell / `who` | 20 | 0 | 0 | 0–0 |
| POSIX shell / `type=version` | 20 | 0 | 0 | 4–4 |
| Python / `status` | 20 | 0 | 0 | 312–312 |
| Python / `ping` | 20 | 0 | 0 | 4–4 |
| Python / `who` | 20 | 0 | 0 | 0–0 |
| Python / `type=version` | 20 | 0 | 0 | 4–4 |
| Node.js / `status` | 20 | 0 | 0 | 312–312 |
| Node.js / `ping` | 20 | 0 | 0 | 4–4 |
| Node.js / `who` | 20 | 0 | 0 | 0–0 |
| Node.js / `type=version` | 20 | 0 | 0 | 4–4 |
| Go / `status` | 20 | 0 | 0 | 312–312 |
| Go / `ping` | 20 | 0 | 0 | 4–4 |
| Go / `who` | 20 | 0 | 0 | 0–0 |
| Go / `type=version` | 20 | 0 | 0 | 4–4 |
| Rust / `status` | 20 | 0 | 0 | 312–312 |
| Rust / `ping` | 20 | 0 | 0 | 4–4 |
| Rust / `who` | 20 | 0 | 0 | 0–0 |
| Rust / `type=version` | 20 | 0 | 0 | 4–4 |
| PHP / `status` | 20 | 0 | 0 | 312–312 |
| PHP / `ping` | 20 | 0 | 0 | 4–4 |
| PHP / `who` | 20 | 0 | 0 | 0–0 |
| PHP / `type=version` | 20 | 0 | 0 | 4–4 |
| PowerShell / `status` | 20 | 0 | 0 | — |
| PowerShell / `ping` | 20 | 0 | 0 | 4–4 |
| PowerShell / `who` | 20 | 0 | 0 | — |
| PowerShell / `type=version` | 20 | 0 | 0 | 4–4 |
| C# / `status` | 20 | 0 | 0 | 312–312 |
| C# / `ping` | 20 | 0 | 0 | 4–4 |
| C# / `who` | 20 | 0 | 0 | 0–0 |
| C# / `type=version` | 20 | 0 | 0 | 4–4 |
