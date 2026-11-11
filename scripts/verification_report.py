"""Fail-closed aggregation for the root verification hook."""
import json
import os
from pathlib import Path
import platform
import sys
import subprocess

BEHAVIORS = ('catalog', 'acceptance', 'docs')


def passed(result):
    return (isinstance(result, dict) and result.get('success') is True
            and type(result.get('exit_code')) is int and result['exit_code'] == 0
            and result.get('timed_out') is False
            and result.get('diagnostic_errors', []) == [])


def summarize(results, inbox, outbox, candidate, base, api):
    verdict = api == 'c2.build-hook/v1'
    rows = []
    for name in BEHAVIORS:
        result = results.get(name, {}) if isinstance(results, dict) else {}
        evidence = inbox / (name + '.log')
        exists = evidence.is_file() and evidence.stat().st_size > 0
        ok = passed(result) and exists
        verdict = verdict and ok
        rows.append({'behavior': name, 'status': 'passed' if ok else 'failed',
                     'evidence': name + '.log' if exists else 'missing required log',
                     'operation': result})
    status = 'passed' if verdict else 'failed'
    observed_candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
    environment = {'platform': platform.platform(), 'machine': platform.machine(),
                   'python': sys.version, 'candidate': observed_candidate, 'requested_candidate': candidate, 'base': base,
                   'api_version': api,
                   'tools': 'Exact command/tool versions are recorded in each behavior log.'}
    (outbox / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
    (outbox / 'results.json').write_text(json.dumps({'status': status, 'behaviors': rows}, indent=2) + '\n')
    lines = ['# Root verification: ' + status, '', 'Candidate: ' + observed_candidate, 'Caller candidate: ' + candidate,
             'Base: ' + base, '', 'All checks run at the repository root.', '']
    lines.extend('- ' + row['behavior'] + ': ' + row['status'] + ' (' + row['evidence'] + ')' for row in rows)
    lines += ['', 'Held: browser/Mermaid rendering and external-link availability. Root has no GitHub Actions.',
              'Docker, alternate platforms, privileged mounts, cloud APIs and publication are outside this hook.']
    (outbox / 'verification.md').write_text('\n'.join(lines) + '\n')
    # Only emitted after every required report has been written successfully.
    return status


if __name__ == '__main__':
    print(summarize(json.loads(os.environ['RESULTS']), Path(os.environ['INBOX']),
                    Path(os.environ['OUTBOX']), os.environ['CANDIDATE'],
                    os.environ['BASE'], os.environ['API_VERSION']))
