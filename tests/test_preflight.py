"""Offline adversarial checks of the real read-only GitHub preflight and renderer."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autopilot_queue as q
from test_queue import FakeAPI


class ReadOnlyPreflightTests(unittest.TestCase):
    def test_two_real_synthetic_tasks_ready_and_zero_writes(self):
        api = FakeAPI()
        result = q.inspect_queue(api, ROOT)
        self.assertEqual(result['status'], 'PREFLIGHT')
        self.assertEqual([x['status'] for x in result['tasks']], ['READY', 'READY'])
        self.assertEqual(result['external_ai_calls'], 0)
        self.assertFalse(result['environment_and_billing_verified'])
        self.assertEqual(result['writes'], 0)
        self.assertTrue(all(method == 'GET' for method, _ in api.calls))

    def test_both_existing_prs_not_reprocessed(self):
        api = FakeAPI()
        for row in q.load_approved(ROOT):
            api.prs['auto/synthetic-' + row['id']] = {'html_url': 'https://example.invalid/pr/1'}
        res = q.inspect_queue(api, ROOT)
        self.assertEqual([x['status'] for x in res['tasks']], ['PR_EXISTS', 'PR_EXISTS'])
        self.assertFalse(api.writes)

    def test_reserved_branch_is_review_not_new_inference(self):
        api = FakeAPI()
        api.branches.add('synthetic-handbook-v1')
        res = q.inspect_queue(api, ROOT)
        self.assertEqual([x['status'] for x in res['tasks']], ['REVIEW_RESERVED_BRANCH', 'READY'])
        self.assertEqual(res['external_ai_calls'], 0)

    def test_external_source_changed_fails_preflight(self):
        api = FakeAPI()
        api.other_change = True
        res = q.inspect_queue(api, ROOT)
        self.assertEqual(res['status'], 'BLOCKED')
        self.assertEqual([x['status'] for x in res['tasks']], ['BLOCKED', 'BLOCKED'])
        self.assertFalse(api.writes)

    def test_closed_and_untrusted_issues_skipped(self):
        api = FakeAPI()
        api.closed.add(2)
        api.owners[3] = 'NONE'
        res = q.inspect_queue(api, ROOT)
        self.assertEqual([x['status'] for x in res['tasks']], ['SKIP', 'SKIP'])
        self.assertFalse(api.writes)

    def test_preflight_rejects_non_sandbox_repository(self):
        api = FakeAPI()
        api.repository = 'example/private-company'
        with self.assertRaisesRegex(q.Halt, 'prohibited'):
            q.inspect_queue(api, ROOT)
        self.assertFalse(api.calls)

    def test_cli_read_only_without_activation_or_gemini_key(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as temp:
            status_file = Path(temp, 'status.json')
            with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/main',
                                         'GITHUB_REPOSITORY': q.OWNER_REPO,
                                         'GITHUB_TOKEN': 'fake-github-only',
                                         'SANDBOX_ENABLED': 'false'}, clear=True):
                with patch('autopilot_queue.GitHub', return_value=api), \
                        patch('autopilot_queue.generate') as forbidden:
                    with patch('sys.argv', ['autopilot_queue.py', '--dry-run', '--output', str(status_file)]):
                        self.assertEqual(q.main(), 0)
                    forbidden.assert_not_called()
            report = json.loads(status_file.read_text())
            self.assertEqual(report['status'], 'PREFLIGHT')
            self.assertEqual(report['writes'], 0)
            self.assertFalse(api.writes)

    def test_cli_off_main_does_not_call_github_or_gemini(self):
        with tempfile.TemporaryDirectory() as temp:
            report_file = Path(temp, 'report.json')
            with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/untrusted-branch'}, clear=True):
                with patch('autopilot_queue.GitHub') as github, patch('autopilot_queue.generate') as model:
                    with patch('sys.argv', ['autopilot_queue.py', '--dry-run', '--output', str(report_file)]):
                        self.assertEqual(q.main(), 1)
                    github.assert_not_called()
                    model.assert_not_called()
            self.assertNotIn('untrusted-branch', report_file.read_text())

    def test_multi_task_blockers_surface_job_failure(self):
        api = FakeAPI()
        def faulty(task, text, key):
            raise q.Halt('provider failed')
        result = q.work_queue(api, 'test-only', ROOT, faulty)
        self.assertEqual(result['status'], 'ATTENTION_REQUIRED')
        self.assertEqual(result['blocked_count'], 2)
        self.assertEqual(result['attempted'], 2)
        self.assertEqual(len(api.writes), 2)  # Both model attempts reserved, no data written.
        again = q.work_queue(api, 'test-only', ROOT, lambda *a: self.fail('no retries'))
        self.assertEqual(again['status'], 'ATTENTION_REQUIRED')
        self.assertEqual(len(api.writes), 2)

    def test_error_message_never_exposes_canary_secrets(self):
        api = FakeAPI()
        def throw(method, path, obj=None):
            raise RuntimeError('CANARY_SUPER_SECRET_123')
        api.call = throw
        result = q.inspect_queue(api, ROOT)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotIn('CANARY', json.dumps(result))


class UntrustedOutputTests(unittest.TestCase):
    def test_known_static_dashboard_is_allowed(self):
        html = (ROOT / 'sandbox/dashboard.html').read_text()
        self.assertEqual(q.validate_fixture('sandbox/dashboard.html', html, q.MAX_BYTES_OUT), html)

    def test_unknown_html_elements_rejected(self):
        html = (ROOT / 'sandbox/dashboard.html').read_text()
        for payload in ('<svg><animate></animate></svg>', '<math></math>',
                        '<audio></audio>', '<script>alert(1)</script>'):
            with self.subTest(payload=payload), self.assertRaises(q.Halt):
                q.validate_fixture('sandbox/dashboard.html', html + payload, q.MAX_BYTES_OUT)

    def test_inline_events_and_remote_links_rejected(self):
        html = (ROOT / 'sandbox/dashboard.html').read_text()
        for payload in ('<div onclick="evil()">x</div>', '<a href="https://evil.invalid">x</a>',
                        '<style>@import "evil";</style>', '<style>body{background:url (evil)}</style>',
                        '<img src=x>', '<div style="color:red">x</div>'):
            with self.subTest(payload=payload), self.assertRaises(q.Halt):
                q.validate_fixture('sandbox/dashboard.html', html + payload, q.MAX_BYTES_OUT)

    def test_markdown_script_and_remote_exfil_rejected(self):
        marker = q.MARKER + '# A fictional handbook\n'
        for payload in ('[click](https://example.invalid)', '<script>alert(1)</script>',
                        '<svg onload=alert(1)>', 'data:text/html,hello'):
            with self.subTest(payload=payload), self.assertRaises(q.Halt):
                q.validate_fixture('sandbox/handbook.md', marker + payload, q.MAX_BYTES_OUT)

    def test_known_key_patterns_and_corporate_terms_rejected(self):
        marker = q.MARKER + '# Fictional note\n'
        for payload in ('AIza' + 'A' * 34, '-----BEGIN PRIVATE KEY-----',
                        'Swiss Novatech', 'Swissmedic', 'GACP'):
            with self.subTest(payload=payload), self.assertRaises(q.Halt):
                q.validate_fixture('sandbox/handbook.md', marker + payload, q.MAX_BYTES_OUT)


if __name__ == '__main__':
    unittest.main()
