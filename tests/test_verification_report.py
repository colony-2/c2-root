"""Failure mechanics for required results, logs and report generation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verification_report', ROOT / 'scripts/verification_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class VerificationReport(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='root-report-test-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.inbox = self.folder / 'inbox'
        self.outbox = self.folder / 'outbox'
        self.inbox.mkdir()
        self.outbox.mkdir()
        for name in report.BEHAVIORS:
            (self.inbox / (name + '.log')).write_text('Real check evidence\n')
        self.results = {name: {'success': True, 'exit_code': 0, 'timed_out': False}
                        for name in report.BEHAVIORS}

    def summarize(self):
        return report.summarize(self.results, self.inbox, self.outbox,
                                'candidate $(never-execute)', 'base', 'c2.build-hook/v1')

    def test_pass_requires_all_checks_and_reports(self):
        self.assertEqual(self.summarize(), 'passed')
        for name in ['environment.json', 'results.json', 'verification.md']:
            self.assertTrue((self.outbox / name).is_file())
        self.assertEqual(json.loads((self.outbox / 'results.json').read_text())['status'], 'passed')
        environment = json.loads((self.outbox / 'environment.json').read_text())
        self.assertRegex(environment['candidate'], r'^[0-9a-f]{40}$')
        self.assertEqual(environment['requested_candidate'], 'candidate $(never-execute)')

    def test_failed_missing_timed_out_launch_error_and_malformed_results(self):
        for result in [{}, None, 'passed', {'success': True},
                       {'success': False, 'exit_code': 7, 'timed_out': False},
                       {'success': True, 'exit_code': 0, 'timed_out': True},
                       {'success': False, 'exit_code': -1, 'timed_out': False, 'error_message': 'launch failed'},
                       {'success': True, 'exit_code': '0', 'timed_out': False},
                       {'success': True, 'exit_code': False, 'timed_out': False},
                       {'success': True, 'exit_code': 0, 'timed_out': False, 'diagnostic_errors': ['lost diagnostics']}]:
            with self.subTest(result=result):
                self.results['catalog'] = result
                self.assertEqual(self.summarize(), 'failed')
        self.results = {}
        self.assertEqual(self.summarize(), 'failed')

    def test_missing_or_empty_evidence_prevents_pass(self):
        log = self.inbox / 'docs.log'
        log.unlink()
        self.assertEqual(self.summarize(), 'failed')
        log.write_text('')
        self.assertEqual(self.summarize(), 'failed')

    def test_evidence_write_failure_cannot_return_pass(self):
        original = Path.write_text
        for failed_name in ['environment.json', 'results.json', 'verification.md']:
            def fail_one(path, *args, **kwargs):
                if path.name == failed_name:
                    raise OSError('forced evidence write failure')
                return original(path, *args, **kwargs)
            with self.subTest(name=failed_name), patch.object(Path, 'write_text', fail_one):
                with self.assertRaisesRegex(OSError, 'evidence write failure'):
                    self.summarize()


if __name__ == '__main__':
    unittest.main()
