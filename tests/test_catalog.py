"""Configuration and discovery regressions without a live registry or JobDB."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog', ROOT / 'scripts/catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

JOBDB_ENTRY = re.compile(r'^jobdb:[ \t]*(.*)$', re.MULTILINE)


class ConfigurationAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='root-config-regression-')
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Path(self.temporary.name)
        for name in ['.c2', 'scripts', 'bin']:
            (self.fixture / name).mkdir()
        for name in ['build.sh', 'README.md', 'PURPOSE.md', '.c2/config.yaml', 'scripts/catalog.py']:
            shutil.copyfile(ROOT / name, self.fixture / name)
        self.config = (ROOT / '.c2/config.yaml').read_text()
        self.readme = (ROOT / 'README.md').read_text()
        self.purpose = (ROOT / 'PURPOSE.md').read_text()
        self.identity = {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main',
                         'root_repo': 'https://github.com/colony-2/c2-root.git', 'root_ref': 'main',
                         'pattern': '', 'short_name': ''}
        self.consumer = {'cells': [], 'identity': self.identity}
        fake = self.fixture / 'bin/c2j'
        fake.write_text('''#!/usr/bin/env python3
import json
from pathlib import Path
import sys
p = Path(__file__).resolve().parents[1]
data = json.loads((p / 'consumer.json').read_text())
args = sys.argv[1:]
if args == ['cells', '--dependencies', '--json']:
    print(data.get('cells_raw', json.dumps(data['cells'])))
elif args == ['self', '--json']:
    print(data.get('identity_raw', json.dumps(data['identity'])))
else:
    sys.exit('fixture forbids registry calls or unsupported arguments: ' + repr(args))
''')
        fake.chmod(0o755)
        self.env = {'PATH': str(self.fixture / 'bin') + os.pathsep + os.environ['PATH'],
                    'HOME': str(self.fixture), 'PYTHONDONTWRITEBYTECODE': '1'}

    def config_with_jobdb(self, value):
        entry = f'jobdb: {value}' if value else 'jobdb:'
        source, count = JOBDB_ENTRY.subn(entry, self.config)
        self.assertEqual(count, 1, 'expected exactly one configured JobDB entry to replace')
        self.assertEqual(JOBDB_ENTRY.findall(source), [value])
        return source

    def run_check(self, accepted, config=None, readme=None, purpose=None):
        for name, content in [('.c2/config.yaml', self.config if config is None else config),
                              ('README.md', self.readme if readme is None else readme),
                              ('PURPOSE.md', self.purpose if purpose is None else purpose)]:
            (self.fixture / name).write_text(content)
        (self.fixture / 'consumer.json').write_text(json.dumps(self.consumer))
        result = subprocess.run(['bash', 'build.sh'], cwd=self.fixture, env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
        if not accepted:
            self.assertIn('FAIL:', result.stderr)
        return result

    def test_root_preserves_settings_without_inventory(self):
        configured_jobdb = JOBDB_ENTRY.findall(self.config)
        self.assertEqual(len(configured_jobdb), 1, 'expected exactly one configured JobDB entry')
        self.assertEqual(catalog.read_config(self.config), {
            'self': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main', 'name': 'root'},
            'root': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main'},
            'execution': {'base': 'ubuntu-26.04-arm64'},
            'jobdb': configured_jobdb[0],
        })
        self.run_check(True)

    def test_manual_dependents_rejected_in_all_forms(self):
        for section in [
            'dependents:\n', 'dependents: []\n', 'dependents: null\n',
            'dependents: [github.com/colony-2/example]\n',
            'dependents:\n  - repo: https://github.com/colony-2/example.git\n',
            'dependents:\n    - github.com/colony-2/example\n',
            '"dependents": []\n', "'dependents': []\n", 'dependents: &empty []\n',
            'dependents: !!seq []\n', '? dependents\n: []\n',
        ]:
            with self.subTest(section=section):
                self.run_check(False, config=self.config + section)
        self.run_check(False, config='{dependents: [], self: {name: root}}\n')

    def test_replacement_discovery_sources_rejected(self):
        for section in ['discovery: registry\n', 'pattern: github.com/colony-2/*\n',
                        'discovery:\n  command: registry\n']:
            with self.subTest(section=section):
                self.run_check(False, config=self.config + section)

    def test_malformed_or_duplicate_configuration_rejected(self):
        for source in [self.config.replace('self:', 'self'),
                       self.config.replace('  name: root', '   name: root'),
                       self.config.replace('self:', 'self: &identity'),
                       self.config + '---\n', self.config + '\tinvalid: value\n']:
            with self.subTest(source=source):
                self.run_check(False, config=source)
        for key, source in [
            ('jobdb', self.config.rstrip('\n') + '\njobdb: http://127.0.0.1:1\n'),
            ('name', self.config.replace('  name: root', '  name: root\n  name: root')),
        ]:
            with self.subTest(duplicate=key):
                result = self.run_check(False, config=source)
                self.assertIn(f'FAIL: duplicate configuration key: {key}', result.stderr.splitlines())
        result = self.run_check(False, config=self.config_with_jobdb(''))
        self.assertIn('FAIL: missing or malformed JobDB setting', result.stderr.splitlines())
        self.run_check(True, config='# Root settings\n' + self.config + '\n# No inventory\n')

    def test_configured_identity_and_base_changes_rejected(self):
        for old, new in [('c2-root.git', 'wrong.git'), ('ref: main', 'ref: other'),
                         ('name: root', 'name: other'), ('ubuntu-26.04-arm64', 'other-base')]:
            for count in [1, -1]:
                with self.subTest(field=old, count=count):
                    self.run_check(False, config=self.config.replace(old, new, count))
        for field, old, new in [('repo', 'https://github.com/colony-2/c2-root.git', 'https://github.com/colony-2/wrong.git'),
                                ('ref', 'main', 'other')]:
            with self.subTest(section='root', field=field):
                before, root_section = self.config.split('\nroot:\n')
                changed = root_section.replace('  ' + field + ': ' + old, '  ' + field + ': ' + new, 1)
                self.run_check(False, config=before + '\nroot:\n' + changed)

    def test_real_checker_and_cli_with_unreachable_jobdb(self):
        # A minimal environment removes injected task helpers and live JobDB
        # settings. PATH excludes the fake CLI created for the other fixtures.
        unreachable = 'http://127.0.0.1:1/unavailable'
        (self.fixture / '.c2/config.yaml').write_text(self.config_with_jobdb(unreachable))
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.fixture), 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run(['bash', 'build.sh', 'catalog'], cwd=self.fixture,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS: empty configured dependencies and current CLI identity', result.stdout)
        for args, expected in [(['cells', '--dependencies', '--json'], []),
                               (['self', '--json'], self.identity)]:
            observed = json.loads(subprocess.check_output(['c2j', *args], cwd=self.fixture,
                                                         env=env, text=True, timeout=10))
            if isinstance(expected, dict):
                self.assertEqual({key: observed[key] for key in expected}, expected)
            else:
                self.assertEqual(observed, expected)

    def test_nonempty_and_malformed_configured_routes_rejected(self):
        for cells in [[{'repo': 'https://github.com/colony-2/example.git'}], {}, None, '', False, 0]:
            with self.subTest(cells=cells):
                self.consumer['cells'] = cells
                self.run_check(False)
        self.consumer['cells_raw'] = '[invalid json'
        self.run_check(False)

    def test_incorrect_effective_identity_rejected(self):
        for key in self.identity:
            with self.subTest(key=key):
                old = self.identity[key]
                self.identity[key] = 'incorrect'
                self.run_check(False)
                self.identity[key] = old
        self.identity['workspace'] = {'status': 'present', 'cell_name': 'wrong'}
        self.run_check(False)
        self.identity['workspace']['cell_name'] = 'root'
        self.run_check(True)
        for raw in ['[invalid json', '[]', 'null']:
            with self.subTest(raw=raw):
                self.consumer['identity_raw'] = raw
                self.run_check(False)

    def test_documentation_uses_registry_and_empty_routes(self):
        self.assertIn('JobDB registry', self.purpose)
        self.assertIn('returns `[]`', self.readme)
        self.assertIn('not an exhaustive inventory', self.readme)
        self.run_check(True)

    def test_component_links_need_not_match_registry_membership(self):
        # Remove a component, add a new one, and reorder existing links. None of
        # these documentation edits changes the registry or configured routes.
        changed = '\n'.join(line for line in self.readme.splitlines() if not line.startswith('| [Pulse]'))
        changed += '\n[example](https://github.com/colony-2/example/blob/main/README.md)\n'
        lines = changed.splitlines()
        positions = [index for index, line in enumerate(lines) if line.startswith('| [')]
        reordered = [lines[index] for index in reversed(positions)]
        for index, line in zip(positions, reordered):
            lines[index] = line
        self.run_check(True, readme='\n'.join(lines) + '\n')

    def test_documentation_structure_and_discovery_rejections(self):
        for changed in [self.readme.replace('](PURPOSE.md)', '](missing.md)'),
                        self.readme.replace('flowchart TD', 'flowchart LR'),
                        self.readme + '\n```',
                        self.readme.replace('c2j cells --json', 'removed command'),
                        self.readme.replace('returns `[]`', 'returns the inventory'),
                        self.readme + '\nUse c2j cell add to extend the catalog.\n',
                        self.readme + '\nThe root catalog is .c2/config.yaml.\n',
                        self.readme + '\ndependents:\n']:
            with self.subTest(changed=changed[-90:]):
                self.run_check(False, readme=changed)
        for changed in [self.purpose.replace('c2j cells --json', 'removed command'),
                        self.purpose + '\nUse c2j cell add to register a cell.\n',
                        self.purpose + '\n[broken](missing.md)\n', self.purpose + '\n```']:
            with self.subTest(purpose=changed[-90:]):
                self.run_check(False, purpose=changed)


if __name__ == '__main__':
    unittest.main()
