"""Credential-scoped DOI candidate review, separate from the public read API."""

import hashlib
import hmac
import json
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote

import pymysql
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from db import get_db_connection

review_api = Blueprint('doi_review_api', __name__, url_prefix='/api/v1/doi-review')
_FIELDS = '''dc.id, dc.paper_id, dc.doi, dc.confidence, dc.crossref_title,
    dc.crossref_authors, dc.crossref_year, dc.status, dc.reviewed_at,
    p.arxiv_id, p.title AS paper_title, p.abstract AS paper_abstract,
    p.published_date, p.journal_ref, p.doi AS current_doi, p.doi_status'''


class ReviewError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


def _error(code, message, status):
    return jsonify(error={'code': code, 'message': message}), status


@review_api.before_request
def authenticate():
    configured = current_app.config.get('DOI_REVIEW_TOKEN_SHA256', '')
    if not re.fullmatch(r'[0-9a-f]{64}', configured):
        return _error('disabled', 'DOI review API is not configured.', 503)
    authorization = request.headers.get('Authorization', '')
    scheme, _, token = authorization.partition(' ')
    supplied = hashlib.sha256(token.encode('utf-8')).hexdigest()
    if (scheme.lower() != 'bearer' or not token or len(token) > 512
            or not hmac.compare_digest(supplied, configured)):
        response, status = _error('unauthorized', 'A DOI review bearer token is required.', 401)
        response.headers['WWW-Authenticate'] = 'Bearer realm="doi-review"'
        return response, status
    if request.content_length is not None and request.content_length > 16384:
        return _error('too_large', 'Request body exceeds 16 KiB.', 413)


@review_api.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Vary'] = 'Authorization'
    return response


@review_api.errorhandler(ReviewError)
def review_error(error):
    return _error(error.code, error.message, error.status)


@review_api.errorhandler(pymysql.Error)
def database_error(error):
    # SQL exceptions can include review text. Do not echo them in logs/responses.
    current_app.logger.error('DOI review database operation failed (%s)', type(error).__name__)
    return _error('unavailable', 'Review outcome could not be confirmed. Retry the identical request.', 503)


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _enrich(cursor, rows, lock=False):
    if not rows:
        return []
    ids = [row['paper_id'] for row in rows]
    placeholders = ','.join(['%s'] * len(ids))
    cursor.execute(f'''SELECT pa.paper_id, a.name FROM paper_authors pa
        JOIN authors a ON a.id = pa.author_id
        WHERE pa.paper_id IN ({placeholders}) ORDER BY pa.paper_id, pa.author_order''', ids)
    authors = {}
    for row in cursor.fetchall():
        authors.setdefault(row['paper_id'], []).append(row['name'])
    dois = [row['doi'].strip().lower() for row in rows]
    cursor.execute(f'''SELECT id AS paper_id, arxiv_id, title, doi FROM papers
        WHERE LOWER(TRIM(doi)) IN ({placeholders}) ORDER BY id'''
                   + (' FOR UPDATE' if lock else ''), dois)
    assignments = cursor.fetchall()
    result = []
    for row in rows:
        item = {key: _plain(value) for key, value in row.items()}
        item['paper_authors'] = authors.get(item['paper_id'], [])
        item['conflicts'] = [dict(other) for other in assignments
                             if other['paper_id'] != item['paper_id']
                             and other['doi'].strip().lower() == item['doi'].strip().lower()]
        item['review_token'] = hashlib.sha256(json.dumps(
            item, sort_keys=True, ensure_ascii=False, separators=(',', ':')
        ).encode('utf-8')).hexdigest()
        item['arxiv_url'] = 'https://arxiv.org/abs/' + item['arxiv_id']
        item['doi_url'] = 'https://doi.org/' + quote(item['doi'], safe='/')
        result.append(item)
    return result


def _candidate(cursor, candidate_id, lock=False):
    cursor.execute(f'''SELECT {_FIELDS} FROM doi_candidates dc
        JOIN papers p ON p.id = dc.paper_id WHERE dc.id = %s'''
                   + (' FOR UPDATE' if lock else ''), (candidate_id,))
    row = cursor.fetchone()
    if row is None:
        raise ReviewError('not_found', 'Candidate not found.', 404)
    return _enrich(cursor, [row], lock=lock)[0]


