"""Validate the actual PR checkout as well as fixed offline regression fixtures.

This guards model-written output without assuming that it matches the original
approved source checksum. Unit tests use immutable tests/fixtures instead.
"""
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import autopilot_queue as queue


class CheckedOutContentTests(unittest.TestCase):
    def test_every_proposed_public_fixture_passes_output_safety_rules(self):
        for path in ('sandbox/handbook.md', 'sandbox/dashboard.html'):
            with self.subTest(path=path):
                text = (PROJECT / path).read_text(encoding='utf-8')
                self.assertEqual(queue.validate_fixture(path, text, queue.MAX_BYTES_OUT), text)

    def test_manifest_and_regression_inputs_remain_pinned(self):
        baseline = PROJECT / 'tests' / 'fixtures'
        for task in queue.load_approved(baseline):
            with self.subTest(path=task['path']):
                self.assertTrue(queue.read_local_fixture(baseline, task).startswith(queue.MARKER))


if __name__ == '__main__':
    unittest.main()
