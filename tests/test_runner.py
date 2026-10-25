"""Offline, deterministic validation. NO network or real credentials."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
SOURCE = (FIXTURES / runner.FILE).read_text()
UPDATED = runner.MARKER + '# Four fictional steps\n\n1. Invent.\n2. Describe.\n3. Check.\n4. Review.\n'


class FakeGitHub:
    repository = 'example/synthetic-only'

    def __init__(self):
        self.branch = False
        self.changed = False
        self.pr = False
        self.calls = []
        self.writes = []

    def call(self, method, path, obj=None):
        self.calls.append((method, path))
        if method == 'GET' and path.startswith('/pulls?'):
            return [{'html_url': 'https://example.invalid/pr/1'}] if self.pr else []
        if method == 'GET' and path.startswith('/git/ref/heads/auto/'):
            return {'object': {'sha': 'base'}} if self.branch else None
        if method == 'GET' and path == '/git/ref/heads/main':
            return {'object': {'sha': 'base'}}
        if method == 'GET' and path.startswith('/compare/'):
            return {'status': 'ahead', 'files': [{'filename': runner.FILE}]} if self.changed else {'status': 'identical', 'files': []}
        if method == 'GET' and path.startswith('/contents/'):
            body = UPDATED if self.changed else SOURCE
            return {'sha': 'fixture-sha', 'encoding': 'base64',
                    'content': base64.b64encode(body.encode()).decode()}
        if method == 'POST' and path == '/git/refs':
            self.branch = True
            self.writes.append('reserve')
            return {'ref': obj['ref']}
        if method == 'PUT' and path.startswith('/contents/'):
            self.changed = True
            self.writes.append('file')
            assert base64.b64decode(obj['content']).decode() == UPDATED
            return {'content': {'sha': 'updated'}}
        if method == 'POST' and path == '/pulls':
            assert obj['draft'] is True
            assert obj['base'] == 'main'
            self.pr = True
            self.writes.append('draft-pr')
            return {'html_url': 'https://example.invalid/pr/1'}
        raise AssertionError(f'Unexpected {method} {path}')


def generated(original, key):
    assert original == SOURCE
    assert key == 'synthetic-test-key'
    return UPDATED

def run_fixture(api, key, generate_fn=runner.generate):
    return runner.run(api, key, generate_fn, root=FIXTURES)


class Tests(unittest.TestCase):
    def test_fixture_digest_is_pinned(self):
        self.assertEqual(runner.confirmed_public_fixture(root=FIXTURES), SOURCE)

    def test_altered_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'sandbox').mkdir()
            Path(d, runner.FILE).write_text(SOURCE + '\nprivate addition\n')
            with self.assertRaisesRegex(runner.Halt, 'digest'):
                runner.confirmed_public_fixture(root=d)

    def test_marker_required_in_model_result(self):
        with self.assertRaisesRegex(runner.Halt, 'synthetic marker'):
            runner.validate('No marker')

    def test_one_draft_pr_happy_path(self):
        api = FakeGitHub()
        state = run_fixture(api, 'synthetic-test-key', generated)
        self.assertEqual(state['status'], 'DRAFT_PR')
        self.assertEqual(api.writes, ['reserve', 'file', 'draft-pr'])
        self.assertEqual(run_fixture(api, '', lambda *_: self.fail('Model repeated'))['status'], 'COMPLETE')

    def test_failed_generation_reserves_and_prevents_repeat(self):
        api = FakeGitHub()
        with self.assertRaisesRegex(runner.Halt, 'model failed'):
            run_fixture(api, 'synthetic-test-key', lambda *_: (_ for _ in ()).throw(runner.Halt('model failed')))
        self.assertEqual(api.writes, ['reserve'])
        with self.assertRaisesRegex(runner.Halt, 'manual review'):
            run_fixture(api, 'synthetic-test-key', lambda *_: self.fail('No retry allowed'))
        self.assertEqual(api.writes, ['reserve'])

    def test_recover_saved_file_without_ai_call(self):
        api = FakeGitHub()
        api.branch = True
        api.changed = True
        state = run_fixture(api, '', lambda *_: self.fail('No second inference'))
        self.assertEqual(state['status'], 'DRAFT_PR')
        self.assertEqual(api.writes, ['draft-pr'])

    def test_missing_secret_is_blocked_without_branch(self):
        api = FakeGitHub()
        with self.assertRaisesRegex(runner.Halt, 'secret missing'):
            run_fixture(api, '')
        self.assertEqual(api.writes, [])

    def test_remote_changed_before_reservation_is_blocked(self):
        api = FakeGitHub()
        api.changed = True
        with self.assertRaisesRegex(runner.Halt, 'fixture differs'):
            run_fixture(api, 'synthetic-test-key', generated)
        self.assertEqual(api.writes, [])

    def test_default_paused_creates_no_github_call(self):
        with tempfile.TemporaryDirectory() as d:
            current = os.getcwd()
            os.chdir(d)
            try:
                with patch.dict(os.environ, {'SANDBOX_ENABLED': 'false'}, clear=True):
                    self.assertEqual(runner.main(), 0)
                    self.assertEqual(json.loads(Path('sandbox-status.json').read_text())['status'], 'PAUSED')
            finally:
                os.chdir(current)

    def test_json_model_validation(self):
        def fake_call(method, url, headers, obj):
            self.assertEqual(headers['x-goog-api-key'], 'synthetic-test-key')
            self.assertTrue(url.startswith('https://generativelanguage.googleapis.com/'))
            self.assertIn(SOURCE, obj['contents'][0]['parts'][0]['text'])
            return {'candidates': [{'content': {'parts': [{'text': json.dumps({'content': UPDATED})}]}}]}
        self.assertEqual(runner.generate(SOURCE, 'synthetic-test-key', fake_call), UPDATED)

    def test_invalid_json_from_model_blocks(self):
        def fake_call(*_):
            return {'candidates': [{'content': {'parts': [{'text': 'not-json'}]}}]}
        with self.assertRaisesRegex(runner.Halt, 'Invalid model response'):
            runner.generate(SOURCE, 'synthetic-test-key', fake_call)


if __name__ == '__main__':
    unittest.main()
