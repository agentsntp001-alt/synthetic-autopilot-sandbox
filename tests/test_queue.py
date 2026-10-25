"""Integration tests: real queue orchestration, fake GitHub/Gemini; no network."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import autopilot_queue as queue

ROOT=Path(__file__).resolve().parents[1]
APPROVED=queue.load_approved(ROOT)


def scripted(task,source,key):
    if key!='test-only':
        raise AssertionError('Wrong fake key')
    return source + '\n<!-- Synthetic review step added. -->\n' if task['path'].endswith('.md') else source.replace('</body>','<footer>Fictional progress reviewed</footer></body>')


class FakeAPI:
    repository=queue.OWNER_REPO
    def __init__(self):
        self.branches=set()
        self.changed={}
        self.prs={}
        self.writes=[]
        self.closed=set()
        self.owners={2:'OWNER',3:'OWNER'}
        self.base='base123'
        self.other_change=False
        self.calls=[]

    def call(self,method,path,obj=None):
        self.calls.append((method,path))
        if method=='GET' and path.startswith('/issues/'):
            n=int(path.split('/')[-1])
            return {'number':n,'state':'closed' if n in self.closed else 'open',
                    'author_association':self.owners.get(n,'NONE')}
        if method=='GET' and path.startswith('/pulls?'):
            from urllib.parse import parse_qs
            branch=parse_qs(path.split('?',1)[1]).get('head',[':'])[0].split(':',1)[-1]
            return [self.prs[branch]] if branch in self.prs else []
        if method=='GET' and path.startswith('/git/ref/heads/auto/'):
            return {'object':{'sha':self.base}} if path.rsplit('/',1)[-1] in self.branches else None
        if method=='GET' and path=='/git/ref/heads/main':
            return {'object':{'sha':self.base}}
        if method=='GET' and path.startswith('/contents/'):
            from urllib.parse import unquote
            filepath=unquote(path.split('/contents/',1)[1].split('?')[0])
            branch=path.split('ref=',1)[1] if 'ref=' in path else 'main'
            text=self.changed.get(filepath,Path(ROOT,filepath).read_text()) if branch!='main' else Path(ROOT,filepath).read_text()
            if self.other_change and branch=='main':
                text += ' altered'
            return {'encoding':'base64','sha':'filesha',
                    'content':base64.b64encode(text.encode()).decode()}
        if method=='GET' and path.startswith('/compare/'):
            branch=path.rsplit('/',1)[-1]
            data=next((t for t in APPROVED if 'synthetic-'+t['id']==branch),None)
            if data and data['path'] in self.changed:
                return {'status':'ahead','files':[{'filename':data['path']}]}
            return {'status':'identical','files':[]}
        if method=='POST' and path=='/git/refs':
            self.branches.add(obj['ref'].rsplit('/',1)[-1]);self.writes.append(('reserve',obj['ref']))
            return {'ref':obj['ref']}
        if method=='PUT' and path.startswith('/contents/'):
            from urllib.parse import unquote
            filepath=unquote(path.split('/contents/',1)[1]);self.changed[filepath]=base64.b64decode(obj['content']).decode()
            self.writes.append(('file',filepath));return {'content':{'sha':'new'}}
        if method=='POST' and path=='/pulls':
            assert obj['draft'] is True and obj['base']=='main'
            self.prs[obj['head']]={'html_url':'https://example.invalid/pr/'+obj['head']}
            self.writes.append(('pr',obj['head']))
            return self.prs[obj['head']]
        raise AssertionError('Unexpected '+method+' '+path)


class QueueTests(unittest.TestCase):
    def test_source_manifest_has_two_reviewed_public_files(self):
        self.assertEqual(len(APPROVED),2)
        for task in APPROVED:
            self.assertTrue(queue.read_local_fixture(ROOT,task).startswith(queue.MARKER))

    def test_reject_unapproved_path(self):
        task={**APPROVED[0],'path':'../company/secrets.md'}
        with tempfile.TemporaryDirectory() as d:
            obj={'schema':1,'tasks':[task]};p=Path(d,'tasks');p.mkdir()
            (p/'approved.json').write_text(json.dumps(obj))
            with self.assertRaises(queue.Halt):queue.load_approved(Path(d))

    def test_manifest_rejects_repeated_issue(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d,'tasks');p.mkdir()
            (p/'approved.json').write_text(json.dumps({'schema':1,'tasks':[APPROVED[0],{**APPROVED[1],'issue':2}]}))
            with self.assertRaisesRegex(queue.Halt,'Duplicate'):queue.load_approved(Path(d))

    def test_entire_pipeline_two_real_issues_two_draft_prs(self):
        api=FakeAPI();state=queue.work_queue(api,'test-only',ROOT,scripted)
        self.assertEqual(state['status'],'PROCESSED')
        self.assertEqual(state['attempted'],2)
        self.assertEqual([s['state'] for s in state['results']],['NEW','NEW'])
        self.assertEqual([x[0] for x in api.writes],['reserve','file','pr','reserve','file','pr'])
        again=queue.work_queue(api,'test-only',ROOT,lambda *args:self.fail('No second Gemini calls'))
        self.assertEqual([s['state'] for s in again['results']],['DONE','DONE'])
        self.assertEqual(len(api.writes),6)

    def test_failed_model_call_reserves_branch_and_continues(self):
        api=FakeAPI();calls=[]
        def model(task,source,key):
            calls.append(task['id'])
            if task['id']==APPROVED[0]['id']:raise queue.Halt('Synthetic provider outage')
            return scripted(task,source,key)
        state=queue.work_queue(api,'test-only',ROOT,model)
        self.assertEqual([s['state'] for s in state['results']],['BLOCKED','NEW'])
        self.assertEqual(len(calls),2)
        second=queue.work_queue(api,'test-only',ROOT,lambda *args:self.fail('No repeat'))
        self.assertEqual([s['state'] for s in second['results']],['BLOCKED','DONE'])
        self.assertEqual(len(api.writes),4)

    def test_recover_after_file_commit_without_model(self):
        api=FakeAPI()
        task=APPROVED[0]
        api.branches.add('synthetic-'+task['id'])
        api.changed[task['path']]=scripted(task,Path(ROOT,task['path']).read_text(),'test-only')
        s=queue.process_task(api,task,'',ROOT,lambda *args:self.fail('No inference'))
        self.assertEqual(s['state'],'RECOVERED');self.assertEqual(api.writes[0][0],'pr')

    def test_empty_reserved_branch_requires_manual_review(self):
        api=FakeAPI();api.branches.add('synthetic-'+APPROVED[0]['id'])
        with self.assertRaisesRegex(queue.Halt,'manual review'):
            queue.process_task(api,APPROVED[0],'',ROOT,lambda *args:self.fail('No inference'))

    def test_remote_source_mismatch_prevents_reservation(self):
        api=FakeAPI();api.other_change=True
        with self.assertRaisesRegex(queue.Halt,'Remote fixture'):
            queue.process_task(api,APPROVED[0],'test-only',ROOT,scripted)
        self.assertFalse(api.writes)

    def test_untrusted_author_cannot_trigger_model(self):
        api=FakeAPI();api.owners[2]='NONE'
        s=queue.process_task(api,APPROVED[0],'test-only',ROOT,lambda *a:self.fail('No call'))
        self.assertEqual(s['state'],'SKIP');self.assertFalse(api.writes)

    def test_closed_issue_cannot_trigger_model(self):
        api=FakeAPI();api.closed.add(3)
        s=queue.process_task(api,APPROVED[1],'test-only',ROOT,lambda *a:self.fail('No call'))
        self.assertEqual(s['state'],'SKIP');self.assertFalse(api.writes)

    def test_no_secret_does_not_consume_attempt(self):
        api=FakeAPI()
        with self.assertRaisesRegex(queue.Halt,'key missing'):
            queue.process_task(api,APPROVED[0],'',ROOT,scripted)
        self.assertFalse(api.writes)

    def test_block_other_repository_identity(self):
        api=FakeAPI();api.repository='corporate/private-repo'
        with self.assertRaisesRegex(queue.Halt,'prohibited'):
            queue.work_queue(api,'test-only',ROOT,scripted)
        self.assertFalse(api.calls)

    def test_html_rejects_external_or_active_content(self):
        original=Path(ROOT,'sandbox/dashboard.html').read_text()
        for code in ('<script src="app.js"></script>','<img src="https://evil.invalid/">','<iframe></iframe>','onload=alert(1)'):
            with self.subTest(code=code):
                with self.assertRaisesRegex(queue.Halt,'forbidden|event handlers'):
                    queue.validate_fixture(APPROVED[1]['path'],original+code,queue.MAX_BYTES_OUT)

    def test_model_json_roundtrip_and_no_issue_body(self):
        task=APPROVED[0];source=Path(ROOT,task['path']).read_text()
        def fake_transport(method,url,headers,payload):
            self.assertEqual(headers['x-goog-api-key'],'test-only')
            self.assertEqual(queue.MODEL,'gemini-3.5-flash-lite')
            prompt=payload['contents'][0]['parts'][0]['text']
            self.assertIn(task['goal'],prompt)
            self.assertNotIn('sensitive-private-issue-body',prompt)
            self.assertIn(source,prompt)
            return {'candidates':[{'content':{'parts':[{'text':json.dumps({'content':scripted(task,source,'test-only')})}]}}]}
        self.assertEqual(queue.generate(task,source,'test-only',fake_transport),scripted(task,source,'test-only'))

    def test_model_invalid_json_is_blocked(self):
        def fake_transport(*args):return {'candidates':[{'content':{'parts':[{'text':'not-json'}]}}]}
        with self.assertRaisesRegex(queue.Halt,'Invalid model'):
            queue.generate(APPROVED[0],Path(ROOT,APPROVED[0]['path']).read_text(),'test-only',fake_transport)

    def test_default_main_paused_writes_safe_status(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d,'state.json')
            with patch.dict(os.environ,{'SANDBOX_ENABLED':'false'},clear=True):
                with patch('sys.argv',['autopilot_queue.py','--output',str(out)]):
                    with patch('autopilot_queue.GitHub') as forbidden:
                        self.assertEqual(queue.main(),0)
                        forbidden.assert_not_called()
            self.assertEqual(json.loads(out.read_text())['status'],'PAUSED')

    def test_exception_string_and_canary_not_leaked(self):
        class Broken(FakeAPI):
            def call(self,*args,**kwargs):
                raise KeyError('CANARY_SECRET_TEST_ONLY')
        state=queue.work_queue(Broken(),'test-only',ROOT,scripted)
        self.assertNotIn('CANARY_SECRET_TEST_ONLY',json.dumps(state))
        self.assertEqual(state['results'][0]['state'],'BLOCKED')

if __name__=='__main__':unittest.main()
