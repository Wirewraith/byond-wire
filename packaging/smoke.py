#!/usr/bin/env python3
"""Exercise installed SDKs and CLI bytes/exit codes outside the repository."""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading


def run(args, cwd, **options):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, check=True, **options)


def exchange(command, cwd, body, expected, code=0):
    failures = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(30)

        def serve():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(10)
                    data = b''
                    while len(data) < 17:
                        chunk = peer.recv(17 - len(data))
                        if not chunk:
                            raise AssertionError('truncated request')
                        data += chunk
                    assert data == b'\0\x83\0\x0d\0\0\0\0\0?status\0', data
                    peer.sendall(b'\0\x83' + struct.pack('>H', len(body)) + body)
                    assert peer.recv(1) == b'', 'socket was not closed'
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = subprocess.run([str(arg) for arg in command] + ['127.0.0.1', str(listener.getsockname()[1]), 'status'],
                                cwd=cwd, capture_output=True, timeout=30)
        thread.join(31)
        assert not thread.is_alive(), 'server did not finish'
        assert not failures, (failures, result.returncode, result.stderr)
        assert result.returncode == code, (result.returncode, result.stderr)
        assert result.stdout == expected, (result.stdout, expected)
        assert bool(result.stderr) == (code == 1), result.stderr


def smoke(package, artifacts, work):
    version = json.loads((artifacts / 'release.json').read_text())['version']
    env = os.environ.copy()
    env['GOWORK'] = 'off'
    env['NUGET_PACKAGES'] = str(work / 'nuget-packages')
    env['COMPOSER_CACHE_DIR'] = str(work / 'composer-cache')
    env['COMPOSER_HOME'] = str(work / 'composer-home')
    if package == 'python':
        import tarfile
        with tarfile.open(next(artifacts.glob('*.tar.gz'))) as archive:
            archive.extractall(work, filter='data')
        run(['python3', '-m', 'unittest', 'discover'], next(work.glob('byond_wire-*')))
        run(['python3', '-m', 'venv', work / 'venv'], work)
        python = work / 'venv/bin/python'
        run([python, '-m', 'pip', 'install', '--no-deps', *artifacts.glob('*.whl')], work)
        cli = [work / 'venv/bin/byond-wire']
        sdk = [python, '-c', "import byond_wire,sys; assert byond_wire.topic(sys.argv[1],int(sys.argv[2]),sys.argv[3]) == 'café'"]
        silent = [python, '-c', 'import byond_wire']
    elif package == 'nodejs':
        run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund', *artifacts.glob('*.tgz')], work)
        cli = [work / 'node_modules/.bin/byond-wire']
        sdk = ['node', '-e', "require('byond-wire')(...[process.argv[1],+process.argv[2],process.argv[3]]).then(x=>{if(x!=='café')throw Error(x)}).catch(e=>{console.error(e);process.exitCode=1})"]
        silent = ['node', '-e', "require('byond-wire')"]
    elif package == 'php':
        archive = next(artifacts.glob('*.zip'))
        manifest = {'require': {'wirewraith/byond-wire': version}, 'repositories': [{
            'type': 'package', 'package': {'name': 'wirewraith/byond-wire', 'version': version,
            'dist': {'url': archive.as_uri(), 'type': 'zip'},
            'autoload': {'files': ['php/byond-wire.php']}, 'bin': ['php/byond-wire']}}]}
        (work / 'composer.json').write_text(json.dumps(manifest))
        run(['composer', 'install', '--no-interaction', '--no-progress', '--no-plugins', '--no-scripts'], work, env=env)
        cli = ['php', work / 'vendor/bin/byond-wire']
        sdk = ['php', '-r', "require 'vendor/autoload.php'; if (\\Byond\\topic($argv[1],(int)$argv[2],$argv[3]) !== 'café') exit(1);", '--']
        silent = ['php', '-r', "require 'vendor/autoload.php';"]
    elif package == 'rust':
        import tarfile
        with tarfile.open(next(artifacts.glob('*.crate'))) as archive:
            archive.extractall(work, filter='data')
        crate = work / f'byond-wire-{version}'
        run(['cargo', 'test', '--offline'], crate)
        env['PATH'] = str(work / 'installed/bin') + os.pathsep + env['PATH']
        run(['cargo', 'install', '--offline', '--path', crate, '--root', work / 'installed'], work, env=env)
        cli = [work / 'installed/bin/byond-wire']
        (work / 'Cargo.toml').write_text('[package]\nname="consumer"\nversion="0.0.0"\nedition="2021"\n[dependencies]\nbyond-wire={path=' + json.dumps(str(crate)) + '}\n')
        (work / 'src').mkdir()
        (work / 'src/main.rs').write_text('fn main() { let a: Vec<_> = std::env::args().collect(); assert_eq!(byond_wire::topic(&a[1], &a[2], &a[3], std::time::Duration::from_secs(5)).unwrap(), byond_wire::Response::Text("café".into())); }')
        run(['cargo', 'build', '--offline'], work)
        sdk = [work / 'target/debug/consumer']
        silent = None
    elif package == 'go':
        import zipfile
        with zipfile.ZipFile(next(artifacts.glob('*.zip'))) as archive:
            archive.extractall(work / 'module')
        module = work / 'module'
        run(['go', 'test', './...'], module, env=env)
        run(['go', 'build', '-o', work / 'byond-wire', './cmd/byond-wire'], module, env=env)
        cli = [work / 'byond-wire']
        (work / 'go.mod').write_text('module consumer\n\ngo 1.22\n\nrequire github.com/Wirewraith/byond-wire/go v' + version + '\nreplace github.com/Wirewraith/byond-wire/go => ./module\n')
        (work / 'main.go').write_text('package main\nimport("github.com/Wirewraith/byond-wire/go/byond";"os";"time")\nfunc main(){a:=os.Args; v,e:=byond.Topic(a[1],a[2],a[3],5*time.Second); if e!=nil || v.Kind!=byond.Text || v.Text!="café" {panic("unexpected result")}}\n')
        run(['go', 'build', '-o', work / 'consumer', '.'], work, env=env)
        sdk = [work / 'consumer']
        silent = None
    elif package == 'csharp':
        config = work / 'NuGet.Config'
        config.write_text('<configuration><packageSources><clear/><add key="local" value="' + str(artifacts) + '"/></packageSources></configuration>')
        run(['dotnet', 'tool', 'install', 'ByondWire.Cli', '--version', version, '--tool-path', work / 'tools', '--configfile', config], work, env=env)
        cli = [work / 'tools/byond-wire']
        (work / 'Consumer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="ByondWire" Version="' + version + '"/></ItemGroup></Project>')
        (work / 'Program.cs').write_text('if ((string)(await ByondWire.Client.TopicAsync(args[0], int.Parse(args[1]), args[2])) != "café") throw new System.Exception("unexpected result");')
        run(['dotnet', 'build', '-o', work / 'built', '--configfile', config], work, env=env)
        sdk = ['dotnet', work / 'built/Consumer.dll']
        silent = None
    else:
        # PowerShellGet installs the actual locally built nupkg into a clean module tree.
        install = work / 'install.ps1'
        install.write_text("$ErrorActionPreference='Stop'\nRegister-PSRepository -Name ByondWireSmoke -SourceLocation $args[0] -InstallationPolicy Trusted\ntry { Save-Module ByondWire -Repository ByondWireSmoke -Path $args[1] -RequiredVersion $args[2] } finally { Unregister-PSRepository ByondWireSmoke }\n")
        (work / 'modules').mkdir()
        run(['pwsh', '-NoProfile', '-File', install, artifacts, work / 'modules', version], work)
        module = work / 'modules/ByondWire' / version
        cli = ['pwsh', '-NoProfile', '-File', module / 'cli.ps1']
        consumer = work / 'consumer.ps1'
        consumer.write_text("$ErrorActionPreference='Stop'\nImport-Module '" + str(module / 'ByondWire.psd1').replace("'", "''") + "'\nif ((Invoke-ByondTopic $args[0] ([int]$args[1]) $args[2]) -cne 'café') { throw 'unexpected result' }\n")
        sdk = ['pwsh', '-NoProfile', '-File', consumer]
        silent = ['pwsh', '-NoProfile', '-Command', "Import-Module '" + str(module / 'ByondWire.psd1').replace("'", "''") + "'"]
    if silent:
        result = run(silent, work, capture_output=True)
        assert result.stdout == result.stderr == b'', result
    exchange(sdk, work, b'\x06\xff\x16caf\xc3\xa9\0', b'')
    for body, expected, code in [
        (b'\x06\xff\x16raw\xff\0', b'\xff\x16raw\xff', 0),
        (b'\x06\0', b'', 0), (b'\0', b'', 2),
        (b'\x2a' + struct.pack('<f', -2.5), b'-2.5', 0),
        (b'\x63', b'', 1),
    ]:
        exchange(cli, work, body, expected, code)
    print(f'{package}: installed library and CLI checks passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package')
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='byond-consumer-') as directory:
        smoke(args.package, args.artifacts.resolve(), Path(directory))


if __name__ == '__main__':
    main()
