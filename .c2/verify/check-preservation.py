"""Check actual hook command preservation in disposable Git candidates.

This uses installed tools, not package provisioning or the recipe compiler.
Cancellation here establishes command-level preservation, not typed propagation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if '.git' in relative.parts:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            value = {'target': os.readlink(path)}
        elif stat.S_ISREG(mode):
            value = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        else:
            continue
        result[str(relative)] = dict(value, mode=oct(stat.S_IMODE(mode)))
    return result


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    hook = json.loads((ROOT / '.c2/recipes/hooks/build/verify.yaml').read_text())
    files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    results = []
    for scenario in ['success', 'failure', 'cancellation']:
        with tempfile.TemporaryDirectory(prefix='root-preservation-') as folder:
            scratch = Path(folder)
            candidate = scratch / 'candidate'
            candidate.mkdir()
            for name in files:
                source = ROOT / name
                destination = candidate / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination, follow_symlinks=False)
            subprocess.run(['git', 'init', '-q', str(candidate)], check=True)
            subprocess.run(['git', 'add', '.'], cwd=candidate, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'Candidate fixture'], cwd=candidate, check=True)
            canaries = candidate / 'untracked canaries'
            canaries.mkdir()
            (canaries / 'binary').write_bytes(bytes(range(256)))
            (canaries / 'binary').chmod(0o640)
            (canaries / 'executable').write_text('#!/bin/sh\nexit 0\n')
            (canaries / 'executable').chmod(0o751)
            (canaries / 'empty').touch(mode=0o600)
            (canaries / 'link').symlink_to('binary')
            before = manifest(candidate)
            evidence = output / scenario
            evidence.mkdir()
            operations = {}
            for node in hook['sequence']:
                name = node['id']
                inbox = scratch / (name + '-inbox')
                outbox = scratch / (name + '-outbox')
                inbox.mkdir()
                outbox.mkdir()
                if name == 'summarize':
                    for prior in ['catalog', 'acceptance', 'docs']:
                        log = scratch / (prior + '-outbox') / (prior + '.log')
                        if log.exists():
                            shutil.copyfile(log, inbox / log.name)
                env = {'PATH': os.environ['PATH'], 'HOME': str(scratch),
                       'PYTHONDONTWRITEBYTECODE': '1', 'OUTBOX': str(outbox),
                       'INBOX': str(inbox), 'CANDIDATE': 'candidate $(false)',
                       'BASE': 'base `false`', 'API_VERSION': 'c2.build-hook/v1',
                       'RESULTS': json.dumps(operations)}
                command = node['inputs']['run']
                if name == 'catalog' and scenario == 'failure':
                    command += '\necho forced-preservation-failure >&2; exit 7\n'
                ready = scratch / 'cancel-ready'
                if name == 'catalog' and scenario == 'cancellation':
                    env['CANCEL_READY'] = str(ready)
                    command += '\nprintf ready > "$CANCEL_READY"\nsleep 60 &\nwait\n'
                started = time.monotonic()
                process = subprocess.Popen(['bash', '-c', command], cwd=candidate, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True, text=True)
                if scenario == 'cancellation' and name == 'catalog':
                    while not ready.exists() and process.poll() is None and time.monotonic() - started < 30:
                        time.sleep(0.02)
                    if not ready.exists():
                        os.killpg(process.pid, signal.SIGKILL)
                        raise RuntimeError('Cancellation probe did not reach its ready marker')
                    os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=35)
                operations[name] = {'success': process.returncode == 0, 'exit_code': process.returncode,
                                    'timed_out': False, 'stdout': stdout, 'stderr': stderr}
                for artifact in outbox.iterdir():
                    shutil.copy2(artifact, evidence / artifact.name)
                if scenario == 'cancellation':
                    if process.returncode == 0:
                        raise AssertionError('Cancelled command returned success')
                    break
            after = manifest(candidate)
            if before != after:
                raise AssertionError('Candidate bytes, modes or symlink targets changed: ' + scenario)
            if scenario != 'cancellation':
                expected = 'passed' if scenario == 'success' else 'failed'
                if operations['summarize']['stdout'].strip() != expected:
                    raise AssertionError('Incorrect aggregate: ' + scenario)
            record = {'scenario': scenario, 'preserved': True, 'before': before, 'after': after,
                      'operations': operations,
                      'scope': 'Actual hook shell commands, installed tools, disposable tracked/untracked candidate; no compiler or package-resolution claim.'}
            (evidence / 'preservation.json').write_text(json.dumps(record, indent=2) + '\n')
            results.append({'scenario': scenario, 'preserved': True})
    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
