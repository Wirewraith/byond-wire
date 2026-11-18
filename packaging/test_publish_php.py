"""Exercise distribution publication against a real local Git remote."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


class PublishPhpTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('publish_php.py')
        self.assertTrue(path.exists(), 'PHP distribution publisher is missing')
        spec = importlib.util.spec_from_file_location('publish_php', path)
        self.publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.publisher)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '--initial-branch=main', self.remote],
                       check=True, capture_output=True)
        self.source = root / 'source'
        self.source.mkdir()
        (self.source / 'README.md').write_text('# PHP only\n')
        (self.source / 'composer.json').write_text('{"name":"wirewraith/byond-wire"}\n')
        self.commit = 'a' * 40

    def git(self, *args):
        return subprocess.check_output(['git', '--git-dir', str(self.remote), *args], text=True).strip()

    def publish(self, tag='v0.1.2'):
        self.publisher.publish(self.source, str(self.remote), tag, self.commit)

    def test_first_publish_and_retry_preserve_tag(self):
        self.publish()
        head = self.git('rev-parse', 'main')
        self.assertEqual(head, self.git('rev-parse', 'v0.1.2'))
        self.assertEqual(self.git('show', 'main:README.md'), '# PHP only')
        self.assertIn(self.commit, self.git('log', '-1', '--format=%B'))
        self.publish()
        self.assertEqual(head, self.git('rev-parse', 'main'))

    def test_changed_retry_is_rejected_without_writing_remote(self):
        self.publish()
        before = self.git('show-ref')
        (self.source / 'README.md').write_text('different\n')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.publish()
        self.assertEqual(before, self.git('show-ref'))

    def test_new_release_removes_old_files_and_keeps_history(self):
        (self.source / 'old.txt').write_text('old')
        self.publish()
        old = self.git('rev-parse', 'main')
        (self.source / 'old.txt').unlink()
        (self.source / 'README.md').write_text('updated\n')
        self.publish('v0.1.3')
        self.assertEqual(old, self.git('rev-parse', 'main^'))
        self.assertNotIn('old.txt', self.git('ls-tree', '-r', '--name-only', 'main'))
        self.assertIn('old.txt', self.git('ls-tree', '-r', '--name-only', 'v0.1.2'))

    def test_old_retry_does_not_rewind_default_branch(self):
        self.publish()
        (self.source / 'README.md').write_text('updated\n')
        self.publish('v0.1.3')
        before = self.git('show-ref')
        (self.source / 'README.md').write_text('# PHP only\n')
        self.publish()
        self.assertEqual(before, self.git('show-ref'))

    def test_unpublished_older_version_is_rejected(self):
        self.publish()
        before = self.git('show-ref')
        with self.assertRaisesRegex(ValueError, 'older'):
            self.publish('v0.1.1')
        self.assertEqual(before, self.git('show-ref'))

    def test_invalid_release_metadata_fails_before_clone(self):
        for tag, commit in [('php/v0.1.2', self.commit), ('v0.1.2', 'not-a-sha')]:
            with self.assertRaises(ValueError):
                self.publisher.publish(self.source, '/missing/repository', tag, commit)

    def test_executable_mode_is_preserved(self):
        cli = self.source / 'byond-wire'
        cli.write_text('#!/usr/bin/env php\n')
        cli.chmod(0o755)
        self.publish()
        self.assertTrue(self.git('ls-tree', 'main', 'byond-wire').startswith('100755'))

    def test_identical_contents_can_have_a_new_version(self):
        self.publish()
        self.publish('v0.1.3')
        self.assertEqual(self.git('rev-parse', 'v0.1.2^{tree}'),
                         self.git('rev-parse', 'v0.1.3^{tree}'))
        self.assertNotEqual(self.git('rev-parse', 'v0.1.2'), self.git('rev-parse', 'v0.1.3'))

    def test_push_rejection_does_not_publish_a_partial_release(self):
        self.publish()
        before = self.git('show-ref')
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish('v0.1.3')
        self.assertEqual(before, self.git('show-ref'))

    def test_migrated_tags_survive_first_distribution_branch(self):
        self.publish()
        old = self.git('rev-parse', 'v0.1.2')
        self.git('update-ref', '-d', 'refs/heads/main')
        (self.source / 'README.md').write_text('new distribution\n')
        self.publish('v0.1.3')
        self.assertEqual(old, self.git('rev-parse', 'v0.1.2'))
        self.assertEqual(self.git('rev-parse', 'main'), self.git('rev-parse', 'v0.1.3'))


if __name__ == '__main__':
    unittest.main()
