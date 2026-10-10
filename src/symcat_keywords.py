"""Import SymCat's generated definition terms without replacing curated data."""

import json
import re
from collections import defaultdict

import requests

from extract_keywords import tokenize


KEYWORD_URL = 'https://www.symmetricfunctions.com/site-keywords.json'
SYMCAT_BASE = 'https://www.symmetricfunctions.com/'
MAX_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 10000
_HREF = re.compile(r'[A-Za-z0-9_-]+\.htm(?:#[A-Za-z0-9_.:-]+)?\Z')


def parse_catalogue(payload):
    """Validate the entire feed before any database access; combine synonyms."""
    if (not isinstance(payload, dict)
            or type(payload.get('schema_version')) is not int
            or payload['schema_version'] != 1):
        raise ValueError('Unsupported SymCat keyword catalogue version.')
    entries = payload.get('keywords')
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError('SymCat returned an empty or oversized keyword catalogue.')
    keywords = defaultdict(set)
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid SymCat keyword record.')
        phrase, href = entry.get('phrase'), entry.get('href')
        if (not isinstance(phrase, str) or not phrase.strip() or len(phrase) > 255
                or any(ord(c) < 32 for c in phrase)
                or not isinstance(href, str) or not _HREF.fullmatch(href)):
            raise ValueError('Invalid SymCat keyword phrase or reference.')
        normalized = ' '.join(tokenize(phrase))
        if not normalized or len(normalized) > 255:
            raise ValueError('SymCat returned a keyword that cannot be tagged.')
        keywords[normalized].add(SYMCAT_BASE + href)
    return dict(keywords)


def fetch_keywords():
    """Fetch only the fixed public feed, with bounded time and response size."""
    with requests.get(KEYWORD_URL, timeout=(5, 20), stream=True,
                      allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError('Could not fetch SymCat keywords (HTTP %s).'
                             % response.status_code)
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('SymCat keyword catalogue is too large.')
            chunks.append(chunk)
    try:
        payload = json.loads(b''.join(chunks))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('SymCat did not return a valid keyword catalogue.') from exc
    return parse_catalogue(payload)


def import_keywords(conn, keywords):
    """Add terms transactionally; preserve aliases, exclusions and existing rows.

    Use the tagger's normalization for both incoming and existing phrases.
    When a term has multiple source targets, leave its URL unset for curation.
    Paper tags are changed only by the separate retag action.
    """
    cursor = conn.cursor()
    counts = dict(total=len(keywords), added=0, existing=0, excluded=0)
    try:
        cursor.execute('SELECT phrase FROM keywords UNION '
                       'SELECT alias AS phrase FROM keyword_aliases')
        existing = {' '.join(tokenize(row['phrase'])) for row in cursor.fetchall()}
        cursor.execute('SELECT phrase FROM math_words UNION '
                       'SELECT phrase FROM ignored_candidates')
        excluded = {' '.join(tokenize(row['phrase'])) for row in cursor.fetchall()}
        for phrase, targets in sorted(keywords.items()):
            if phrase in existing:
                counts['existing'] += 1
            elif phrase in excluded:
                counts['excluded'] += 1
            else:
                url = next(iter(targets)) if len(targets) == 1 else None
                cursor.execute(
                    'INSERT IGNORE INTO keywords (phrase, score, url) VALUES (%s, 5, %s)',
                    (phrase, url),
                )
                counts['added' if cursor.rowcount else 'existing'] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
    return counts
