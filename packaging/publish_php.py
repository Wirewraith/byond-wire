#!/usr/bin/env python3
"""Publish tested PHP package contents to the distribution repository."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def publish(source, repository, tag, commit):
    match = re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag)
    if not match or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a stable PHP tag and full source commit SHA')
    source = Path(source).resolve()
    if not (source / 'composer.json').is_file() or (source / '.git').exists():
        raise ValueError('Expected extracted Composer archive without Git metadata')
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory) / 'distribution'

        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args],
                                           text=True, stderr=subprocess.PIPE).strip()

        subprocess.run(['git', 'clone', '--no-checkout', '--', repository, str(repo)],
                       check=True, capture_output=True)
        git('symbolic-ref', 'HEAD', 'refs/heads/main')
        refs = git('for-each-ref', '--format=%(refname)').splitlines()
        if 'refs/remotes/origin/main' in refs:
            git('update-ref', 'refs/heads/main', 'refs/remotes/origin/main')
            git('read-tree', 'HEAD')
        elif any(ref.startswith('refs/remotes/') for ref in refs):
            raise ValueError('Distribution repository must use the main branch')
        git('--work-tree=' + str(source), 'add', '--all')
        tree = git('write-tree')
        tags = [ref[10:] for ref in refs if ref.startswith('refs/tags/')]
        if tag in tags:
            if git('rev-parse', tag + '^{tree}') != tree:
                raise ValueError(f'{tag} already exists with different package contents')
            return
        version = tuple(map(int, match.groups()))
        for previous in tags:
            if re.fullmatch(r'v\d+\.\d+\.\d+', previous) and tuple(map(int, previous[1:].split('.'))) > version:
                raise ValueError(f'{tag} is older than published {previous}')
        git('-c', 'commit.gpgsign=false', '-c', 'user.name=github-actions[bot]',
            '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit', '--allow-empty', '-m', f'Release {tag}\n\nSource: https://github.com/Wirewraith/byond-wire/commit/{commit}')
        git('-c', 'tag.gpgsign=false', 'tag', tag)
        git('push', '--atomic', 'origin', 'HEAD:refs/heads/main', 'refs/tags/' + tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('repository')
    parser.add_argument('tag')
    parser.add_argument('commit')
    args = parser.parse_args()
    try:
        publish(args.source, args.repository, args.tag, args.commit)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n{getattr(error, "stderr", "") or ""}')


if __name__ == '__main__':
    main()
