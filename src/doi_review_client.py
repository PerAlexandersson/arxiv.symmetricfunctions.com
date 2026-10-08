#!/usr/bin/env python3
"""Agent client for the credential-scoped DOI review REST API."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import urlsplit

import requests

DEFAULT_URL = 'https://arxiv.symmetricfunctions.com/api/v1/doi-review'


def create_token(path, actor):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', actor):
        raise ValueError('Actor must contain 1–100 letters, digits, underscores, dots or hyphens.')
    path = Path(path).expanduser()
    server_path = path.with_name(path.name + '.server.env')
    if path.exists() or server_path.exists():
        raise ValueError('Credential files already exist; choose new paths for rotation.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(48)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        f.write(token + '\n')
    with os.fdopen(os.open(server_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        f.write('DOI_REVIEW_TOKEN_SHA256=' + hashlib.sha256(token.encode()).hexdigest() + '\n')
        f.write('DOI_REVIEW_ACTOR=' + actor + '\n')
    return {'token_file': str(path), 'server_config_file': str(server_path)}


def call_api(base_url, token_file, method, path, payload=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http'
            and parsed.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Use HTTPS (HTTP is allowed only on loopback for local tests).')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid API base URL.')
    file = Path(token_file).expanduser()
    if file.is_symlink() or not stat.S_ISREG(file.stat().st_mode) or file.stat().st_mode & 0o077:
        raise ValueError('Token file must be a regular private file (mode 600).')
    token = file.read_text().strip()
    if not 32 <= len(token) <= 512 or any(char.isspace() for char in token):
        raise ValueError('Invalid token file.')
    response = requests.request(method, base_url.rstrip('/') + path,
                                headers={'Authorization': 'Bearer ' + token},
                                json=payload, timeout=30, allow_redirects=False)
    if not 200 <= response.status_code < 300:
        # Do not print server HTML, request objects, credentials or headers.
        try:
            code = response.json().get('error', {}).get('code', 'request_failed')
        except (ValueError, AttributeError):
            code = 'request_failed'
        raise ValueError(f'HTTP {response.status_code}: {code}')
    return response.json()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=os.getenv('DOI_REVIEW_API_URL', DEFAULT_URL))
    parser.add_argument('--token-file', default=os.getenv('DOI_REVIEW_TOKEN_FILE'))
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init-token', help='Create private token and server hash files')
    init.add_argument('--output', required=True)
    init.add_argument('--actor', default='academic-agent')
    queue = commands.add_parser('list', help='Read pending candidates; no decisions')
    queue.add_argument('--limit', type=int, default=25)
    queue.add_argument('--after-id', type=int, default=0)
    get = commands.add_parser('get')
    get.add_argument('candidate_id', type=int)
    decide = commands.add_parser('decide', help='Preview a review; --apply sends it')
    decide.add_argument('candidate_id', type=int)
    decide.add_argument('decision', choices=['approve', 'reject'])
    decide.add_argument('--review-token', required=True)
    decide.add_argument('--reason', required=True)
    decide.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init-token':
            result = create_token(args.output, args.actor)
        else:
            if args.command == 'decide':
                payload = {key: getattr(args, key) for key in ('decision', 'review_token', 'reason')}
                if not args.apply:
                    print(json.dumps({'dry_run': True, 'candidate_id': args.candidate_id,
                                      'body': payload}, ensure_ascii=False, indent=2))
                    return 0
                method, path = 'POST', f'/candidates/{args.candidate_id}/decision'
            elif args.command == 'get':
                method, path, payload = 'GET', f'/candidates/{args.candidate_id}', None
            else:
                method, path, payload = 'GET', f'/candidates?limit={args.limit}&after_id={args.after_id}', None
            if not args.token_file:
                raise ValueError('Set DOI_REVIEW_TOKEN_FILE or pass --token-file (not the token itself).')
            result = call_api(args.base_url, args.token_file, method, path, payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, requests.RequestException) as error:
        # Network exceptions can contain URLs; the client never embeds credentials there.
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
