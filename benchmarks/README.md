# Running benchmarks

Run commands from the repository root. See [PERFORMANCE.md](../PERFORMANCE.md) for measured results.

- Run `python3 benchmarks/run.py` to regenerate the tables and [individual samples](results.json). Defaults: 20 measured rounds, one warmup round, five-second request deadlines, and a 250 ms pause after every request. Requests are sequential; a complete run sends about 1,900 requests and takes roughly 15 minutes on a 200 ms network path.
- Use `--samples 1 --warmups 0` for a pilot; p95 requires 20 successful samples per cell. Increase `--samples` for more stable tail estimates. Set `--location 'your network location'` to identify the measurement path.
- Optional: `--host`, `--port`, `--pause`, `--only Python Go Rust`, `--output results.json`, and `--report summary.md`. Partial JSON is saved after each round; an interrupted run leaves the previous Markdown report intact.
- Requires Python 3 and each implementation's documented runtime/utilities. Missing runtimes and build failures are reported as unavailable. Shell benchmarking additionally requires GNU `date`, `mktemp`, `wc`, and POSIX `awk`. Compiled adapters and CLIs use temporary release builds; build time is excluded. On WSL, Windows `pwsh.exe` is supported and labeled separately.
- Run benchmark regression tests with `python3 -m unittest discover -s benchmarks`; they use loopback fixtures and the shared text vectors, without contacting the remote server.
