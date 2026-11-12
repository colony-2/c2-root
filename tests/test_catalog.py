"""Deterministic consumer fixtures: never connect to a registry or live JobDB."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog', ROOT / 'scripts/catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='catalog-regression-')
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Path(self.temporary.name)
        for name in ['.c2', 'scripts', 'bin']:
            (self.fixture / name).mkdir()
        for name in ['build.sh', 'README.md', 'PURPOSE.md', '.c2/config.yaml', 'scripts/catalog.py']:
            shutil.copyfile(ROOT / name, self.fixture / name)
        self.config = (ROOT / '.c2/config.yaml').read_text()
        self.entries, identity = catalog.read_catalog(self.config)
        self.identity = {'repo': identity['self']['repo'], 'ref': identity['self']['ref'],
                         'root_repo': identity['root']['repo'], 'root_ref': identity['root']['ref'],
                         'pattern': '', 'short_name': ''}
        self.consumer = {'cells': self.entries, 'identity': self.identity}
        fake = self.fixture / 'bin/c2j'
        fake.write_text('''#!/usr/bin/env python3
import json
from pathlib import Path
import sys
p = Path(__file__).resolve().parents[1]
data = json.loads((p / 'consumer.json').read_text())
args = sys.argv[1:]
if args == ['cells', '--dependencies', '--json']:
    print(json.dumps(data['cells']))
elif args == ['cells', '--dependencies']:
    print(data.get('human', '\\n'.join(c['repo'] + ' ' + c['description'] for c in data['cells'])))
elif args == ['self', '--json']:
    print(json.dumps(data['identity']))
else:
    sys.exit('fixture forbids remote registry calls or unsupported arguments: ' + repr(args))
''')
        fake.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.fixture / 'bin') + os.pathsep + os.environ['PATH'],
                        PYTHONDONTWRITEBYTECODE='1')

    def run_check(self, accepted, config=None, readme=None):
        (self.fixture / '.c2/config.yaml').write_text(self.config if config is None else config)
        (self.fixture / 'consumer.json').write_text(json.dumps(self.consumer))
        if readme is not None:
            (self.fixture / 'README.md').write_text(readme)
        result = subprocess.run(['bash', 'build.sh'], cwd=self.fixture, env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
        if not accepted:
            self.assertIn('FAIL:', result.stderr)

    def test_current_config_and_cli_schema(self):
        self.run_check(True)

    def test_infra_is_the_only_appended_route(self):
        self.assertEqual(len(self.entries), 13)
        self.assertEqual(self.entries[-1], {
            'repo': 'https://github.com/colony-2/infra.git',
            'description': 'Google Cloud infrastructure and deployment operations for shared platform access and isolated application environments. Owns OpenTofu provisioning, private service networking, secrets references, upgrades and recovery. Starts with Oregon dev Cloud Run and Cloud SQL plus shared Headscale SQLite and VPN routing; application code and identity contracts remain with their owners.',
        })
        self.assertEqual(sum(e['repo'].endswith('/infra.git') for e in self.entries), 1)
        self.run_check(True)

    def test_infra_consumer_and_documentation_rejections(self):
        self.consumer['cells'] = [dict(c) for c in self.entries]
        self.consumer['cells'][-1]['description'] = 'Incomplete infra description.'
        self.run_check(False)
        self.consumer['cells'] = self.entries
        readme = (ROOT / 'README.md').read_text()
        self.run_check(False, readme=readme.replace(
            '/infra/blob/main/PURPOSE.md', '/unknown/blob/main/PURPOSE.md'))

    def test_real_consumer_without_jobdb(self):
        # Use the actual installed CLI, isolated from task helpers and live JobDB.
        config = self.config.replace('http://192.168.1.195:9047/c2', 'http://127.0.0.1:1/unavailable')
        (self.fixture / '.c2/config.yaml').write_text(config)
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.fixture), 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run(['bash', 'build.sh', 'catalog'], cwd=self.fixture,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_rejections(self):
        # Select the last complete block, rather than accidentally including
        # subsequent cells in an assistant-specific description fixture.
        start = self.config.rfind('  - repo: ')
        before, block = self.config[:start], self.config[start:]
        repo = self.entries[-1]['repo']
        description = self.entries[-1]['description']
        flow = '{repo: ' + json.dumps(repo) + ', description: ' + json.dumps(description) + '}'
        fixtures = {
            'missing': before,
            'block_duplicate': self.config + block,
            'flow_mapping_duplicate': self.config + '  - ' + flow + '\n',
            'string_duplicate': self.config + '  - ' + json.dumps(repo) + '\n',
            'plain_string_duplicate': self.config + '  - ' + repo + '\n',
            'alternate_indent_duplicate': self.config + '  -\n    repo: ' + repo + '\n    description: ' + json.dumps(description) + '\n',
            'alias_duplicate': self.config.replace('  - repo: ' + repo, '  - &entry\n    repo: ' + repo) + '  - *entry\n',
            'tagged_duplicate': self.config + '  - !!map ' + flow + '\n',
            'flow_sequence': before.split('dependents:\n')[0] + 'dependents: [' + flow + ', ' + flow + ']\n',
            'reordered': before.replace('dependents:\n', 'dependents:\n' + block),
            'wrong_repository': self.config.replace(repo, 'https://github.com/colony-2/wrong.git'),
            'empty_description': before + '  - repo: ' + repo + '\n    description: >-\n      \n',
            'missing_description': before + '  - repo: ' + repo + '\n',
            'changed_description': self.config.replace('Tart-backed instance-provider', 'Changed instance-provider'),
        }
        for name, source in fixtures.items():
            with self.subTest(name=name):
                self.run_check(False, config=source)

    def test_configured_identity_changes(self):
        for old, new in [('c2-root.git', 'wrong.git'), ('ref: main', 'ref: other'), ('name: root', 'name: other')]:
            with self.subTest(field=old):
                self.run_check(False, config=self.config.replace(old, new))

    def test_consumer_discrepancies(self):
        for field, value in [('cells', self.entries[:-1]), ('cells', self.entries + self.entries[:1]),
                             ('cells', list(reversed(self.entries))), ('human', 'incomplete output')]:
            with self.subTest(field=field, value=value):
                old = self.consumer.get(field)
                self.consumer[field] = value
                self.run_check(False)
                if old is None:
                    del self.consumer[field]
                else:
                    self.consumer[field] = old
        self.consumer['cells'] = [dict(c) for c in self.entries]
        self.consumer['cells'][0]['description'] = 'Changed description.'
        self.run_check(False)

    def test_incorrect_identity(self):
        for key in self.identity:
            with self.subTest(key=key):
                old = self.identity[key]
                self.identity[key] = 'incorrect'
                self.run_check(False)
                self.identity[key] = old
        self.identity['workspace'] = {'status': 'present', 'cell_name': 'wrong'}
        self.run_check(False)

    def test_documentation_inconsistencies(self):
        readme = (ROOT / 'README.md').read_text()
        for changed in [readme.replace('/pulse-tart/blob/main/README.md', '/unknown/blob/main/README.md'),
                        readme.replace('](PURPOSE.md)', '](missing.md)'),
                        readme.replace('flowchart TD', 'flowchart LR'),
                        readme + '\n```',
                        readme.replace('c2j cells --dependencies', 'removed command')]:
            with self.subTest(changed=changed[-70:]):
                self.run_check(False, readme=changed)

    def test_unexpected_documented_route_is_rejected(self):
        # Even matching consumer and docs cannot silently expand approved membership.
        repo = 'https://github.com/colony-2/example.git'
        self.consumer['cells'] = self.entries + [{'repo': repo, 'description': 'First sentence. Second sentence. Third sentence.'}]
        config = self.config + ('  - repo: ' + repo + '\n    description: >-\n'
                                '      First sentence. Second sentence. Third sentence.\n')
        readme = (ROOT / 'README.md').read_text() + '\n[example](https://github.com/colony-2/example/blob/main/README.md)\n'
        self.run_check(False, config=config, readme=readme)


if __name__ == '__main__':
    unittest.main()
