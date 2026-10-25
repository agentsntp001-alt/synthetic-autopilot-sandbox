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
from html.parser import HTMLParser
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



# Static public HTML is a document, not an application. There is no scripting,
# networking, frames, embeds, forms, click handlers or remote images.
_ALLOWED_HTML_TAGS = frozenset({
    'html', 'head', 'meta', 'title', 'style', 'body', 'header', 'main',
    'section', 'article', 'nav', 'aside', 'footer', 'h1', 'h2', 'h3', 'h4',
    'p', 'small', 'strong', 'em', 'b', 'i', 'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'div', 'span', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'caption', 'progress', 'br', 'hr', 'code', 'pre', 'blockquote', 'time',
})
_ALLOWED_HTML_ATTRS = frozenset({
    'lang', 'dir', 'class', 'id', 'role', 'title', 'charset', 'name',
    'content', 'scope', 'colspan', 'rowspan', 'value', 'max', 'datetime',
})
_FORBIDDEN_CONTENT = re.compile(
    r'(?:AIza[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9_]{20,}|' 
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|' 
    r'\bSwiss\s+Novatech\b|\b(?:GACP|Swissmedic)\b)',
    flags=re.IGNORECASE,
)


class _StaticHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = set()
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_HTML_TAGS:
            raise Halt('HTML contains forbidden non-static element')
        self.tags.add(tag)
        if tag == 'style':
            self.in_style = True
        for key, value in attrs:
            if key not in _ALLOWED_HTML_ATTRS and not key.startswith('aria-'):
                raise Halt('HTML contains an unsafe attribute')
            if value and ('javascript:' in value.casefold() or
                          'data:' in value.casefold() or
                          'http:' in value.casefold() or 'https:' in value.casefold()):
                raise Halt('HTML contains an external or executable value')

    def handle_endtag(self, tag):
        if tag not in _ALLOWED_HTML_TAGS:
            raise Halt('HTML contains forbidden non-static element')
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style and ('@' in data or '\\' in data or
                              re.search(r'(?i)\b(?:url|expression|behavior|image-set)\s*\(', data)):
            raise Halt('HTML contains unsafe stylesheet')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def unknown_decl(self, data):
        raise Halt('HTML contains unsupported declaration')


def load_approved(root):
    path = root / 'tasks' / 'approved.json'
    try:
        if path.stat().st_size > 12000:
            raise Halt('Approved queue too large')
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
    if chr(0) in content or _FORBIDDEN_CONTENT.search(content):
        raise Halt('Proposed content contains unsafe or non-synthetic text')
    if path.endswith('.html'):
        lowered = content.casefold()
        if any(fragment in lowered for fragment in (
                'http://', 'https://', 'javascript:', 'data:', '@import',
                'url(', 'expression(', '-moz-binding', 'behavior:')):
            raise Halt('HTML contains forbidden active or remote content')
        if re.search(r'\bon[a-z]+\s*=', lowered):
            raise Halt('HTML contains forbidden event handlers')
        if '<!doctype html>' not in lowered:
            raise Halt('Proposed HTML document incomplete')
        parser = _StaticHTML()
        try:
            parser.feed(content)
            parser.close()
        except (ValueError, TypeError):
            raise Halt('Invalid HTML document') from None
        if not {'html', 'head', 'body', 'title', 'main'}.issubset(parser.tags):
            raise Halt('Proposed HTML missing required document elements')
    elif path.endswith('.md'):
        # This fictional fixture needs only plain Markdown. Refuse *all* rendered
        # hyperlinks/images and raw HTML, including protocol-relative URLs,
        # reference links, autolinks, and entity/escape-obfuscated schemes.
        # We are intentionally stricter than GitHub Flavored Markdown because
        # a rendered PR preview must never fetch a model-selected resource.
        safe_text = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        if re.search(r'(?i)(?:https?\s*[:;]|javascript\s*[:;]|data\s*[:;]|\bwww\.)', safe_text) or '// ' in safe_text or '//' in safe_text:
            raise Halt('Markdown contains external or executable links')
        if re.search(r'(?s)!?\[[^\]\n]{0,400}\]\s*(?:\(|\[)', safe_text) or re.search(r'(?m)^\s{0,3}\[[^\]\n]{1,400}\]\s*:', safe_text):
            raise Halt('Markdown links and images are not allowed')
        if re.search(r'<\s*[/!a-zA-Z][^>]{0,600}>', safe_text) or re.search(r'&(?:#(?:x[0-9a-f]+|[0-9]+)|[a-z]+);', safe_text, flags=re.IGNORECASE):
            raise Halt('Markdown raw HTML and entities are not allowed')
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
    if api.repository != OWNER_REPO:
        raise Halt('Execution in any other repository is prohibited')
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