@review_api.get('/candidates')
def candidates():
    try:
        after = int(request.args.get('after_id', '0'))
        limit = int(request.args.get('limit', '25'))
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError
    except ValueError:
        raise ReviewError('invalid_request', 'Use after_id >= 0 and limit between 1 and 100.', 400)
    cursor = get_db_connection().cursor()
    try:
        cursor.execute(f'''SELECT {_FIELDS} FROM doi_candidates dc
            JOIN papers p ON p.id = dc.paper_id
            WHERE dc.status = 'pending' AND dc.id > %s ORDER BY dc.id LIMIT %s''',
                       (after, limit + 1))
        rows = cursor.fetchall()
        data = _enrich(cursor, rows[:limit])
    finally:
        cursor.close()
    return jsonify(data=data, next_after_id=(data[-1]['id'] if len(rows) > limit else None))


@review_api.get('/candidates/<int:candidate_id>')
def candidate(candidate_id):
    cursor = get_db_connection().cursor()
    try:
        data = _candidate(cursor, candidate_id)
    finally:
        cursor.close()
    return jsonify(data=data)


@review_api.post('/candidates/<int:candidate_id>/decision')
def decision(candidate_id):
    if not request.is_json:
        raise ReviewError('invalid_request', 'Use an application/json request.', 415)
    try:
        raw = request.stream.read(16385)
        if len(raw) > 16384:
            raise ReviewError('too_large', 'Request body exceeds 16 KiB.', 413)
        body = json.loads(raw)
    except (BadRequest, ValueError, UnicodeError):
        raise ReviewError('invalid_request', 'Invalid JSON body.', 400)
    if not isinstance(body, dict) or set(body) != {'decision', 'reason', 'review_token'}:
        raise ReviewError('invalid_request', 'Supply decision, reason and review_token only.', 400)
    action, reason, token = (body[key] for key in ('decision', 'reason', 'review_token'))
    if (action not in ('approve', 'reject') or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 2000 or not isinstance(token, str)
            or not re.fullmatch(r'[0-9a-f]{64}', token)):
        raise ReviewError('invalid_request', 'Invalid decision, reason or review_token.', 400)
    reviewer = current_app.config.get('DOI_REVIEW_ACTOR', 'agent')
    if not isinstance(reviewer, str) or not 1 <= len(reviewer) <= 100:
        raise ReviewError('disabled', 'Reviewer identity is not configured correctly.', 503)
    status = 'approved' if action == 'approve' else 'rejected'
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.begin()
        item = _candidate(cursor, candidate_id, lock=True)
        cursor.execute('SELECT * FROM doi_review_events WHERE candidate_id = %s', (candidate_id,))
        previous = cursor.fetchone()
        if previous:
            if (previous['review_token'] == token and previous['decision'] == action
                    and previous['reviewer'] == reviewer and previous['reason'] == reason.strip()
                    and item['status'] == status
                    and (action == 'reject' or (item['current_doi'] or '').strip().lower()
                         == item['doi'].strip().lower())):
                conn.rollback()
                return jsonify(ok=True, candidate_id=candidate_id, status=status, repeated=True)
            raise ReviewError('already_reviewed', 'Candidate already has a different recorded review.')
        if item['status'] != 'pending':
            raise ReviewError('already_reviewed', 'Only pending candidates can be reviewed.')
        if not hmac.compare_digest(item['review_token'], token):
            raise ReviewError('stale_review', 'Candidate evidence changed. Fetch and review it again.')
        current_doi = (item['current_doi'] or '').strip().lower()
        candidate_doi = item['doi'].strip().lower()
        if action == 'approve':
            if item['conflicts'] or (current_doi and current_doi != candidate_doi):
                raise ReviewError('doi_conflict', 'DOI reassignment requires the admin interface.')
            if item['doi_status'] == 'skipped':
                raise ReviewError('paper_skipped', 'This paper was marked skipped by an editor.')
            cursor.execute('''UPDATE papers SET doi = %s, doi_status = 'verified',
                doi_confidence = %s WHERE id = %s''',
                           (item['doi'], item['confidence'], item['paper_id']))
            cursor.execute('''UPDATE site_stats SET cache_dirty_at = NOW(),
                cache_rebuild_after = DATE_ADD(NOW(), INTERVAL 600 SECOND),
                updated_at = updated_at WHERE id = 1''')
        elif current_doi == candidate_doi:
            raise ReviewError('doi_assigned', 'Candidate DOI is already assigned; use the admin interface.')
        cursor.execute('''UPDATE doi_candidates SET status = %s, reviewed_at = NOW()
            WHERE id = %s''', (status, candidate_id))
        cursor.execute('''INSERT INTO doi_review_events
            (candidate_id, paper_id, doi, decision, reviewer, reason, review_token)
            VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                       (candidate_id, item['paper_id'], item['doi'], action, reviewer,
                        reason.strip(), token))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
    return jsonify(ok=True, candidate_id=candidate_id, status=status, repeated=False)
