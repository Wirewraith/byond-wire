#!/usr/bin/env python3
"""Plan native package versions; write only with --write. Git remains the caller's job."""
import argparse
import json
import re
import release

FILES = {
    'python': [('python/pyproject.toml', r'(?m)^(version = ")[^"]+("$)')],
    'nodejs': [('nodejs/package.json', r'("version":\s*")[^"]+(")')],
    'rust': [('rust/Cargo.toml', r'(?m)^(version = ")[^"]+("$)')],
    'php': [('php/VERSION', r'\A()[^\s]+(\s*)\Z')],
    'powershell': [('powershell/ByondWire.psd1', r"(ModuleVersion = ')[^']+(')")],
    'csharp': [(name, r'(<Version>)[^<]+(</Version>)') for name in
               ('csharp/ByondWire.csproj', 'csharp/cli/ByondWire.Cli.csproj')],
    'go': [('go/VERSION', r'\A()[^\s]+(\s*)\Z')],
}


def plan(package, bump, write=False):
    if package != 'all' and package not in release.PACKAGES:
        raise ValueError(f'Unknown package: {package}')
    if bump not in ('current', 'patch', 'minor', 'major'):
        raise ValueError(f'Unknown bump: {bump}')
    packages = list(release.PACKAGES) if package == 'all' else [package]
    versions, edits, tags = {}, {}, []
    for name in packages:
        before = release.version(name)
        parts = list(map(int, before.split('.')))
        if bump != 'current':
            index = ('major', 'minor', 'patch').index(bump)
            parts[index] += 1
            parts[index + 1:] = [0] * (2 - index)
        after = '.'.join(map(str, parts))
        if name == 'go' and parts[0] >= 2:
            raise ValueError('Go v2 requires a module/import migration before automated release')
        versions[name] = {'before': before, 'after': after}
        tags.append(release.tag_for(name, after))
        if after == before:
            continue
        files = list(FILES[name])
        if name == 'rust' and (release.ROOT / 'rust/Cargo.lock').exists():
            files.append(('rust/Cargo.lock', r'(\[\[package\]\]\nname = "byond-wire"\nversion = ")[^"]+(")'))
        for filename, pattern in files:
            text = (release.ROOT / filename).read_text()
            updated, count = re.subn(pattern, lambda match: match[1] + after + match[2], text)
            if count != 1:
                raise ValueError(f'{filename}: expected exactly one package version, found {count}')
            edits[filename] = updated
    # Validate every manifest before writing any selected package.
    if write:
        for filename, content in edits.items():
            (release.ROOT / filename).write_text(content)
    return {'versions': versions, 'tags': tags, 'files': list(edits)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', choices=['all', *release.PACKAGES], default='all')
    parser.add_argument('--bump', choices=['patch', 'minor', 'major', 'current'], default='patch')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(plan(args.package, args.bump, args.write), indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
