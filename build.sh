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
readme_names = ['c2j', 'cortex', 'pulse', 'jobdb', 'pgjobdb', 'shai',
                'c2ops', 'recipes', 'gitvend', 'base']
catalog_names = readme_names + ['cortex-assistant']
expected = [f'https://github.com/colony-2/{name}.git' for name in catalog_names]
config = Path('.c2/config.yaml').read_text()
readme = Path('README.md').read_text()

# c2j deduplicates repositories. Enforce our complete catalog source format
# before consulting it: one final dependents section, block mappings with an
# unquoted canonical repo and a folded description. Reject all other source
# forms rather than silently skipping flow entries, strings, aliases or tags.
sections = config.split('\ndependents:\n')
require(len(sections) == 2, 'expected one final dependents section')
catalog_source = sections[1]
entry_pattern = re.compile(
    r'  - repo: (https://github\.com/colony-2/[a-z0-9-]+\.git)\n'
    r'    description: >-\n(?:      [^\r\n]+\n)+'
)
listed = []
offset = 0
while offset < len(catalog_source):
    entry = entry_pattern.match(catalog_source, offset)
    require(entry is not None, 'unsupported catalog source format; use canonical block mappings with folded descriptions')
    listed.append(entry.group(1))
    offset = entry.end()
require(listed == expected, 'source catalog membership or ordering differs from the approved inventory')

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
assistant_description = (
    'Reusable contextual assistant core, versioned serving protocol, and cell-local c2j session recipe. '
    'Supports durable multi-turn root-executed sessions, contextual reads, documents and returned files/media, finish, and restart. '
    'Orchestrates confirmed, deduplicated goal creation for existing cells; Cortex owns browser and HTTP integration.'
)
require(cells[-1]['description'] == assistant_description,
        'assistant description differs from the approved responsibilities')
print('PASS: c2j parses the ordered eleven-repository catalog and exposes complete descriptions in human/JSON output')

identity = json.loads(cli('self', '--json'))
root = 'https://github.com/colony-2/c2-root.git'
require(identity['repo'] == root and identity['root_repo'] == root,
        'current-cell or root repository changed')
require(identity['ref'] == 'main' and identity['root_ref'] == 'main'
        and identity['short_name'] == 'root', 'current-cell or root identity changed')
print('PASS: current-cell and root identities resolve correctly')

links = re.findall(r'\]\(([^)]+)\)', readme)
for name in readme_names:
    require(f'https://github.com/colony-2/{name}/blob/main/README.md' in links,
            f'missing authoritative component README link: {name}')
require('https://github.com/colony-2/cortex-assistant/blob/main/PURPOSE.md' in links,
        'missing assistant purpose link')
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
