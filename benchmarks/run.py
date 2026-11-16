#!/usr/bin/env python3
"""Paced, sequential remote BYOND benchmarks; standard library only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from byond_wire import decode_text, topic_raw

QUERIES = ('status', 'ping', 'who', 'type=version')
NAMES = ('Bash', 'POSIX shell', 'Python', 'Node.js', 'Go', 'Rust', 'PHP', 'PowerShell', 'C#')
MODES = ('decoded', 'raw', 'cli')
WATCHDOG = 12  # Includes IPC/process startup; library deadlines remain five seconds.


def rotate(items, round_number):
    offset = round_number % len(items) if items else 0
    return items[offset:] + items[:offset]


def summarize(samples):
    good = [s for s in samples if 'error' not in s]
    times = sorted(s['ms'] for s in good)
    sizes = [s['size'] for s in good]
    return dict(median=statistics.median(times) if times else None,
                p95=times[math.ceil(.95 * len(times)) - 1] if len(times) >= 20 else None,
                ok=len(good), failures=len(samples) - len(good),
                timeouts=sum(bool(s.get('timeout')) for s in samples),
                sizes=[min(sizes), max(sizes)] if sizes else None)


def validate_cli(code, output, expected):
    if expected == 'null':
        if code != 2 or output:
            raise ValueError('null must have exit 2 and empty stdout')
        return 0
    if code != 0:
        raise ValueError(f'exit {code}')
    if expected == 'number':
        try:
            if not output or output.strip() != output:
                raise ValueError('empty number or surrounding whitespace')
            float(output)
        except ValueError as error:
            raise ValueError('invalid numeric stdout') from error
        return 4
    decode_text(output)  # CLI text is raw, including supported formatting markers.
    return len(output)


def command(args, **kwargs):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=120, **kwargs).stdout.decode().strip()


def prepare(build, selected=None):
    """Build once; return runnable workers/CLIs and explicit unavailable reasons."""
    entries = {}
    configs = {
        'Bash': ('bash', ['bash', 'benchmarks/worker.sh', 'bash/byond-wire.sh'], ['bash', 'bash/cli.sh'], ['bash', '--version']),
        'POSIX shell': ('nc', ['sh', 'benchmarks/worker.sh', 'shell/byond-wire.sh'], ['sh', 'shell/cli.sh'], ['nc', '-h']),
        'Python': ('python3', [sys.executable, 'benchmarks/worker.py'], [sys.executable, 'python/cli.py'], [sys.executable, '--version']),
        'Node.js': ('node', ['node', 'benchmarks/worker.js'], ['node', 'nodejs/byond-wire.js'], ['node', '--version']),
        'PHP': ('php', ['php', 'benchmarks/worker.php'], ['php', 'php/byond-wire.php'], ['php', '--version']),
        'Go': ('go', [str(build / 'go-worker')], [str(build / 'go-cli')], ['go', 'version']),
        'Rust': ('rustc', [str(build / 'rust-worker')], [str(build / 'rust-cli')], ['rustc', '--version']),
        'C#': ('dotnet', ['dotnet', str(build / 'worker/Worker.dll')], ['dotnet', str(build / 'cli/ByondWire.Cli.dll')], ['dotnet', '--version']),
    }
    powershell = shutil.which('pwsh') or shutil.which('pwsh.exe')
    if powershell and (not selected or 'PowerShell' in selected):
        def ps_path(relative):
            return command(['wslpath', '-w', str(ROOT / relative)]) if powershell.endswith('.exe') else str(ROOT / relative)
        configs['PowerShell'] = (powershell,
            [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps_path('benchmarks/worker.ps1')],
            [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps_path('powershell/cli.ps1')],
            [powershell, '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'])
    for name in NAMES:
        if selected and name not in selected:
            entries[name] = {'unavailable': 'not selected'}
            continue
        config = configs.get(name)
        if not config or not shutil.which(config[0]):
            entries[name] = {'unavailable': 'runtime/tool not installed'}
            continue
        executable, worker, cli, version = config
        try:
            if name == 'Go':
                command(['go', 'build', '-trimpath', '-o', build / 'go-worker', ROOT / 'benchmarks/worker.go'])
                command(['go', 'build', '-trimpath', '-o', build / 'go-cli', ROOT / 'go/cmd/byond-wire/main.go'])
            elif name == 'Rust':
                for source, target in [('benchmarks/worker.rs', 'rust-worker'), ('rust/cli.rs', 'rust-cli')]:
                    command(['rustc', '--edition=2021', '-O', ROOT / source, '-o', build / target])
            elif name == 'C#':
                for project, target in [('benchmarks/csharp/Worker.csproj', 'worker'), ('csharp/cli/ByondWire.Cli.csproj', 'cli')]:
                    command(['dotnet', 'build', ROOT / project, '-c', 'Release', '-o', build / target, '--nologo'])
            try:
                version_text = command(version).splitlines()[0]
            except subprocess.CalledProcessError as error:
                # nc -h commonly returns 1 while still identifying itself.
                version_text = error.stdout.decode(errors='replace').splitlines()[0]
            entries[name] = dict(worker=worker, cli=cli, version=version_text,
                                 platform='Windows via WSL interop' if executable.endswith('.exe') else platform.system())
        except (OSError, subprocess.SubprocessError) as error:
            detail = error.stdout.decode(errors='replace')[-1500:] if getattr(error, 'stdout', None) else str(error)
            entries[name] = {'unavailable': detail}
    return entries


class Worker:
    def __init__(self, command_args):
        self.errors = tempfile.TemporaryFile()
        self.process = subprocess.Popen(command_args, cwd=ROOT, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.errors,
                                        start_new_session=True, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def request(self, mode, query, expected):
        self.process.stdin.write(f'{mode}\t{query}\t{expected}\n'.encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + WATCHDOG
        response = bytearray()
        while b'\n' not in response:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                self.close()
                raise TimeoutError('worker watchdog expired (includes startup/IPC)')
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 65536:
                raise ValueError('worker response exceeds 64 KiB')
        line = response.decode().strip()
        if not line:
            self.errors.seek(0)
            raise ValueError('worker exited: ' + self.errors.read(1500).decode(errors='replace'))
        elapsed, kind, payload = line.split('\t', 2)
        ms = float(elapsed)
        if not math.isfinite(ms) or ms < 0:
            raise ValueError('invalid worker timing')
        if kind == 'error':
            raise ValueError(payload)
        if kind == 'timeout':
            raise TimeoutError(payload)
        size = int(payload)
        if kind != expected or size < 0 or (kind == 'number' and size != 4) or (kind == 'null' and size != 0):
            raise ValueError(f'result mismatch: expected {expected}, got {kind}/{size}')
        return {'ms': ms, 'kind': kind, 'size': size}

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout, self.errors):
            stream.close()


def cli_request(args, expected):
    start = time.perf_counter_ns()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=errors,
                                   start_new_session=True)
        try:
            output, _ = process.communicate(timeout=WATCHDOG)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise TimeoutError('CLI watchdog expired (includes process startup)')
        ms = (time.perf_counter_ns() - start) / 1e6
        try:
            size = validate_cli(process.returncode, output, expected)
        except ValueError as error:
            errors.seek(0)
            raise ValueError(f'{error}: {errors.read(1500).decode(errors="replace")}') from error
    return {'ms': ms, 'kind': expected, 'size': size}


def report(data):
    settings = data['settings']
    results_link = f"[JSON results](<{data['results_path']}>)"
    lines = ['# Performance', '',
        f"- Target: `{settings['host']}:{settings['port']}`; queries are application-specific.",
        f"- Run: {data['started']} to {data['finished']} (UTC).",
        f"- Machine: {data['environment']['system']}; CPU: {data['environment']['cpu']}.",
        f"- Location/network: {settings['location']}. Resolved addresses: {', '.join(data['addresses']) or 'unavailable'}.",
        f"- Revision: {data['revision']}; exact source SHA-256 hashes are in the {results_link}.",
        f"- {settings['samples']} measured rounds, {settings['warmups']} warmup rounds per cell; {settings['pause']} s pause after every request, including discovery and warmup.",
        '- Sequential requests; each owns a new TCP connection. Implementation, mode, and query order rotate between rounds. Warmup results are excluded.',
        '- Library cells time the native API call after process startup/import. CLI cells include process startup, imports, output capture, and exit; compilation is excluded.',
        '- Libraries use decoded strings or raw text bytes. Shell decoded calls include the separate text filter; shell raw calls return byte streams. CLI output remains raw.',
        '- Shell library timings include temporary-file I/O and GNU date timestamp-process overhead; their text/number labels follow discovery because shell APIs return byte streams.',
        '- Numeric/null sizes are 4/0. Text sizes count returned UTF-8 bytes in decoded mode and original text bytes in raw/CLI mode; framing and the terminator are excluded.',
        '- Five-second library/CLI deadline; a separate 12-second watchdog covers startup and IPC. Blocking OS DNS can exceed the library deadline; the normal resolver/cache is used.',
        '- Cells: median / p95 milliseconds. p95 uses nearest rank and requires 20 successful samples; `—` means insufficient samples. Failures are excluded from latency statistics and retained in JSON.',
        '- Results describe this machine-to-server path and server load during the run. They do not isolate language speed. Dynamic response contents are not compared byte-for-byte.',
        '- Native library result types and lengths are checked; CLI exit status, numeric output, and raw text decoding are checked. A type change from discovery is a failure.',
        f'- Reproduce: `python3 benchmarks/run.py` (all installed runtimes; standard libraries only). Details and every observation: {results_link}.', '',
        '## Observed queries', '', '| Query | Discovered type | Initial payload bytes | Note |', '| --- | --- | ---: | --- |']
    for query, discovery in data['queries'].items():
        lines.append(f"| `{query}` | {discovery.get('kind', 'unavailable')} | {discovery.get('size', '—')} | {discovery.get('error', '').replace('|', '/').replace(chr(10), ' ')} |")
    lines += ['', '## Runtimes', '', '| Implementation | Runtime | Execution platform |', '| --- | --- | --- |']
    for name, entry in data['implementations'].items():
        lines.append(f"| {name} | {entry.get('version', 'Unavailable').replace('|', '/')} | {entry.get('platform', '—')} |")
    for mode, title in [('decoded', 'Library: decoded'), ('raw', 'Library: raw text'), ('cli', 'CLI')]:
        queries = [q for q, v in data['queries'].items() if 'kind' in v and (mode != 'raw' or v['kind'] == 'text')]
        lines += ['', f'## {title}', '', '| Implementation | ' + ' | '.join(f'`{q}`' for q in queries) + ' |', '| --- | ' + ' | '.join('---:' for _ in queries) + ' |']
        for name in NAMES:
            cells = []
            for query in queries:
                s = summarize([v for v in data['samples'] if v['implementation'] == name and v['mode'] == mode and v['query'] == query])
                cells.append('Unavailable' if 'unavailable' in data['implementations'][name] else
                             'Failed' if s['median'] is None else
                             f"{s['median']:.2f} / " + (f"{s['p95']:.2f}" if s['p95'] is not None else '—'))
            lines.append('| ' + name + ' | ' + ' | '.join(cells) + ' |')
        lines += ['', '| Implementation / query | Successes | Failures | Timeouts | Result bytes (min–max) |', '| --- | ---: | ---: | ---: | ---: |']
        for name in NAMES:
            for query in queries:
                observations = [v for v in data['samples'] if v['implementation'] == name and v['mode'] == mode and v['query'] == query]
                if observations:
                    s = summarize(observations)
                    sizes = '–'.join(map(str, s['sizes'])) if s['sizes'] else '—'
                    lines.append(f"| {name} / `{query}` | {s['ok']} | {s['failures']} | {s['timeouts']} | {sizes} |")
    unavailable = [(n, e['unavailable']) for n, e in data['implementations'].items() if 'unavailable' in e]
    if unavailable:
        lines += ['', '## Unavailable checks', '']
        lines += [f"- {name}: {reason.replace(chr(10), ' ').replace('`', '')}" for name, reason in unavailable]
    return '\n'.join(lines) + '\n'


def save(data, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='goondev.goonhub.com')
    parser.add_argument('--port', type=int, default=26900)
    parser.add_argument('--samples', type=int, default=20)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--pause', type=float, default=.25)
    parser.add_argument('--location', default='Not supplied; see OS/network metadata in JSON')
    parser.add_argument('--only', nargs='+', choices=NAMES, help='Benchmark only selected implementations')
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/results.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'PERFORMANCE.md')
    args = parser.parse_args()
    if not args.host or not 1 <= args.port <= 65535 or args.samples < 1 or args.warmups < 0 or not math.isfinite(args.pause) or args.pause < 0:
        parser.error('require a host, valid port, positive samples, nonnegative warmups and finite pause')
    started = datetime.now(timezone.utc).isoformat()
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(args.host, args.port, type=socket.SOCK_STREAM)})
    except OSError as error:
        parser.exit(1, f'DNS failed: {error}\n')
    data = dict(started=started, finished=None, settings={k: v for k, v in vars(args).items() if k not in ('output', 'report')},
                addresses=addresses, environment={'system': platform.platform(), 'cpu': platform.processor() or 'unknown',
                'python': sys.version, 'hostname': socket.gethostname()}, queries={}, implementations={}, samples=[],
                results_path=os.path.relpath(args.output.resolve(), args.report.resolve().parent))
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        data['environment']['cpu'] = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), 'unknown')
    try:
        data['revision'] = command(['git', 'rev-parse', 'HEAD'])
    except subprocess.CalledProcessError:
        data['revision'] = 'uncommitted checkout (no HEAD)'
    files = [p for folder in ('bash', 'shell', 'python', 'nodejs', 'go', 'rust', 'php', 'powershell', 'csharp', 'benchmarks')
             for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in ('.py', '.sh', '.js', '.go', '.rs', '.php', '.ps1', '.psm1', '.cs', '.csproj', '.toml')
             and not {'bin', 'obj', 'target', '__pycache__'} & set(p.parts)]
    data['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    # Discovery is paced just like measured requests and sends only these four read-only queries.
    for query in QUERIES:
        try:
            value = topic_raw(args.host, args.port, query)
            kind = 'null' if value is None else 'number' if isinstance(value, float) else 'text'
            data['queries'][query] = {'kind': kind, 'size': len(value) if kind == 'text' else 4 if kind == 'number' else 0}
        except Exception as error:
            data['queries'][query] = {'error': str(error)}
        finally:
            time.sleep(args.pause)
    if not any('kind' in v for v in data['queries'].values()):
        data['finished'] = datetime.now(timezone.utc).isoformat()
        save(data, args.output)
        parser.exit(1, 'All discovery queries failed; observations saved, report not replaced.\n')
    with tempfile.TemporaryDirectory(prefix='byond-benchmark-') as directory:
        entries = prepare(Path(directory), args.only)
        data['implementations'] = entries
        workers = {}
        try:
            for round_number in range(-args.warmups, args.samples):
                print(f"{'Warmup' if round_number < 0 else 'Measured'} round {round_number + 1}/{args.samples}", file=sys.stderr, flush=True)
                for query in rotate(list(data['queries']), round_number):
                    discovery = data['queries'][query]
                    if 'kind' not in discovery:
                        continue
                    expected = discovery['kind']
                    for mode in rotate(list(MODES), round_number):
                        if mode == 'raw' and expected != 'text':
                            continue
                        for name in rotate(list(NAMES), round_number):
                            entry = entries[name]
                            if 'unavailable' in entry:
                                continue
                            timestamp = datetime.now(timezone.utc).isoformat()
                            try:
                                if mode == 'cli':
                                    value = cli_request(entry['cli'] + [args.host, str(args.port), query], expected)
                                else:
                                    if name not in workers:
                                        workers[name] = Worker(entry['worker'] + [args.host, str(args.port)])
                                    value = workers[name].request(mode, query, expected)
                            except (OSError, ValueError, TimeoutError) as error:
                                message = str(error)
                                value = {'error': message, 'timeout': isinstance(error, TimeoutError) or any(t in message.lower() for t in ('timeout', 'timed out', 'etimedout', 'exit 124'))}
                                if mode != 'cli' and name in workers:
                                    workers.pop(name).close()
                            finally:
                                time.sleep(args.pause)
                            if round_number >= 0:
                                data['samples'].append(dict(implementation=name, mode=mode, query=query,
                                                            round=round_number + 1, timestamp=timestamp, **value))
                save(data, args.output)
        finally:
            for worker in workers.values():
                worker.close()
            data['finished'] = datetime.now(timezone.utc).isoformat()
            save(data, args.output)
    args.report.write_text(report(data))
    failures = sum('error' in s for s in data['samples'])
    print(f"Saved {len(data['samples'])} samples ({failures} failures) to {args.output}; report: {args.report}", file=sys.stderr)
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
