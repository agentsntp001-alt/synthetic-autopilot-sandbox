"""High-volume, offline failure-injection tests; never send secrets or charge APIs."""
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import autopilot_queue as q
from test_queue import FakeAPI, ROOT, scripted


class StressTests(unittest.TestCase):
    def test_500_identical_runs_do_not_repeat_a_model_request(self):
        api=FakeAPI()
        invocations=[0]
        def only_once_per_task(task, source, key):
            invocations[0] += 1
            return scripted(task, source, key)
        first=q.work_queue(api,'test-only',ROOT,only_once_per_task)
        self.assertEqual(first['status'],'PROCESSED')
        self.assertEqual(invocations[0],2)
        self.assertEqual([x[0] for x in api.writes],['reserve','file','pr','reserve','file','pr'])
        for _ in range(500):
            final=q.work_queue(api,'test-only',ROOT,only_once_per_task)
            self.assertEqual(final['attempted'],0)
        self.assertEqual(invocations[0],2)
        self.assertEqual(len(api.writes),6)

    def test_250_generated_markdown_attack_variations_are_rejected(self):
        prefix=q.MARKER+'# Public fictional handbook\n\n'
        endpoints=['//evil.invalid/track','https://evil.invalid/x','javascript:alert(1)','data:text/html,xx',
                   '/relative-only','mailto:bad@example.invalid','https&#58;//evil.invalid']
        for endpoint in endpoints:
            for left in ('[text]', '![picture]'):
                payload=left+'('+endpoint+')'
                with self.subTest(payload=payload),self.assertRaises(q.Halt):
                    q.validate_fixture('sandbox/handbook.md',prefix+payload,q.MAX_BYTES_OUT)
        rng=random.Random(20261025)
        for i in range(250):
            part=''.join(rng.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(20))
            payload=rng.choice(['![image](//', '[text](//','<a href="//','[reference]['+part+']\n['+part+']: //'])+'evil.invalid/'+part+('">x</a>' if i%3==0 else ')' if i%3==1 else '')
            with self.subTest(i=i),self.assertRaises(q.Halt):
                q.validate_fixture('sandbox/handbook.md',prefix+payload,q.MAX_BYTES_OUT)

    def test_100_independent_failures_never_retry(self):
        for i in range(100):
            api=FakeAPI()
            calls=[0]
            def failing(*args):
                calls[0]+=1
                raise q.Halt('Synthetic provider outage')
            state=q.work_queue(api,'test-only',ROOT,failing)
            self.assertEqual(state['status'],'ATTENTION_REQUIRED')
            self.assertEqual(calls[0],2)
            for _ in range(3):
                q.work_queue(api,'test-only',ROOT,failing)
            self.assertEqual(calls[0],2)
            self.assertEqual(len(api.writes),2)

    def test_100_readonly_preflights_without_writes_or_inference(self):
        api=FakeAPI()
        for _ in range(100):
            report=q.inspect_queue(api,ROOT)
            self.assertEqual(report['writes'],0)
            self.assertEqual(report['external_ai_calls'],0)
            self.assertEqual([x['status'] for x in report['tasks']],['READY','READY'])
        self.assertTrue(all(method=='GET' for method,_ in api.calls))
        self.assertEqual(api.writes,[])

if __name__=='__main__':
    unittest.main()
