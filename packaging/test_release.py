"""Release boundaries: versions, authoritative fixtures, and package contents."""
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'packaging/release.py').is_file(), 'release staging is missing')
        spec = importlib.util.spec_from_file_location('release', ROOT / 'packaging/release.py')
        self.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.release)

    def test_go_module_fixture_matches_authoritative_vectors(self):
        self.assertEqual((ROOT / "go/byond/testdata/text-vectors.tsv").read_bytes(),
                         (ROOT / "tests/text-vectors.tsv").read_bytes())

    def test_native_versions_match_independent_tags(self):
        for package in self.release.PACKAGES:
            version = self.release.version(package)
            tag = self.release.tag_for(package, version)
            self.assertEqual(self.release.check_tag(package, tag), version)
            self.assertEqual(self.release.resolve_tag(tag), package)
            with self.assertRaises(ValueError):
                self.release.check_tag(package, self.release.tag_for(package, '9.9.9'))
            with self.assertRaises(ValueError):
                self.release.check_tag(package, 'untrusted/v0.1.0')

    def test_unrecognized_tags_are_rejected(self):
        for tag in ('main', 'php/v0.1.0', 'python/v9.9.9', 'python/v0.1.0-rc1'):
            with self.assertRaises(ValueError):
                self.release.resolve_tag(tag)

    def test_release_resolution_does_not_require_other_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'go').mkdir()
            (root / 'go/VERSION').write_text('0.1.0\n')
            original = self.release.ROOT
            self.release.ROOT = root
            try:
                self.assertEqual(self.release.resolve_tag('go/v0.1.0'), 'go')
            finally:
                self.release.ROOT = original

    def test_staged_sources_are_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            for package in self.release.PACKAGES:
                stage = self.release.stage(package, pathlib.Path(directory) / package)
                self.assertEqual((stage / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
                self.assertTrue((stage / 'README.md').is_file())
                self.assertTrue((stage / 'PROTOCOL.md').is_file())
                if package == 'php':
                    readme = (stage / 'README.md').read_text()
                    self.assertIn('composer require wirewraith/byond-wire', readme)
                    self.assertIn('\\Byond\\topic_raw(', readme)
                    self.assertNotIn('### Python', readme)
                if package == 'go':
                    self.assertIn('github.com/Wirewraith/byond-wire/go/byond',
                                  (stage / 'README.md').read_text())
                fixture = stage / ('byond/testdata/text-vectors.tsv' if package == 'go' else 'tests/text-vectors.tsv')
                self.assertEqual(fixture.read_bytes(), (ROOT / 'tests/text-vectors.tsv').read_bytes())
                self.assertFalse(any(path.name in {'obj', 'bin', 'target', '__pycache__', '.git'}
                                     for path in stage.rglob('*') if path.is_dir()))
                for other in self.release.PACKAGES:
                    if other != package:
                        self.assertFalse((stage / other).is_dir(), (package, other))

    def test_unknown_package_and_existing_directory_are_rejected(self):
        with self.assertRaises(ValueError):
            self.release.version('../python')
        with tempfile.TemporaryDirectory() as directory:
            sentinel = pathlib.Path(directory) / 'keep'
            sentinel.write_text('unchanged')
            with self.assertRaises(FileExistsError):
                self.release.stage('python', pathlib.Path(directory))
            self.assertEqual(sentinel.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
