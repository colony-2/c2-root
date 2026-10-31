"""Exercise catalog acceptance through the real build script in isolated fixtures."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CatalogAcceptance(unittest.TestCase):
    def test_catalog_source_and_consumer(self):
        config = (ROOT / '.c2/config.yaml').read_text()
        marker = '  - repo: https://github.com/colony-2/cortex-assistant.git\n'
        before, tail = config.split(marker)
        assistant = marker + tail
        repo = 'https://github.com/colony-2/cortex-assistant.git'
        description = ' '.join(tail.split('description: >-\n', 1)[1].split())
        flow = '{repo: ' + json.dumps(repo) + ', description: ' + json.dumps(description) + '}'
        fixtures = {
            'approved': (config, True),
            'missing': (before, False),
            'block_duplicate': (config + assistant, False),
            'flow_mapping_duplicate': (config + '  - ' + flow + '\n', False),
            'string_duplicate': (config + '  - ' + json.dumps(repo) + '\n', False),
            'plain_string_duplicate': (config + '  - ' + repo + '\n', False),
            'alternate_indent_duplicate': (
                config + '  -\n    repo: ' + repo + '\n    description: ' + json.dumps(description) + '\n', False),
            'alias_duplicate': (
                config.replace(marker, '  - &assistant\n    repo: ' + repo + '\n') + '  - *assistant\n', False),
            'tagged_duplicate': (config + '  - !!map ' + flow + '\n', False),
            'flow_sequence': (
                before.split('dependents:\n')[0] + 'dependents: [' + flow + ', ' + flow + ']\n', False),
            'reordered': (before.replace('dependents:\n', 'dependents:\n' + assistant), False),
            'wrong_repository': (config.replace(repo, 'https://github.com/colony-2/wrong.git'), False),
            'empty_description': (before + marker + '    description: >-\n      \n', False),
            'changed_description': (config.replace('Reusable contextual assistant core', 'Changed contextual assistant core'), False),
        }
        with tempfile.TemporaryDirectory(prefix='catalog-regression-') as folder:
            fixture = Path(folder)
            (fixture / '.c2').mkdir()
            for name in ['build.sh', 'README.md', 'PURPOSE.md']:
                shutil.copyfile(ROOT / name, fixture / name)
            for name, (source, accepted) in fixtures.items():
                with self.subTest(name=name):
                    (fixture / '.c2/config.yaml').write_text(source)
                    result = subprocess.run(
                        ['bash', 'build.sh'], cwd=fixture, text=True,
                        capture_output=True, timeout=60,
                    )
                    self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
                    if not accepted:
                        self.assertIn('FAIL:', result.stderr)


if __name__ == '__main__':
    unittest.main()
