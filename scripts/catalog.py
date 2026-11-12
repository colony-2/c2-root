"""Read-only checks for the root's deliberately restricted catalog source format."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


APPROVED = [{'repo': 'https://github.com/colony-2/c2j.git', 'description': 'CLI and Go libraries for submitting, executing, and inspecting recipe jobs through JobDB. Interprets recipe control flow and invokes built-in and extension operations in workers. Supports local embedded and remote execution; compute provisioning belongs outside c2j.'}, {'repo': 'https://github.com/colony-2/cortex.git', 'description': 'Web interface for c2j recipe jobs backed by remote JobDB. Supports submission, execution inspection, artifacts, restarts, and human input or document reviews. Workers run separately against the same runtime.'}, {'repo': 'https://github.com/colony-2/pulse.git', 'description': 'Discovers eligible c2j jobs across a JobDB tenant and dispatches them to compatible executors. Acquires leases and supplies them to c2j workers on local Docker or configured remote/cloud providers. Owns compute dispatch rather than recipe semantics or durable state storage.'}, {'repo': 'https://github.com/colony-2/jobdb.git', 'description': 'Durable job runtime, public workflow APIs, and remote runtime server. Coordinates execution state, leases, history, and artifact access for workers and clients. Provides SQLite and in-memory options, with PostgreSQL support composed by pgjobdb.'}, {'repo': 'https://github.com/colony-2/pgjobdb.git', 'description': "PostgreSQL scheduler and JobDB runtime integration. Combines typed scheduling and persistent PostgreSQL state with JobDB's public workflow core. Provides the PostgreSQL runtime executable and container distribution."}, {'repo': 'https://github.com/colony-2/shai.git', 'description': 'Container sandbox tooling for agent and development commands. Configures workspace access, network access, and host integrations for controlled execution environments. Supports environment setup independently; current c2j operations execute directly in their provisioned worker environment.'}, {'repo': 'https://github.com/colony-2/c2ops.git', 'description': 'Packaged extension operations used by c2j recipes. Provides agent/LLM, GitHub Actions, and policy integrations through a JSON input/output contract. Published package selectors let recipes choose available operation implementations.'}, {'repo': 'https://github.com/colony-2/recipes.git', 'description': 'Shared C2 development recipes, authoring guides, and native c2j scenarios. Combines operations into durable flows with consultation, human review, prerequisite coordination, implementation, and verification. Supplies reusable workflow definitions consumed by c2j.'}, {'repo': 'https://github.com/colony-2/gitvend.git', 'description': 'Gateway for controlled GitHub repository access through scoped short-lived Git credentials. Keeps upstream GitHub credentials outside agent environments and enforces repository/branch permissions. An optional JobDB plugin issues credentials bounded by verified job lease authority.'}, {'repo': 'https://github.com/colony-2/base.git', 'description': 'Shared worker image and development tool distribution. Supplies c2j and tools used in provisioned executors, including the base2 shared-Nix-store integration used by Pulse. Provides an execution environment rather than scheduling or workflow state.'}, {'repo': 'https://github.com/colony-2/cortex-assistant.git', 'description': 'Reusable contextual assistant core, versioned serving protocol, and cell-local c2j session recipe. Supports durable multi-turn root-executed sessions, contextual reads, documents and returned files/media, finish, and restart. Orchestrates confirmed, deduplicated goal creation for existing cells; Cortex owns browser and HTTP integration.'}, {'repo': 'https://github.com/colony-2/pulse-tart.git', 'description': 'Tart-backed instance-provider plugin for Pulse on Apple Silicon macOS hosts. Provisions isolated VMs and delivers supplied worker processes while preserving Pulse submission and active-instance contracts. Owns Tart capacity, guest execution, and cleanup; Pulse retains scheduling and lease acquisition.'}, {'repo': 'https://github.com/colony-2/infra.git', 'description': 'Google Cloud infrastructure and deployment operations for shared platform access and isolated application environments. Owns OpenTofu provisioning, private service networking, secrets references, upgrades and recovery. Starts with Oregon dev Cloud Run and Cloud SQL plus shared Headscale SQLite and VPN routing; application code and identity contracts remain with their owners.'}]


def read_catalog(config):
    sections = config.split('\ndependents:\n')
    require(len(sections) == 2, 'expected one final dependents section')
    header, source = sections
    pattern = re.compile(
        r'  - repo: (https://github\.com/colony-2/[a-z0-9-]+\.git)\n'
        r'    description: >-\n((?:      [^\r\n]+\n)+)')
    entries, offset = [], 0
    while offset < len(source):
        match = pattern.match(source, offset)
        require(match is not None, 'unsupported catalog source format; use canonical block mappings with folded descriptions')
        description = ' '.join(match[2].split())
        require(bool(description), 'missing description')
        require(len(description.split('. ')) == 3, 'expected three descriptive sentences')
        entries.append({'repo': match[1], 'description': description})
        offset = match.end()
    require(bool(entries), 'empty catalog')
    require(len({entry['repo'] for entry in entries}) == len(entries), 'duplicate repository')
    # This is a source-format checker, not an alternative general YAML loader.
    identity = {}
    for section in ['self', 'root']:
        match = re.search(r'^' + section + r':\n((?:  [^\n]+\n)+)', header, re.M)
        require(match is not None, 'missing identity section: ' + section)
        values = dict(re.findall(r'^  ([a-z_]+): ([^\n]+)$', match[1], re.M))
        require('repo' in values and 'ref' in values, 'missing repository/ref identity')
        identity[section] = values
    require(entries == APPROVED, 'catalog differs from approved membership, order or descriptions')
    require(identity == {'self': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main', 'name': 'root'}, 'root': {'repo': 'https://github.com/colony-2/c2-root.git', 'ref': 'main'}}, 'configured identity differs from approved repository, ref or name')
    return entries, identity


def cli(*args):
    return subprocess.check_output(['c2j', *args], text=True, timeout=30)


def check_consumers(entries, identity):
    # Registry enumeration is remote. Configured dependency parsing is local.
    cells = json.loads(cli('cells', '--dependencies', '--json'))
    require(isinstance(cells, list), 'expected dependency list')
    require([{'repo': c.get('repo'), 'description': c.get('description')} for c in cells] == entries,
            'consumer membership, order, or descriptions differ from source')
    human = cli('cells', '--dependencies')
    for entry in entries:
        require(entry['repo'] in human and entry['description'] in human,
                'human output omits repository or complete description')
    actual = json.loads(cli('self', '--json'))
    for key, value in {'repo': identity['self']['repo'], 'ref': identity['self']['ref'],
                       'root_repo': identity['root']['repo'], 'root_ref': identity['root']['ref']}.items():
        require(actual.get(key) == value, 'incorrect CLI identity: ' + key)
    # No naming pattern is configured here. Current c2j intentionally emits an
    # empty short_name; self.name is not a repository naming pattern.
    require(actual.get('pattern') == '' and actual.get('short_name') == '',
            'incorrect CLI naming identity for a config without a pattern')
    if actual.get('workspace', {}).get('status') == 'present':
        require(actual['workspace'].get('cell_name') == identity['self'].get('name'),
                'incorrect workspace cell identity')
    print(f'PASS: {len(entries)} configured dependencies and current CLI identity')


def check_docs(entries, identity, root):
    readme = (root / 'README.md').read_text()
    links = re.findall(r'\]\(([^)]+)\)', readme)
    documented = re.findall(r'https://github\.com/colony-2/([a-z0-9-]+)/blob/main/(?:README|PURPOSE)\.md', readme)
    names = [e['repo'].rsplit('/', 1)[1].removesuffix('.git') for e in entries]
    require(set(documented) == set(names), 'documentation and configured catalog membership differ')
    require(identity['root']['repo'].removesuffix('.git') in links, 'missing root repository link')
    require('PURPOSE.md' in links and '.c2/config.yaml' in links, 'missing purpose or catalog navigation')
    for link in links:
        if not link.startswith('https://'):
            require((root / link.split('#', 1)[0]).is_file(), 'broken local link: ' + link)
    require('c2j cells\n' in readme and 'c2j cells --json' in readme
            and 'c2j cells --dependencies' in readme, 'missing catalog discovery commands')
    require(readme.count('```') % 2 == 0 and '```mermaid\nflowchart TD\n' in readme,
            'unbalanced code fences or missing architecture diagram')
    print('PASS: documentation membership, links, commands and diagram structure')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['catalog', 'docs', 'all'], nargs='?', default='all')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    entries, identity = read_catalog((root / '.c2/config.yaml').read_text())
    if args.mode in ['catalog', 'all']:
        check_consumers(entries, identity)
    if args.mode in ['docs', 'all']:
        check_docs(entries, identity, root)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        sys.exit('FAIL: ' + str(error))