def inspect_queue(api, root):
    """Read-only live GitHub preflight: never creates a branch or calls a model.

    This tests the real connection, trusted Issues and source checksums; it cannot
    prove billing settings, reviewer independence or environment secret policy.
    """
    if api.repository != OWNER_REPO:
        raise Halt('Execution in any other repository is prohibited')
    tasks = load_approved(root)
    result = []
    for task in tasks:
        try:
            issue = api.call('GET', '/issues/' + str(task['issue']))
            if not is_trusted_open_issue(issue, task['issue']):
                status = 'SKIP'
            else:
                branch = 'auto/synthetic-' + task['id']
                if existing_pr(api, branch):
                    status = 'PR_EXISTS'
                elif api.call('GET', '/git/ref/heads/' + branch):
                    status = 'REVIEW_RESERVED_BRANCH'
                else:
                    source = read_local_fixture(root, task)
                    validate_remote_original(api, task, source)
                    status = 'READY'
        except Halt:
            status = 'BLOCKED'
        except Exception:
            status = 'BLOCKED'
        result.append({'task': task['id'], 'status': status})
    verdict = 'BLOCKED' if any(x['status'] == 'BLOCKED' for x in result) else 'PREFLIGHT'
    return {'status': verdict, 'tasks': result,
            'read_only': True, 'external_ai_calls': 0, 'writes': 0,
            'environment_and_billing_verified': False}


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
    blocked=sum(entry['state']=='BLOCKED' for entry in results)
    return {'status':'ATTENTION_REQUIRED' if blocked else 'PROCESSED',
            'queue_size':len(tasks),'attempted':attempts,
            'blocked_count':blocked,'results':results}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='sandbox-status.json')
    parser.add_argument('--dry-run',action='store_true',help='Read-only GitHub preflight; no AI or writes')
    args=parser.parse_args()
    status={'status':'PAUSED','reason':'Explicit activation required'}
    try:
        if args.dry_run:
            if os.getenv('GITHUB_REF') != 'refs/heads/main':
                raise Halt('Preflight must run on protected main')
            api=GitHub(os.getenv('GITHUB_REPOSITORY',''),os.getenv('GITHUB_TOKEN',''))
            status=inspect_queue(api,Path(__file__).resolve().parent)
        elif os.getenv('SANDBOX_ENABLED')=='true' and os.getenv('GITHUB_REF')=='refs/heads/main':
            api=GitHub(os.getenv('GITHUB_REPOSITORY',''),os.getenv('GITHUB_TOKEN',''))
            status=work_queue(api,os.getenv('GEMINI_API_KEY',''),Path(__file__).resolve().parent)
    except Halt:
        status={'status':'BLOCKED','reason':'Safety prerequisite not satisfied'}
    except Exception:
        status={'status':'BLOCKED','reason':'Unexpected controller failure'}
    Path(args.output).write_text(json.dumps(status,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(status,sort_keys=True))
    return 1 if status['status'] in {'BLOCKED','ATTENTION_REQUIRED'} else 0

if __name__=='__main__':
    sys.exit(main())
