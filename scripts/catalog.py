"""Read-only checks for root configuration, CLI identity and documentation."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


IDENTITY = {
    'self': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main', 'name': 'root'},
    'root': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main'},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_config(source):
    # Validate root's small source format, not general YAML. Refusing unknown
    # fields and YAML constructs also prevents an empty, quoted, flow or aliased
    # dependents key from silently restoring the retired inventory.
    config = {}
    section = None
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'(  )?([a-z_]+):(?: ([A-Za-z0-9][A-Za-z0-9:/._-]*))?', line)
        require(match is not None, 'unsupported or malformed configuration line: ' + line)
        indent, key, value = match.groups()
        if indent:
            require(section is not None and value is not None, 'unexpected nested configuration')
            target = config[section]
        else:
            target = config
            section = key if value is None else None
        require(key not in target, 'duplicate configuration key: ' + key)
        target[key] = {} if value is None else value
    require(set(config) == {'self', 'root', 'execution', 'jobdb'},
            'expected only self, root, execution and jobdb; manual dependents and discovery sources are forbidden')
    require({key: config[key] for key in IDENTITY} == IDENTITY,
            'configured identity differs from approved repository, ref or name')
    require(config['execution'] == {'base': 'ubuntu-26.04-arm64'}, 'incorrect execution base')
    require(isinstance(config['jobdb'], str) and config['jobdb'].startswith(('http://', 'https://')),
            'missing or malformed JobDB setting')
    return config


def cli(*args):
    return subprocess.check_output(['c2j', *args], text=True, timeout=30)


def check_consumers(config):
    # Configured routes and self resolution are local; registry enumeration is
    # deliberately outside the build, so a live JobDB is unnecessary.
    cells = json.loads(cli('cells', '--dependencies', '--json'))
    require(cells == [], 'expected an empty configured dependency list')
    actual = json.loads(cli('self', '--json'))
    require(isinstance(actual, dict), 'expected CLI identity object')
    for key, value in {'repo': config['self']['repo'], 'ref': config['self']['ref'],
                       'root_repo': config['root']['repo'], 'root_ref': config['root']['ref']}.items():
        require(actual.get(key) == value, 'incorrect CLI identity: ' + key)
    # self.name is not a repository naming pattern.
    require(actual.get('pattern') == '' and actual.get('short_name') == '',
            'incorrect CLI naming identity for a config without a pattern')
    if actual.get('workspace', {}).get('status') == 'present':
        require(actual['workspace'].get('cell_name') == config['self']['name'],
                'incorrect workspace cell identity')
    print('PASS: empty configured dependencies and current CLI identity')


def check_docs(config, root):
    readme = (root / 'README.md').read_text()
    purpose = (root / 'PURPOSE.md').read_text()
    links = re.findall(r'\]\(([^)]+)\)', readme)
    require(config['root']['repo'].removesuffix('.git') in links, 'missing root repository link')
    require('PURPOSE.md' in links and '.c2/config.yaml' in links, 'missing purpose or configuration navigation')
    for document in [readme, purpose]:
        for link in re.findall(r'\]\(([^)]+)\)', document):
            if not link.startswith('https://'):
                require((root / link.split('#', 1)[0]).is_file(), 'broken local link: ' + link)
        require('c2j cells' in document and 'c2j cells --json' in document and 'registry' in document,
                'missing registry discovery instructions')
        require('c2j cell add' not in document and 'dependents:' not in document
                and 'root catalog is' not in document.lower(), 'obsolete manual-catalog instructions')
        require(document.count('```') % 2 == 0, 'unbalanced code fences')
    require('c2j cells\nc2j cells --json\n' in readme, 'missing registry discovery commands')
    require('c2j cells --dependencies --json' in readme and 'returns `[]`' in readme,
            'missing empty configured-route explanation')
    require('```mermaid\nflowchart TD\n' in readme, 'missing architecture diagram')
    print('PASS: documentation links, registry commands and diagram structure')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['catalog', 'docs', 'all'], nargs='?', default='all')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = read_config((root / '.c2/config.yaml').read_text())
    if args.mode in ['catalog', 'all']:
        check_consumers(config)
    if args.mode in ['docs', 'all']:
        check_docs(config, root)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.SubprocessError) as error:
        sys.exit('FAIL: ' + str(error))
