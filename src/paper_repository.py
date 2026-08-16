"""Shared read model for the public paper API and future web routes."""

import base64
import binascii
import json
from datetime import date, datetime, timezone
from urllib.parse import quote, urlparse

from db import attach_authors, attach_categories, attach_keywords
from utils import split_arxiv_id_version

SITE_URL = 'https://arxiv.symmetricfunctions.com'
SYMCAT_URL = 'https://www.symmetricfunctions.com/'
ORDER_COLUMNS = {
    'ingested': ('p.created_at', 'datetime'),
    'changed': ('p.updated_at', 'datetime'),
    'published': ('p.published_date', 'date'),
}

PAPER_COLUMNS = """
    p.id, p.arxiv_id, p.arxiv_base_id, p.arxiv_version,
    p.title, p.abstract, p.primary_category,
    p.published_date, p.updated_date, p.created_at, p.updated_at,
    p.comment, p.journal_ref, p.doi, p.doi_status,
    p.publication_url, p.publication_venue_key,
    p.publication_status, p.editor_note
"""


class CursorError(ValueError):
    """Raised when an API cursor is malformed or used with another ordering."""


def _utc_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_date(value, parameter):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f'{parameter} must be an ISO date (YYYY-MM-DD)')


def _parse_datetime(value, parameter):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        raise ValueError(f'{parameter} must be an ISO-8601 timestamp')
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _encode_cursor(order, value, paper_id):
    payload = json.dumps(
        {'order': order, 'value': _utc_iso(value), 'id': int(paper_id)},
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return base64.urlsafe_b64encode(payload).decode('ascii').rstrip('=')


def _decode_cursor(cursor, order):
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        if payload.get('order') != order or int(payload.get('id', 0)) < 1:
            raise CursorError('cursor does not match the requested ordering')
        kind = ORDER_COLUMNS[order][1]
        parser = _parse_date if kind == 'date' else _parse_datetime
        return parser(payload.get('value'), 'cursor'), int(payload['id'])
    except CursorError:
        raise
    except (
        AttributeError,
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        raise CursorError('cursor is invalid')


def _symcat_target(keyword, site_labels):
    value = keyword.get('url')
    if not value:
        return None
    if value.startswith(('http://', 'https://')):
        hostname = (urlparse(value).hostname or '').lower()
        if hostname not in {'symmetricfunctions.com', 'www.symmetricfunctions.com'}:
            return None
        return {
            'label': value,
            'title': keyword.get('phrase') or value,
            'url': value,
        }
    label = (site_labels or {}).get(value)
    if not label:
        return None
    href = label.get('href') or ''
    return {
        'label': value,
        'title': label.get('title') or label.get('text') or value,
        'url': SYMCAT_URL + href.lstrip('/'),
    }


def serialize_paper(paper, site_labels=None):
    """Convert a database paper row into the stable public JSON shape."""
    base_id = paper.get('arxiv_base_id')
    version = paper.get('arxiv_version')
    if not base_id or not version:
        base_id, parsed_version = split_arxiv_id_version(paper.get('arxiv_id'))
        version = version or parsed_version
    versioned_id = paper.get('arxiv_id') or (
        f'{base_id}v{version}' if base_id and version else base_id
    )
    site_id = quote(base_id or versioned_id, safe='/')
    arxiv_path = quote(versioned_id, safe='/')

    keywords = []
    symcat_targets = []
    seen_targets = set()
    for raw_keyword in paper.get('keywords') or []:
        keyword = {
            'phrase': raw_keyword.get('phrase'),
            'score': raw_keyword.get('score'),
            'source': raw_keyword.get('source'),
            'reference': raw_keyword.get('url'),
        }
        target = _symcat_target(raw_keyword, site_labels)
        if target:
            keyword['symcat_target'] = target
            if target['label'] not in seen_targets:
                seen_targets.add(target['label'])
                symcat_targets.append(target)
        keywords.append(keyword)

    return {
        'arxiv_id': base_id,
        'arxiv_version': int(version or 1),
        'versioned_arxiv_id': versioned_id,
        'title': paper.get('title'),
        'abstract': paper.get('abstract'),
        'authors': list(paper.get('authors') or []),
        'primary_category': paper.get('primary_category'),
        'categories': list(paper.get('categories') or []),
        'keywords': keywords,
        'symcat_targets': symcat_targets,
        'published_at': _utc_iso(paper.get('published_date')),
        'revised_at': _utc_iso(paper.get('updated_date')),
        'ingested_at': _utc_iso(paper.get('created_at')),
        'changed_at': _utc_iso(paper.get('updated_at')),
        'comment': paper.get('comment'),
        'publication': {
            'journal_reference': paper.get('journal_ref'),
            'doi': paper.get('doi'),
            'doi_status': paper.get('doi_status'),
            'url': paper.get('publication_url'),
            'venue_key': paper.get('publication_venue_key'),
            'status': paper.get('publication_status'),
            'editor_note': paper.get('editor_note'),
        },
        'urls': {
            'site': f'{SITE_URL}/paper/{site_id}',
            'arxiv': f'https://arxiv.org/abs/{arxiv_path}',
            'pdf': f'https://arxiv.org/pdf/{arxiv_path}',
        },
    }


def _attach_related(cursor, papers):
    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)
    attach_categories(cursor, papers)


def list_papers(cursor, *, limit=50, order='ingested', cursor_token=None,
                ingested_after=None, changed_after=None, published_after=None,
                category=None, keyword=None, query=None, site_labels=None):
    """Return a cursor-paginated page of papers and the next cursor."""
    if order not in ORDER_COLUMNS:
        raise ValueError('order must be ingested, changed, or published')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')

    conditions = []
    params = []
    if ingested_after:
        conditions.append('p.created_at >= %s')
        params.append(_parse_datetime(ingested_after, 'ingested_after'))
    if changed_after:
        conditions.append('p.updated_at >= %s')
        params.append(_parse_datetime(changed_after, 'changed_after'))
    if published_after:
        conditions.append('p.published_date >= %s')
        params.append(_parse_date(published_after, 'published_after'))
    if category:
        conditions.append("""EXISTS (
            SELECT 1 FROM paper_categories pc
            WHERE pc.paper_id = p.id AND pc.category = %s
        )""")
        params.append(category)
    if keyword:
        conditions.append("""EXISTS (
            SELECT 1 FROM paper_keywords filter_pk
            JOIN keywords filter_k ON filter_k.id = filter_pk.keyword_id
            WHERE filter_pk.paper_id = p.id
              AND filter_k.active = 1 AND filter_k.phrase = %s
        )""")
        params.append(keyword)
    if query:
        query = str(query).strip()[:200]
        if query:
            if len(query) < 2:
                raise ValueError('q must contain at least 2 characters')
            like_query = f'%{query}%'
            conditions.append("""(
                MATCH(p.title, p.abstract) AGAINST (%s IN NATURAL LANGUAGE MODE)
                OR EXISTS (
                    SELECT 1 FROM paper_authors search_pa
                    JOIN authors search_a ON search_a.id = search_pa.author_id
                    WHERE search_pa.paper_id = p.id AND search_a.name LIKE %s
                )
                OR EXISTS (
                    SELECT 1 FROM paper_keywords search_pk
                    JOIN keywords search_k ON search_k.id = search_pk.keyword_id
                    WHERE search_pk.paper_id = p.id AND search_k.active = 1
                      AND search_k.phrase LIKE %s
                )
            )""")
            params.extend((query, like_query, like_query))

    order_column = ORDER_COLUMNS[order][0]
    if cursor_token:
        cursor_value, cursor_id = _decode_cursor(cursor_token, order)
        conditions.append(
            f'({order_column} < %s OR ({order_column} = %s AND p.id < %s))'
        )
        params.extend((cursor_value, cursor_value, cursor_id))

    where_sql = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
    cursor.execute(f"""
        SELECT {PAPER_COLUMNS}
        FROM papers p
        {where_sql}
        ORDER BY {order_column} DESC, p.id DESC
        LIMIT %s
    """, params + [limit + 1])
    papers = list(cursor.fetchall())
    has_more = len(papers) > limit
    if has_more:
        papers = papers[:limit]
    _attach_related(cursor, papers)

    next_cursor = None
    if has_more and papers:
        value_key = {
            'ingested': 'created_at',
            'changed': 'updated_at',
            'published': 'published_date',
        }[order]
        last = papers[-1]
        next_cursor = _encode_cursor(order, last[value_key], last['id'])
    return {
        'data': [serialize_paper(paper, site_labels) for paper in papers],
        'next_cursor': next_cursor,
        'has_more': has_more,
    }


def get_paper(cursor, arxiv_id, site_labels=None):
    base_id, _ = split_arxiv_id_version(arxiv_id)
    if not base_id:
        raise ValueError('arxiv_id is invalid')
    cursor.execute(f"""
        SELECT {PAPER_COLUMNS}
        FROM papers p
        WHERE p.arxiv_base_id = %s
        LIMIT 1
    """, (base_id,))
    paper = cursor.fetchone()
    if not paper:
        return None
    _attach_related(cursor, [paper])
    return serialize_paper(paper, site_labels)


def list_keywords(cursor, *, limit=100, site_labels=None):
    if not 1 <= limit <= 500:
        raise ValueError('limit must be between 1 and 500')
    cursor.execute("""
        SELECT k.phrase, k.score, k.url, COUNT(pk.paper_id) AS paper_count
        FROM keywords k
        LEFT JOIN paper_keywords pk ON pk.keyword_id = k.id
        WHERE k.active = 1
        GROUP BY k.id, k.phrase, k.score, k.url
        ORDER BY k.score DESC, paper_count DESC, k.phrase ASC
        LIMIT %s
    """, (limit,))
    keywords = []
    for row in cursor.fetchall():
        keyword = dict(row)
        target = _symcat_target(keyword, site_labels)
        keyword['reference'] = keyword.pop('url', None)
        if target:
            keyword['symcat_target'] = target
        keywords.append(keyword)
    return keywords


def get_status(cursor):
    cursor.execute("""
        SELECT COUNT(*) AS paper_count,
               MAX(created_at) AS latest_ingested_at,
               MAX(updated_at) AS latest_changed_at,
               MAX(published_date) AS latest_published_at
        FROM papers
    """)
    row = cursor.fetchone() or {}
    return {
        'api_version': 'v1',
        'paper_count': int(row.get('paper_count') or 0),
        'latest_ingested_at': _utc_iso(row.get('latest_ingested_at')),
        'latest_changed_at': _utc_iso(row.get('latest_changed_at')),
        'latest_published_at': _utc_iso(row.get('latest_published_at')),
    }
