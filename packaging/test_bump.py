"""Version planning must preserve manifests and keep partial edits out of releases."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    'python/pyproject.toml': '[project]\nversion = "0.1.0"\n',
    'nodejs/package.json': '{\n  "name": "byond-wire",\n  "version": "0.1.0"\n}\n',
    'rust/Cargo.toml': '[package]\nname = "byond-wire"\nversion = "0.1.0"\n',
    'rust/Cargo.lock': 'version = 4\n\n[[package]]\nname = "byond-wire"\nversion = "0.1.0"\n',
    'php/VERSION': '0.1.0\n',
    'powershell/ByondWire.psd1': "@{ ModuleVersion = '0.1.0' }\n",
    'csharp/ByondWire.csproj': '<Project><PropertyGroup><Version>0.1.0</Version></PropertyGroup></Project>\n',
    'csharp/cli/ByondWire.Cli.csproj': '<Project><PropertyGroup><Version>0.1.0</Version></PropertyGroup></Project>\n',
    'go/VERSION': '0.1.0\n',
}


class BumpTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'packaging/bump.py').is_file(), 'version planner is missing')
        import sys
        sys.path.insert(0, str(ROOT / 'packaging'))
        self.addCleanup(sys.path.pop, 0)
        spec = importlib.util.spec_from_file_location('bump', ROOT / 'packaging/bump.py')
        self.bump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bump)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for name, content in MANIFESTS.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        old = self.bump.release.ROOT
        self.bump.release.ROOT = root
        self.addCleanup(setattr, self.bump.release, 'ROOT', old)
        self.root = root

    def snapshot(self):
        return {name: (self.root / name).read_bytes() for name in MANIFESTS}

    def test_plan_does_not_modify_any_file(self):
        before = self.snapshot()
        plan = self.bump.plan('all', 'patch')
        self.assertEqual(len(plan['tags']), 7)
        self.assertIn('v0.1.1', plan['tags'])
        self.assertIn('go/v0.1.1', plan['tags'])
        self.assertEqual(self.snapshot(), before)

    def test_all_manifests_and_csharp_pair_and_rust_lock_are_updated(self):
        self.bump.plan('all', 'minor', write=True)
        for package in self.bump.release.PACKAGES:
            self.assertEqual(self.bump.release.version(package), '0.2.0')
        self.assertIn('version = "0.2.0"', (self.root / 'rust/Cargo.lock').read_text())

    def test_single_package_keeps_other_files_and_formatting(self):
        before = self.snapshot()
        plan = self.bump.plan('nodejs', 'major', write=True)
        self.assertEqual(plan['tags'], ['nodejs/v1.0.0'])
        self.assertEqual(plan['files'], ['nodejs/package.json'])
        for name, value in before.items():
            expected = value.replace(b'"version": "0.1.0"', b'"version": "1.0.0"') if name == 'nodejs/package.json' else value
            self.assertEqual((self.root / name).read_bytes(), expected)

    def test_current_publishes_existing_versions_without_edits(self):
        before = self.snapshot()
        plan = self.bump.plan('all', 'current', write=True)
        self.assertEqual(plan['files'], [])
        self.assertEqual(len(plan['tags']), 7)
        self.assertEqual(self.snapshot(), before)

    def test_all_bumps_each_independent_version(self):
        (self.root / 'php/VERSION').write_text('3.4.9\n')
        plan = self.bump.plan('all', 'patch', write=True)
        self.assertIn('v3.4.10', plan['tags'])
        self.assertIn('python/v0.1.1', plan['tags'])
        self.assertEqual(self.bump.release.version('php'), '3.4.10')

    def test_validation_failure_never_partially_updates_versions(self):
        path = self.root / 'csharp/cli/ByondWire.Cli.csproj'
        path.write_text(path.read_text().replace('<Version>0.1.0</Version>', '<Version>9.0.0</Version>'))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.bump.plan('all', 'patch', write=True)
        self.assertEqual(self.snapshot(), before)

    def test_go_v2_requires_module_migration_before_any_edit(self):
        (self.root / 'go/VERSION').write_text('1.4.7\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Go v2'):
            self.bump.plan('all', 'major', write=True)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_package_and_bump_are_rejected(self):
        for package, bump in [('unknown', 'patch'), ('python', 'beta')]:
            with self.assertRaises(ValueError):
                self.bump.plan(package, bump, write=True)


if __name__ == '__main__':
    unittest.main()
