#!/usr/bin/env python3
"""One-shot public synthetic document proposer. No private repositories or data."""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Everything this runner may submit to a model is in this reviewed file.
FILE = 'sandbox/example.md'
OBJECTIVE = 'Rewrite this invented demonstration as four short, testable steps.'
SOURCE_SHA256 = '3e6187a6c2a3bbe2aa12ca53d847ff3302aed803fac9b1e0633906fbe915a14d'
MARKER = '<!-- PUBLIC_SYNTHETIC_ONLY -->\n'
BRANCH = 'auto/synthetic-pilot-one'
MODEL = 'gemini-3.5-flash-lite'  # Verify it is free for the unbilled project before enablement.
MAX_INPUT_BYTES = 12_000
MAX_OUTPUT_BYTES = 16_000


class Halt(Exception):
    """Controlled, non-sensitive failure."""


def request_json(method, url, headers, obj=None):
    data = json.dumps(obj).encode('utf-8') if obj is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=70) as response:
            result = response.read(100_000)
            return json.loads(result) if result else {}
    except urllib.error.HTTPError as exc:
        if method == 'GET' and exc.code == 404:
            return None
        raise Halt('Remote API returned HTTP ' + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise Halt('Remote API temporarily unreachable') from None
    except (UnicodeError, ValueError):
        raise Halt('Invalid remote API response') from None


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise Halt('Invalid repository identity')
        if not token:
            raise Halt('Missing GitHub token')
        self.repository = repository
        self.base_url = 'https://api.github.com/repos/' + repository
        self.headers = {
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
            'User-Agent': 'synthetic-demo-once',
        }

    def call(self, method, path, obj=None):
        return request_json(method, self.base_url + path, self.headers, obj)


def validate(content, expected_marker=MARKER, max_bytes=MAX_OUTPUT_BYTES):
    if not isinstance(content, str) or not content.startswith(expected_marker):
        raise Halt('Missing synthetic marker')
    if not 1 <= len(content.encode('utf-8')) <= max_bytes:
        raise Halt('Output too large or empty')
    if content == MARKER:
        raise Halt('Empty synthetic proposal')
    return content


def generate(content, key, call=request_json):
    if not key:
        raise Halt('Gemini secret is not configured')
    prompt = (
        'This is only a public, fictional Markdown fixture. Return a JSON object with '
        'one key "content" containing an improved version. Preserve the exact marker '
        'at the start. Do not request credentials, run code, or refer to private files. '
        'Objective: ' + OBJECTIVE + '\n\nPublic fixture:\n' + content
    )
    payload = {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {'responseMimeType': 'application/json',
                             'temperature': 0.1, 'maxOutputTokens': 2048},
    }
    endpoint = 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent'
    response = call('POST', endpoint, {'x-goog-api-key': key,
                                       'Content-Type': 'application/json'}, payload)
    try:
        text = ''.join(part.get('text', '') for part in response['candidates'][0]['content']['parts'])
        data = json.loads(text)
        if not isinstance(data, dict) or set(data) != {'content'}:
            raise Halt('Invalid model result schema')
        updated = validate(data['content'])
    except Halt:
        raise
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise Halt('Invalid model response') from None
    if updated == content:
        raise Halt('Model produced no change')
    return updated


def confirmed_public_fixture(path=FILE, root=None):
    root = Path(root or Path(__file__).resolve().parent)
    source = (root / path).read_bytes()
    if len(source) > MAX_INPUT_BYTES or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise Halt('Synthetic source digest differs from approved version')
    try:
        text = source.decode('utf-8')
    except UnicodeError:
        raise Halt('Invalid fixture encoding') from None
    return validate(text)


def run(api, key, generate_fn=generate, root=None):
    # The source bytes and prompt are pinned to this reviewed release.
    source = confirmed_public_fixture(root=root)
    branch_path = '/git/ref/heads/' + BRANCH
    prior = api.call('GET', branch_path)
    prs = api.call('GET', '/pulls?state=all&head=' + urllib.parse.quote(
        api.repository.split('/')[0] + ':' + BRANCH, safe=''))
    if not isinstance(prs, list):
        raise Halt('Unable to check existing pull requests')
    if prs:
        return {'status': 'COMPLETE', 'detail': 'A proposal PR already exists'}
    if prior:
        # Recovery of branch-with-change may create a Draft-PR, but NEVER recontact Gemini.
        delta = api.call('GET', '/compare/main...' + BRANCH)
        if (isinstance(delta, dict) and delta.get('status') == 'ahead' and
                len(delta.get('files') or []) == 1 and
                delta['files'][0].get('filename') == FILE):
            saved = api.call('GET', '/contents/' + FILE + '?ref=' + BRANCH)
            if not isinstance(saved, dict) or saved.get('encoding') != 'base64':
                raise Halt('Cannot verify recovery contents')
            try:
                check = base64.b64decode(''.join(saved['content'].split()), validate=True).decode('utf-8')
            except (ValueError, UnicodeError, KeyError):
                raise Halt('Invalid recovery contents') from None
            validate(check)
        else:
            raise Halt('Prior attempt requires manual review; model not called again')
    else:
        if not key:
            raise Halt('Gemini secret missing; no attempt reserved')
        ref = api.call('GET', '/git/ref/heads/main')
        if not isinstance(ref, dict) or not ref.get('object', {}).get('sha'):
            raise Halt('Main branch cannot be verified')
        base = ref['object']['sha']
        remote_file = api.call('GET', '/contents/' + FILE + '?ref=main')
        if not isinstance(remote_file, dict) or remote_file.get('encoding') != 'base64':
            raise Halt('Cannot verify remote fixture')
        try:
            remote = base64.b64decode(''.join(remote_file['content'].split()), validate=True)
        except (KeyError, ValueError):
            raise Halt('Invalid remote fixture') from None
        if remote != source.encode('utf-8'):
            raise Halt('Approved remote fixture differs; no model call')
        # Durable branch reservation: at most ONE external inference attempt.
        api.call('POST', '/git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': base})
        proposal = generate_fn(source, key)
        if api.call('GET', '/git/ref/heads/main')['object']['sha'] != base:
            raise Halt('Main changed during attempt; manual review required')
        api.call('PUT', '/contents/' + FILE, {
            'branch': BRANCH, 'message': 'docs: propose public synthetic fixture update',
            'sha': remote_file['sha'],
            'content': base64.b64encode(proposal.encode('utf-8')).decode('ascii'),
        })
    created = api.call('POST', '/pulls', {
        'title': 'Public synthetic fixture proposal', 'head': BRANCH,
        'base': 'main', 'draft': True,
        'body': 'Fictional test fixture only. Requires manual review. No automatic merge.',
    })
    return {'status': 'DRAFT_PR', 'url': created.get('html_url', '')}


def main():
    status = {'status': 'PAUSED', 'detail': 'Explicit approval and enablement required'}
    try:
        if (os.getenv('SANDBOX_ENABLED') == 'true' and
                os.getenv('GITHUB_REF') == 'refs/heads/main'):
            api = GitHub(os.getenv('GITHUB_REPOSITORY', ''), os.getenv('GITHUB_TOKEN', ''))
            status = run(api, os.getenv('GEMINI_API_KEY', ''))
    except Halt as exc:
        # Halt strings are static; never include external data or credentials.
        status = {'status': 'BLOCKED', 'detail': str(exc)}
    except Exception:
        status = {'status': 'BLOCKED', 'detail': 'Unexpected runner failure'}
    Path('sandbox-status.json').write_text(json.dumps(status, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(status, sort_keys=True))
    return 0 if status['status'] in {'PAUSED', 'COMPLETE', 'DRAFT_PR'} else 1


if __name__ == '__main__':
    sys.exit(main())
