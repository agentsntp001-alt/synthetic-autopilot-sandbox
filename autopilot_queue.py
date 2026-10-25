#!/usr/bin/env python3
"""Bounded public-only GitHub issue queue -> Gemini -> draft PR, no auto-merge.

Every possible external input is gated by a commit-reviewed task manifest.
The untrusted issue body is NEVER forwarded to the model or to a log.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from runner import GitHub, Halt, request_json

OWNER_REPO = 'agentsntp001-alt/synthetic-autopilot-sandbox'
MODEL = 'gemini-3.5-flash-lite'
MARKER = '<!-- PUBLIC_SYNTHETIC_ONLY -->\n'
MAX_TASKS = 8
MAX_PER_RUN = 2
MAX_BYTES_IN = 12000
MAX_BYTES_OUT = 16000
MAX_TASK_GOAL = 600
MAX_MODEL_TOKENS = 3072
ID_PATTERN = re.compile(r'[a-z][a-z0-9-]{2,49}\Z')
HEX_PATTERN = re.compile(r'[a-f0-9]{64}\Z')
PATH_PATTERN = re.compile(r'sandbox/[A-Za-z0-9_-]+\.(?:md|html)\Z')


def load_approved(root):
    path = root / 'tasks' / 'approved.json'
    if path.stat().st_size > 12000:
        raise Halt('Approved queue too large')
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        raise Halt('Approved queue unreadable') from None
    if not isinstance(obj, dict) or set(obj) != {'schema', 'tasks'} or obj['schema'] != 1:
        raise Halt('Invalid approved queue schema')
    tasks = obj['tasks']
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise Halt('Invalid task count')
    seen_ids, seen_issues, seen_paths = set(), set(), set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {'id', 'issue', 'path', 'goal', 'sha256'}:
            raise Halt('Invalid task schema')
        ident, issue, filepath, goal, sha = (task[k] for k in ('id', 'issue', 'path', 'goal', 'sha256'))
        if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident):
            raise Halt('Invalid task ID')
        if type(issue) is not int or not 1 <= issue <= 1_000_000:
            raise Halt('Invalid issue number')
        if not isinstance(filepath, str) or not PATH_PATTERN.fullmatch(filepath):
            raise Halt('Only direct public Markdown/HTML fixtures are allowed')
        if not isinstance(goal, str) or not 16 <= len(goal) <= MAX_TASK_GOAL or any(ord(c) < 32 and c not in '\n\t' for c in goal):
            raise Halt('Invalid approved objective')
        if not isinstance(sha, str) or not HEX_PATTERN.fullmatch(sha):
            raise Halt('Invalid source checksum')
        if ident in seen_ids or issue in seen_issues or filepath in seen_paths:
            raise Halt('Duplicate task, issue or file')
        seen_ids.add(ident); seen_issues.add(issue); seen_paths.add(filepath)
    return tasks


def validate_fixture(path, content, max_bytes):
    if not PATH_PATTERN.fullmatch(path):
        raise Halt('Unsafe proposed path')
    if not isinstance(content, str) or not content.startswith(MARKER):
        raise Halt('Synthetic marker missing')
    if not 1 <= len(content.encode('utf-8')) <= max_bytes:
        raise Halt('Proposed content exceeds size limit')
    if path.endswith('.html'):
        lowered = content.casefold()
        # No script execution, external resources, embedded frames or redirect instructions.
        for forbidden in ('<script', '<iframe', '<object', '<embed', '<link', '<base',
                          '<form', '<meta http-equiv', 'http://', 'https://', 'javascript:',
                          '@import', 'url('):
            if forbidden in lowered:
                raise Halt('HTML contains forbidden active or remote content')
        if re.search(r'\bon[a-z]+\s*=', lowered) or re.search(r'\b(?:src|srcdoc)\s*=', lowered):
            raise Halt('HTML contains event handlers or embedded content')
        if '<!doctype html>' not in lowered:
            raise Halt('Proposed HTML document incomplete')
    return content


def read_local_fixture(root, task):
    file_path = root / task['path']
    try:
        raw = file_path.read_bytes()
    except OSError:
        raise Halt('Reviewed fixture missing') from None
    if len(raw) > MAX_BYTES_IN or hashlib.sha256(raw).hexdigest() != task['sha256']:
        raise Halt('Fixture checksum differs from reviewed source')
    try:
        return validate_fixture(task['path'], raw.decode('utf-8'), MAX_BYTES_IN)
    except UnicodeError:
        raise Halt('Fixture encoding invalid') from None


def generate(task, source, key, transport=request_json):
    if not key:
        raise Halt('Gemini key is absent')
    # No untrusted issue body, attachments, comments or other repositories enter this prompt.
    prompt = ('You are improving one fictional PUBLIC synthetic sample. Do not request private '
              'content, secrets, tools, network requests, external scripts or company data. '
              'Return JSON exactly {"content":"full rewritten file"}, with the exact first '
              'line marker preserved. Keep the file standalone, accessible and syntactically '
              'valid. Task: ' + task['goal'] + '\nPUBLIC FIXTURE:\n' + source)
    req = {'contents':[{'role':'user','parts':[{'text':prompt}]}],
           'generationConfig':{'responseMimeType':'application/json',
                               'temperature':0.1,'maxOutputTokens':MAX_MODEL_TOKENS}}
    url = 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent'
    response = transport('POST',url,{'x-goog-api-key':key,'Content-Type':'application/json'},req)
    try:
        plain = ''.join(p['text'] for p in response['candidates'][0]['content']['parts'] if 'text' in p)
        obj = json.loads(plain)
        if not isinstance(obj,dict) or set(obj) != {'content'}:
            raise ValueError('schema')
        content = validate_fixture(task['path'],obj['content'],MAX_BYTES_OUT)
    except Halt:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise Halt('Invalid model reply') from None
    if content == source:
        raise Halt('Model did not change the approved fixture')
    return content


def is_trusted_open_issue(issue, number):
    return (isinstance(issue,dict) and issue.get('number')==number and
            issue.get('state')=='open' and 'pull_request' not in issue and
            issue.get('author_association') in {'OWNER','MEMBER','COLLABORATOR'})


def existing_pr(api, branch):
    from urllib.parse import urlencode
    owner = api.repository.split('/')[0]
    res = api.call('GET','/pulls?'+urlencode({'head':owner+':'+branch,'state':'all','per_page':10}))
    if not isinstance(res,list) or len(res)>=10:
        raise Halt('Unable to determine existing proposals')
    return res[0] if res else None


def validate_remote_original(api, task, local_text):
    from urllib.parse import quote
    data = api.call('GET','/contents/'+quote(task['path'],safe='/')+'?ref=main')
    if not isinstance(data,dict) or data.get('encoding')!='base64' or not data.get('sha'):
        raise Halt('Remote source cannot be verified')
    try:
        blob = base64.b64decode(''.join(data['content'].split()),validate=True)
    except (ValueError,KeyError,TypeError):
        raise Halt('Remote fixture invalid') from None
    if hashlib.sha256(blob).hexdigest()!=task['sha256'] or blob!=local_text.encode('utf-8'):
        raise Halt('Remote fixture no longer matches approval')
    return data['sha']


def recover(api, task, branch):
    from urllib.parse import quote
    delta = api.call('GET','/compare/main...'+quote(branch,safe='/'))
    if not isinstance(delta,dict) or delta.get('status')!='ahead':
        raise Halt('Reserved task requires manual review; no repeated inference')
    changes=delta.get('files') or []
    if len(changes)!=1 or changes[0].get('filename')!=task['path']:
        raise Halt('Reserved branch contains unapproved modifications')
    saved=api.call('GET','/contents/'+quote(task['path'],safe='/')+'?ref='+quote(branch,safe='/'))
    if not isinstance(saved,dict) or saved.get('encoding')!='base64':
        raise Halt('Cannot safely recover proposal')
    try:
        text=base64.b64decode(''.join(saved['content'].split()),validate=True).decode('utf-8')
    except (KeyError,TypeError,UnicodeError,ValueError):
        raise Halt('Unreadable recovered proposal') from None
    validate_fixture(task['path'],text,MAX_BYTES_OUT)
    return text


def process_task(api, task, key, root, model_fn=generate):
    from urllib.parse import quote
    issue=api.call('GET','/issues/'+str(task['issue']))
    if not is_trusted_open_issue(issue,task['issue']):
        return {'task':task['id'],'state':'SKIP','reason':'Approved owner issue missing or closed'}
    branch='auto/synthetic-'+task['id']
    prior=existing_pr(api,branch)
    if prior:
        return {'task':task['id'],'state':'DONE','reason':'Existing PR found'}
    reserved=api.call('GET','/git/ref/heads/'+branch)
    if reserved:
        recover(api,task,branch)
        phase='RECOVERED'
    else:
        source=read_local_fixture(root,task)
        current=api.call('GET','/git/ref/heads/main')
        if not isinstance(current,dict) or not current.get('object',{}).get('sha'):
            raise Halt('Cannot verify main')
        base=current['object']['sha']
        remote_sha=validate_remote_original(api,task,source)
        if not key:
            raise Halt('Gemini key missing; no attempt reserved')
        # Reserve durable branch FIRST. This is a one-try transaction by task ID.
        api.call('POST','/git/refs',{'ref':'refs/heads/'+branch,'sha':base})
        candidate=model_fn(task,source,key)
        if api.call('GET','/git/ref/heads/main')['object']['sha']!=base:
            raise Halt('Main changed during inference; no write')
        api.call('PUT','/contents/'+quote(task['path'],safe='/'),{
            'branch':branch,'sha':remote_sha,
            'message':'docs(sandbox): proposed public task '+task['id'],
            'content':base64.b64encode(candidate.encode('utf-8')).decode('ascii')})
        phase='NEW'
    pr=api.call('POST','/pulls',{
        'title':'[PUBLIC AUTO] '+task['id'], 'head':branch, 'base':'main', 'draft':True,
        'body':'Public fictional-only sample; approved manifest and issue #'+str(task['issue'])+
               '. Requires independent review. No automatic merge. No private data.'})
    return {'task':task['id'],'state':phase,'pr':pr.get('html_url','')}


def work_queue(api, key, root, model_fn=generate):
    if api.repository!=OWNER_REPO:
        raise Halt('Execution in any other repository is prohibited')
    tasks=load_approved(root)
    results=[]
    attempts=0
    for task in tasks:
        if attempts>=MAX_PER_RUN:
            break
        try:
            out=process_task(api,task,key,root,model_fn)
        except Halt:
            # A reserved task may already have spent its one free provider call.
            # Continue with other approved, independent tasks.
            out={'task':task['id'],'state':'BLOCKED','reason':'Task needs manual review'}
        except Exception:
            # No traceback or third-party response/secret reaches job log.
            out={'task':task['id'],'state':'BLOCKED','reason':'Unexpected task failure'}
        results.append(out)
        if out['state'] in {'NEW','RECOVERED','BLOCKED'}:
            attempts+=1
    return {'status':'PROCESSED','queue_size':len(tasks),'attempted':attempts,'results':results}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='sandbox-status.json')
    args=parser.parse_args()
    status={'status':'PAUSED','reason':'Explicit activation required'}
    try:
        if os.getenv('SANDBOX_ENABLED')=='true' and os.getenv('GITHUB_REF')=='refs/heads/main':
            api=GitHub(os.getenv('GITHUB_REPOSITORY',''),os.getenv('GITHUB_TOKEN',''))
            status=work_queue(api,os.getenv('GEMINI_API_KEY',''),Path(__file__).resolve().parent)
    except Halt:
        status={'status':'BLOCKED','reason':'Safety prerequisite not satisfied'}
    except Exception:
        status={'status':'BLOCKED','reason':'Unexpected controller failure'}
    Path(args.output).write_text(json.dumps(status,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status,sort_keys=True))
    return 1 if status['status']=='BLOCKED' else 0

if __name__=='__main__':
    sys.exit(main())
