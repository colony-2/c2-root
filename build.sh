#!/usr/bin/env bash
# Read-only catalog checks. Requires python3 and c2j; no services or downloads.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v python3 >/dev/null
command -v c2j >/dev/null

python3 - <<'PY'
import json
from pathlib import Path
import re
import subprocess
import sys


def require(condition, message):
    if not condition:
        sys.exit('FAIL: ' + message)


def cli(*args):
    return subprocess.check_output(['c2j', *args], text=True, timeout=30)


# This ordered inventory is a compatibility expectation, not CLI discovery.
names = ['c2j', 'cortex', 'pulse', 'jobdb', 'pgjobdb', 'shai',
         'c2ops', 'recipes', 'gitvend', 'base']
expected = [f'https://github.com/colony-2/{name}.git' for name in names]
config = Path('.c2/config.yaml').read_text()
readme = Path('README.md').read_text()

# The actual consumer performs YAML parsing and repository resolution.
cells = json.loads(cli('cells', '--json'))
require([cell['repo'] for cell in cells] == expected,
        'catalog membership or ordering differs from the approved inventory')
human = cli('cells')
folded_config = ' '.join(config.split())
for cell in cells:
    description = cell.get('description', '')
    require(bool(description.strip()), f"missing description: {cell['repo']}")
    require(len(description.split('. ')) == 3,
            f"expected three descriptive sentences: {cell['repo']}")
    require(description in human and cell['repo'] in human,
            f"human output omits repository or complete description: {cell['repo']}")
    require(' '.join(description.split()) in folded_config,
            f"resolved description does not match config content: {cell['repo']}")
print('PASS: c2j parses the ordered ten-repository catalog and exposes complete descriptions in human/JSON output')

identity = json.loads(cli('self', '--json'))
root = 'https://github.com/colony-2/c2-root.git'
require(identity['repo'] == root and identity['root_repo'] == root,
        'current-cell or root repository changed')
require(identity['ref'] == 'main' and identity['root_ref'] == 'main'
        and identity['short_name'] == 'root', 'current-cell or root identity changed')
print('PASS: current-cell and root identities resolve correctly')

links = re.findall(r'\]\(([^)]+)\)', readme)
for name in names:
    require(f'https://github.com/colony-2/{name}/blob/main/README.md' in links,
            f'missing authoritative component README link: {name}')
require(root.removesuffix('.git') in links, 'missing root repository link')
require('PURPOSE.md' in links and '.c2/config.yaml' in links,
        'missing purpose or catalog navigation')
for link in links:
    if not link.startswith('https://'):
        require(Path(link.split('#', 1)[0]).is_file(), f'broken local link: {link}')
require('c2j cells\n' in readme and 'c2j cells --json' in readme,
        'missing read-only catalog commands')
require(readme.count('```') % 2 == 0 and '```mermaid\nflowchart TD\n' in readme,
        'unbalanced code fences or missing architecture diagram')
print('PASS: all component documentation links, local targets, catalog commands, and diagram fence are present')
print('NOTE: browser/Mermaid rendering, external link availability, and factual prose review are separate inspection checks')
PY
