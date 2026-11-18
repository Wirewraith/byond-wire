#!/usr/bin/env python3
"""Stage native packages without copying build outputs or duplicating fixtures."""
import argparse
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    'python': ('Python', ['*.py', 'pyproject.toml', 'MANIFEST.in']),
    'nodejs': ('Node.js', ['*.js', 'package.json']),
    'rust': ('Rust', ['*.rs', 'Cargo.toml', 'tests/*.rs']),
    'php': ('PHP', ['php/*.php', 'php/byond-wire', 'php/VERSION', 'composer.json']),
    'powershell': ('PowerShell', ['*.ps1', '*.psm1', '*.psd1']),
    'csharp': ('C# / .NET', ['*.cs', '*.csproj', 'cli/*.cs', 'cli/*.csproj', 'tests/*.cs', 'tests/*.csproj']),
    'go': ('Go', ['go.mod', 'VERSION', 'byond/*.go', 'cmd/byond-wire/*.go']),
}


def version(package):
    if package not in PACKAGES:
        raise ValueError(f'Unknown package: {package}')
    root = ROOT / package
    if package == 'python':
        value = re.search(r'^version = "([^"]+)"$', (root / 'pyproject.toml').read_text(), re.M)[1]
    elif package == 'nodejs':
        value = json.loads((root / 'package.json').read_text())['version']
    elif package == 'rust':
        value = re.search(r'^version = "([^"]+)"$', (root / 'Cargo.toml').read_text(), re.M)[1]
    elif package == 'powershell':
        value = re.search(r"ModuleVersion = '([^']+)'", (root / 'ByondWire.psd1').read_text())[1]
    elif package == 'csharp':
        value = ET.parse(root / 'ByondWire.csproj').findtext('./PropertyGroup/Version')
        if value != ET.parse(root / 'cli/ByondWire.Cli.csproj').findtext('./PropertyGroup/Version'):
            raise ValueError('C# library and CLI versions must match')
    else:
        value = (root / 'VERSION').read_text().strip()
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError(f'{package}: expected stable major.minor.patch version, got {value!r}')
    return value


def tag_for(package, value):
    return f'v{value}' if package == 'php' else f'{package}/v{value}'


def check_tag(package, tag):
    value = version(package)
    if tag != tag_for(package, value):
        raise ValueError(f'{tag!r} does not match {package} version {value}')
    return value


def resolve_tag(tag):
    package = tag.split('/', 1)[0] if '/' in tag else 'php'
    check_tag(package, tag)
    return package


def stage(package, destination):
    version(package)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    source = ROOT if package == 'php' else ROOT / package
    for pattern in PACKAGES[package][1]:
        for path in sorted(source.glob(pattern)):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.copy2(ROOT / 'LICENSE', destination / 'LICENSE')
    fixture = destination / ('byond/testdata/text-vectors.tsv' if package == 'go' else 'tests/text-vectors.tsv')
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'tests/text-vectors.tsv', fixture)
    readme = (ROOT / 'README.md').read_text()
    section = readme.split(f'### {PACKAGES[package][0]}\n', 1)[1].split('\n### ', 1)[0].split('\n## ', 1)[0]
    # Examples in the monorepo README use implementation-directory prefixes.
    if package != 'php':
        section = section.replace(f'./{package}/', './')
        section = re.sub(r'(?<![\w/.-])' + re.escape(package) + '/', '', section)
        section = section.replace(f'cd {package} && ', '')
    if package == 'go':
        section = section.replace('The root `go.work` supports the CLI command above.\n', '')
    (destination / 'README.md').write_text(
        '# BYOND Wire\n\nSmall, standard-library BYOND Topic client. MIT licensed.\n\n'
        'Library calls return decoded text, numbers, or null. Raw calls preserve text bytes.\n\n' + section)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', choices=PACKAGES, nargs='?')
    parser.add_argument('--tag', help='require an exact match with the native package version')
    parser.add_argument('--resolve-tag', help='print validated package/version/tag as GitHub outputs')
    parser.add_argument('--output', type=Path, help='new, empty staging directory')
    parser.add_argument('--sync-go-fixture', action='store_true', help='refresh the generated Go module fixture from tests/text-vectors.tsv')
    args = parser.parse_args()
    try:
        if args.sync_go_fixture:
            target = ROOT / 'go/byond/testdata/text-vectors.tsv'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / 'tests/text-vectors.tsv', target)
        elif args.resolve_tag:
            package = resolve_tag(args.resolve_tag)
            print(f'package={package}\nversion={version(package)}\ntag={args.resolve_tag}')
        elif args.package:
            if args.tag:
                check_tag(args.package, args.tag)
            if args.output:
                stage(args.package, args.output)
            else:
                print(tag_for(args.package, version(args.package)))
        else:
            parser.error('supply a package or --resolve-tag')
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
