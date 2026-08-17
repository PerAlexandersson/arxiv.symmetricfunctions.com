#!/usr/bin/env python3
"""Evidence-based triage for pending DOI candidates.

The command is read-only by default. It resolves each arXiv identifier through
Semantic Scholar's batch API and compares that independently linked DOI with
the queued Crossref candidate. Only exact, non-conflicting DOI agreements with
strong title/author evidence are eligible for ``--apply-confirmed``.

Examples:
    python3 doi_triage.py --report /tmp/doi-triage.json
    python3 doi_triage.py --apply-confirmed --report /tmp/doi-triage.json
    python3 doi_triage.py --validate-replacements --validate-metadata
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote

import pymysql
import requests

from config import DB_CONFIG
from doi_lookup import score_match
from site_stats import mark_index_cache_dirty
from title_matching import (
    author_coverage_similarity,
    normalize_title,
    score_title_author_match,
    title_similarity,
)


SEMANTIC_SCHOLAR_BATCH_API = (
    'https://api.semanticscholar.org/graph/v1/paper/batch'
)
CROSSREF_WORK_API = 'https://api.crossref.org/works'
USER_AGENT = 'arxiv-symmetricfunctions/1.0 (mailto:per.alexandersson@math.su.se)'
DEFAULT_CACHE = Path.home() / '.cache' / 'arxiv.symmetricfunctions.com' / (
    'doi-triage/semantic-scholar.json'
)
DEFAULT_CROSSREF_CACHE = Path.home() / '.cache' / (
    'arxiv.symmetricfunctions.com/doi-triage/crossref.json'
)
DEFAULT_RESOLVER_CACHE = Path.home() / '.cache' / (
    'arxiv.symmetricfunctions.com/doi-triage/doi-resolver.json'
)
_KNOWN_DOI_LESS_JOURNALS = ('journal of integer sequences',)
_HIGH_EVIDENCE_MIN_SCORE = 0.84
_HIGH_EVIDENCE_MIN_TITLE = 0.78
_HIGH_EVIDENCE_MIN_AUTHOR = 0.95
_REFERENCE_STOPWORDS = {
    'a', 'an', 'and', 'for', 'in', 'of', 'on', 'series', 'the',
}


def normalize_doi(value):
    """Return a canonical lowercase DOI without a resolver prefix."""
    doi = str(value or '').strip().lower()
    prefixes = (
        'https://doi.org/',
        'http://doi.org/',
        'https://dx.doi.org/',
        'http://dx.doi.org/',
        'doi:',
    )
    for prefix in prefixes:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.rstrip('.,; ')


def arxiv_base_id(value):
    """Strip an arXiv revision suffix while preserving legacy identifiers."""
    return re.sub(r'v\d+$', '', str(value or ''), flags=re.IGNORECASE)


def is_preprint_doi(value):
    """Return whether a DOI identifies the arXiv preprint rather than a journal."""
    return normalize_doi(value).startswith('10.48550/arxiv.')


def _crossref_authors(value):
    return [part.strip() for part in (value or '').split(';') if part.strip()]


def _semantic_scholar_authors(record):
    return [
        author.get('name', '').strip()
        for author in (record or {}).get('authors', [])
        if author.get('name', '').strip()
    ]


def classify_candidate(candidate, record, conflicting_dois, min_evidence=0.85):
    """Classify one pending candidate without changing database state."""
    queued_doi = normalize_doi(candidate['doi'])
    external_ids = (record or {}).get('externalIds') or {}
    linked_doi = normalize_doi(external_ids.get('DOI'))
    ignored_preprint_doi = linked_doi if is_preprint_doi(linked_doi) else None
    if ignored_preprint_doi:
        linked_doi = ''
    queued_conflict = queued_doi in conflicting_dois
    linked_conflict = bool(linked_doi and linked_doi in conflicting_dois)

    paper_authors = candidate.get('paper_authors') or []
    stored_score = score_title_author_match(
        candidate.get('paper_title') or '',
        paper_authors,
        candidate.get('crossref_title') or '',
        _crossref_authors(candidate.get('crossref_authors')),
    )
    linked_score = score_title_author_match(
        candidate.get('paper_title') or '',
        paper_authors,
        (record or {}).get('title') or '',
        _semantic_scholar_authors(record),
    )

    result = {
        'candidate_id': candidate['id'],
        'paper_id': candidate['paper_id'],
        'arxiv_id': candidate['arxiv_id'],
        'queued_doi': queued_doi,
        'linked_doi': linked_doi or None,
        'ignored_preprint_doi': ignored_preprint_doi,
        'queued_conflict': queued_conflict,
        'linked_conflict': linked_conflict,
        'stored_match_score': round(stored_score, 3),
        'linked_match_score': round(linked_score, 3),
    }

    paper_title = normalize_title(candidate.get('paper_title') or '')
    crossref_title = normalize_title(candidate.get('crossref_title') or '')
    exact_stored_title = bool(paper_title) and (
        paper_title.replace(' ', '') == crossref_title.replace(' ', '')
    )
    stored_title_similarity = title_similarity(
        candidate.get('paper_title') or '',
        candidate.get('crossref_title') or '',
    )
    stored_author_coverage = author_coverage_similarity(
        paper_authors,
        _crossref_authors(candidate.get('crossref_authors')),
    )
    near_exact_stored_metadata = (
        stored_title_similarity >= 0.98
        and stored_author_coverage >= 0.95
        and stored_score >= 0.95
    )
    result['stored_title_similarity'] = round(stored_title_similarity, 3)
    result['stored_author_coverage'] = round(stored_author_coverage, 3)

    if not linked_doi:
        if (
            not queued_conflict
            and (exact_stored_title or near_exact_stored_metadata)
            and stored_score >= min_evidence
        ):
            result['decision'] = 'metadata_exact'
        elif (
            not queued_conflict
            and stored_score >= _HIGH_EVIDENCE_MIN_SCORE
            and stored_title_similarity >= _HIGH_EVIDENCE_MIN_TITLE
            and stored_author_coverage >= _HIGH_EVIDENCE_MIN_AUTHOR
        ):
            # These are valuable manual-review candidates, but not safe for
            # automatic approval: corrigenda, appendices, and merged papers
            # can have the same strong title/author signal as a title rename.
            result['decision'] = 'review_high_evidence'
        else:
            result['decision'] = 'unresolved'
    elif linked_doi == queued_doi:
        if queued_conflict:
            result['decision'] = 'review_exact_conflict'
        elif max(stored_score, linked_score) >= min_evidence:
            result['decision'] = 'approve_confirmed'
        else:
            result['decision'] = 'review_exact_weak_metadata'
    elif linked_score >= min_evidence:
        if linked_conflict:
            result['decision'] = 'review_replacement_conflict'
        else:
            result['decision'] = 'replacement_confirmed'
    else:
        result['decision'] = 'review_disagreement'
    return result


def _load_cache(path):
    try:
        with path.open(encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    return data.get('records', {})


def _save_cache(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    payload = {
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'records': records,
    }
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def fetch_semantic_scholar_records(arxiv_ids, cache_path, refresh=False,
                                   batch_size=450, request_delay=1.0):
    """Fetch arXiv-linked records in batches, retaining a local API cache."""
    records = {} if refresh else _load_cache(cache_path)
    missing = [arxiv_id for arxiv_id in arxiv_ids if arxiv_id not in records]
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT

    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        response = None
        for attempt in range(6):
            response = session.post(
                SEMANTIC_SCHOLAR_BATCH_API,
                params={'fields': 'title,externalIds,authors,publicationDate'},
                json={'ids': [f'ARXIV:{arxiv_id}' for arxiv_id in batch]},
                timeout=45,
            )
            if response.status_code != 429:
                response.raise_for_status()
                break
            retry_after = response.headers.get('Retry-After')
            wait = float(retry_after) if retry_after else min(2 ** attempt, 30)
            time.sleep(wait)
        else:
            raise RuntimeError('Semantic Scholar rate limit did not clear')

        data = response.json()
        if len(data) != len(batch):
            raise RuntimeError('Semantic Scholar batch response length mismatch')
        records.update(dict(zip(batch, data)))
        _save_cache(cache_path, records)
        print(f'Fetched Semantic Scholar evidence for {len(batch)} papers.')
        if start + batch_size < len(missing):
            time.sleep(request_delay)
    return records


def fetch_crossref_records(dois, cache_path, refresh=False, request_delay=0.1):
    """Fetch current Crossref metadata for replacement DOI evidence."""
    records = {} if refresh else _load_cache(cache_path)
    missing = [doi for doi in dois if doi not in records]
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT

    for index, doi in enumerate(missing, start=1):
        response = None
        for attempt in range(6):
            response = session.get(
                f'{CROSSREF_WORK_API}/{quote(doi, safe="")}',
                params={'mailto': 'per.alexandersson@math.su.se'},
                timeout=30,
            )
            if response.status_code == 404:
                records[doi] = None
                break
            if response.status_code != 429:
                response.raise_for_status()
                records[doi] = response.json().get('message')
                break
            retry_after = response.headers.get('Retry-After')
            wait = float(retry_after) if retry_after else min(2 ** attempt, 30)
            time.sleep(wait)
        else:
            raise RuntimeError('Crossref rate limit did not clear')

        _save_cache(cache_path, records)
        if index % 25 == 0 or index == len(missing):
            print(f'Fetched Crossref evidence for {index}/{len(missing)} DOIs.')
        if index < len(missing):
            time.sleep(request_delay)
    return records


def fetch_doi_resolver_records(dois, cache_path, refresh=False,
                               request_delay=0.1):
    """Fetch registration-agency-neutral CSL metadata through doi.org."""
    records = {} if refresh else _load_cache(cache_path)
    missing = [doi for doi in dois if doi not in records]
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'application/vnd.citationstyles.csl+json',
    })

    for index, doi in enumerate(missing, start=1):
        response = None
        for attempt in range(6):
            response = session.get(
                f'https://doi.org/{quote(doi, safe="")}',
                timeout=30,
            )
            if response.status_code in (404, 406):
                records[doi] = None
                break
            if response.status_code != 429:
                response.raise_for_status()
                try:
                    records[doi] = response.json()
                except ValueError:
                    records[doi] = None
                break
            retry_after = response.headers.get('Retry-After')
            wait = float(retry_after) if retry_after else min(2 ** attempt, 30)
            time.sleep(wait)
        else:
            raise RuntimeError('DOI resolver rate limit did not clear')

        _save_cache(cache_path, records)
        if index % 25 == 0 or index == len(missing):
            print(f'Fetched DOI resolver evidence for {index}/{len(missing)} DOIs.')
        if index < len(missing):
            time.sleep(request_delay)
    return records


def _csl_as_crossref_record(record, doi):
    """Adapt CSL JSON fields to the shape consumed by ``score_match``."""
    if not record:
        return None
    adapted = dict(record)
    title = adapted.get('title') or ''
    if isinstance(title, str):
        adapted['title'] = [title]
    container = adapted.get('container-title') or ''
    if isinstance(container, str):
        adapted['container-title'] = [container]
    adapted['DOI'] = normalize_doi(adapted.get('DOI') or doi)
    return adapted


def _is_repository_metadata(record):
    """Return whether CSL metadata describes a repository copy, not a work."""
    text = ' '.join(str((record or {}).get(key) or '') for key in (
        'publisher', 'container-title', 'URL', 'url',
    )).casefold()
    return (
        'digital repository' in text
        or 'institutional repository' in text
        or '/handle/' in text
    )


def _record_title(record):
    title = (record or {}).get('title') or ''
    return ' '.join(title) if isinstance(title, list) else str(title)


def _record_authors(record):
    return [
        (
            f"{author.get('family', '')}, {author.get('given', '')}"
        ).strip(', ')
        for author in (record or {}).get('author', [])
        if author.get('family') or author.get('given')
    ]


def _record_values(record, key):
    value = (record or {}).get(key) or []
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def _record_years(record):
    years = set()
    for field in ('published-print', 'published-online', 'issued', 'created'):
        parts = ((record or {}).get(field) or {}).get('date-parts', [[]])
        if parts and parts[0]:
            years.add(str(parts[0][0]))
    return years


def _compact_bibliographic_value(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def _reference_contains_volume(reference, record):
    normalized_reference = normalize_title(reference)
    for volume in _record_values(record, 'volume'):
        normalized_volume = normalize_title(volume)
        if normalized_volume and re.search(
            rf'(?<![a-z0-9]){re.escape(normalized_volume)}(?![a-z0-9])',
            normalized_reference,
        ):
            return True
    return False


def _reference_contains_locator(reference, record):
    reference_tokens = {
        _compact_bibliographic_value(token)
        for token in re.findall(
            r'[a-z]*\d+(?:\.\d+)*',
            str(reference or '').casefold(),
        )
    }
    for field in ('page', 'article-number'):
        for locator in _record_values(record, field):
            locator_tokens = [
                _compact_bibliographic_value(token)
                for token in re.findall(
                    r'[a-z]*\d+(?:\.\d+)*',
                    str(locator).casefold(),
                )
            ]
            if locator_tokens and len(locator_tokens[0]) >= 2:
                if locator_tokens[0] in reference_tokens:
                    return True
    return False


def _reference_container_coverage(reference, record):
    reference_tokens = set(normalize_title(reference).split())
    reference_tokens -= _REFERENCE_STOPWORDS
    best = 0.0
    for field in ('container-title', 'short-container-title'):
        for container in _record_values(record, field):
            container_tokens = set(normalize_title(container).split())
            container_tokens -= _REFERENCE_STOPWORDS
            if container_tokens:
                best = max(
                    best,
                    len(container_tokens & reference_tokens)
                    / len(container_tokens),
                )
    return best


def is_known_doi_less_journal(reference):
    """Return whether the reference names a deliberately DOI-less journal."""
    normalized = normalize_title(reference)
    return any(name in normalized for name in _KNOWN_DOI_LESS_JOURNALS)


def journal_reference_evidence(reference, record):
    """Compare a free-form arXiv journal reference with registry metadata."""
    years = _record_years(record)
    year_match = any(year in str(reference or '') for year in years)
    volume_match = _reference_contains_volume(reference, record)
    locator_match = _reference_contains_locator(reference, record)
    container_coverage = _reference_container_coverage(reference, record)
    record_has_locator = bool(
        _record_values(record, 'page')
        or _record_values(record, 'article-number')
    )
    bibliographic_match = year_match and (
        (locator_match and (volume_match or container_coverage >= 0.40))
        or (
            not record_has_locator
            and volume_match
            and container_coverage >= 0.80
        )
    )
    return {
        'year_match': year_match,
        'volume_match': volume_match,
        'locator_match': locator_match,
        'record_has_locator': record_has_locator,
        'container_coverage': round(container_coverage, 3),
        'bibliographic_match': bibliographic_match,
    }


def enrich_replacement_decisions(decisions, candidates_by_id, records,
                                 min_evidence=0.85):
    """Require current Crossref metadata before approving a replacement DOI."""
    for decision in decisions:
        if decision['decision'] != 'replacement_confirmed':
            continue
        candidate = candidates_by_id[decision['candidate_id']]
        record = records.get(decision['linked_doi'])
        if not record:
            decision['decision'] = 'review_replacement_no_crossref'
            continue
        confidence, title, year = score_match(
            candidate.get('paper_title') or '',
            candidate.get('paper_authors') or [],
            candidate.get('published_date'),
            record,
            paper_published_date=candidate.get('published_date'),
        )
        decision['replacement_metadata_source'] = 'crossref'
        decision['replacement_metadata_score'] = confidence
        decision['replacement_metadata_title'] = title
        decision['replacement_metadata_year'] = year
        decision['replacement_metadata_authors'] = '; '.join(
            (
                f"{author.get('family', '')}, {author.get('given', '')}"
            ).strip(', ')
            for author in record.get('author', [])
            if author.get('family') or author.get('given')
        )
        if (
            normalize_doi(record.get('DOI')) == decision['linked_doi']
            and confidence >= min_evidence
        ):
            decision['decision'] = 'approve_replacement'
        else:
            decision['decision'] = 'review_replacement_crossref_mismatch'


def enrich_resolver_replacement_decisions(decisions, candidates_by_id,
                                          records, min_evidence=0.85):
    """Validate non-Crossref replacements through DOI content negotiation."""
    for decision in decisions:
        if decision['decision'] != 'review_replacement_no_crossref':
            continue
        candidate = candidates_by_id[decision['candidate_id']]
        record = _csl_as_crossref_record(
            records.get(decision['linked_doi']),
            decision['linked_doi'],
        )
        if not record:
            decision['decision'] = 'review_replacement_no_resolver_metadata'
            continue
        if _is_repository_metadata(record):
            decision['decision'] = 'review_replacement_repository'
            continue
        confidence, title, year = score_match(
            candidate.get('paper_title') or '',
            candidate.get('paper_authors') or [],
            candidate.get('published_date'),
            record,
            paper_published_date=candidate.get('published_date'),
        )
        decision['replacement_metadata_source'] = 'doi_resolver'
        decision['replacement_metadata_score'] = confidence
        decision['replacement_metadata_title'] = title
        decision['replacement_metadata_year'] = year
        decision['replacement_metadata_authors'] = '; '.join(
            (
                f"{author.get('family', '')}, {author.get('given', '')}"
            ).strip(', ')
            for author in record.get('author', [])
            if author.get('family') or author.get('given')
        )
        if (
            normalize_doi(record.get('DOI')) == decision['linked_doi']
            and confidence >= min_evidence
        ):
            decision['decision'] = 'approve_replacement'
        else:
            decision['decision'] = 'review_replacement_resolver_mismatch'


def enrich_metadata_decisions(decisions, candidates_by_id, records,
                              min_evidence=0.95):
    """Revalidate exact stored metadata directly against current Crossref."""
    for decision in decisions:
        if decision['decision'] != 'metadata_exact':
            continue
        candidate = candidates_by_id[decision['candidate_id']]
        record = records.get(decision['queued_doi'])
        if not record:
            decision['decision'] = 'review_metadata_no_crossref'
            continue
        confidence, title, year = score_match(
            candidate.get('paper_title') or '',
            candidate.get('paper_authors') or [],
            candidate.get('published_date'),
            record,
            paper_published_date=candidate.get('published_date'),
        )
        decision['metadata_crossref_score'] = confidence
        decision['metadata_crossref_title'] = title
        decision['metadata_crossref_year'] = year
        if (
            normalize_doi(record.get('DOI')) == decision['queued_doi']
            and confidence >= min_evidence
        ):
            decision['decision'] = 'approve_metadata_exact'
        else:
            decision['decision'] = 'review_metadata_crossref_mismatch'


def enrich_exact_external_decisions(decisions, candidates_by_id,
                                    crossref_records, resolver_records,
                                    min_title=0.45, min_author=0.80):
    """Validate weak exact DOI links with live metadata and author coverage."""
    for decision in decisions:
        if decision['decision'] != 'review_exact_weak_metadata':
            continue
        candidate = candidates_by_id[decision['candidate_id']]
        doi = decision['queued_doi']
        record = crossref_records.get(doi)
        source = 'crossref'
        if not record:
            record = _csl_as_crossref_record(resolver_records.get(doi), doi)
            source = 'doi_resolver'
        if not record:
            decision['decision'] = 'review_exact_no_live_metadata'
            continue
        title = _record_title(record)
        authors = _record_authors(record)
        live_title_score = title_similarity(
            candidate.get('paper_title') or '', title)
        live_author_score = author_coverage_similarity(
            candidate.get('paper_authors') or [], authors)
        decision['exact_external_metadata_source'] = source
        decision['exact_external_title_score'] = round(live_title_score, 3)
        decision['exact_external_author_score'] = round(live_author_score, 3)
        decision['exact_external_confidence'] = round(max(
            decision['stored_match_score'],
            decision['linked_match_score'],
            (live_title_score + live_author_score) / 2,
        ), 3)
        if (
            normalize_doi(record.get('DOI')) == doi
            and live_title_score >= min_title
            and live_author_score >= min_author
        ):
            decision['decision'] = 'approve_exact_external'
        else:
            decision['decision'] = 'review_exact_live_metadata_mismatch'


def enrich_journal_reference_decisions(
    decisions,
    candidates_by_id,
    crossref_records,
    resolver_records,
    min_title=0.45,
    min_author=0.80,
):
    """Use arXiv journal references to corroborate queued publication DOIs."""
    for decision in decisions:
        candidate = candidates_by_id[decision['candidate_id']]
        reference = candidate.get('journal_ref') or ''
        if not reference:
            continue
        if is_known_doi_less_journal(reference):
            decision['decision'] = 'skip_known_doi_less'
            continue
        if decision['queued_conflict']:
            continue

        doi = decision['queued_doi']
        record = crossref_records.get(doi)
        source = 'crossref'
        if not record:
            record = _csl_as_crossref_record(resolver_records.get(doi), doi)
            source = 'doi_resolver'
        if not record or normalize_doi(record.get('DOI')) != doi:
            continue

        evidence = journal_reference_evidence(reference, record)
        title_score = title_similarity(
            candidate.get('paper_title') or '', _record_title(record))
        author_score = author_coverage_similarity(
            candidate.get('paper_authors') or [], _record_authors(record))
        decision.update({
            'journal_metadata_source': source,
            'journal_title_score': round(title_score, 3),
            'journal_author_score': round(author_score, 3),
            **{f'journal_{key}': value for key, value in evidence.items()},
        })
        if (
            evidence['bibliographic_match']
            and title_score >= min_title
            and author_score >= min_author
        ):
            decision['journal_reference_confidence'] = round(
                0.50 * title_score + 0.25 * author_score + 0.25,
                3,
            )
            decision['decision'] = 'approve_journal_reference'


def get_pending_candidates(cursor, limit=None):
    limit_sql = ' LIMIT %s' if limit else ''
    params = [limit] if limit else []
    cursor.execute(f"""
        SELECT dc.id, dc.paper_id, dc.doi, dc.confidence,
               dc.crossref_title, dc.crossref_authors, dc.crossref_year,
               p.arxiv_id, p.title AS paper_title, p.published_date,
               p.journal_ref,
               p.doi AS current_doi
        FROM doi_candidates dc
        JOIN papers p ON p.id = dc.paper_id
        WHERE dc.status = 'pending'
        ORDER BY dc.id
        {limit_sql}
    """, params)
    candidates = cursor.fetchall()
    paper_ids = [candidate['paper_id'] for candidate in candidates]
    authors = {}
    if paper_ids:
        placeholders = ','.join(['%s'] * len(paper_ids))
        cursor.execute(f"""
            SELECT pa.paper_id, a.name
            FROM paper_authors pa
            JOIN authors a ON a.id = pa.author_id
            WHERE pa.paper_id IN ({placeholders})
            ORDER BY pa.paper_id, pa.author_order
        """, paper_ids)
        for row in cursor.fetchall():
            authors.setdefault(row['paper_id'], []).append(row['name'])
    for candidate in candidates:
        candidate['paper_authors'] = authors.get(candidate['paper_id'], [])
    return candidates


def get_conflicting_dois(cursor):
    """Return assigned DOIs and DOIs queued for more than one paper."""
    cursor.execute("SELECT doi FROM papers WHERE doi IS NOT NULL")
    conflicts = {normalize_doi(row['doi']) for row in cursor.fetchall()}
    cursor.execute("""
        SELECT doi
        FROM doi_candidates
        WHERE status = 'pending'
        GROUP BY doi
        HAVING COUNT(DISTINCT paper_id) > 1
    """)
    conflicts.update(normalize_doi(row['doi']) for row in cursor.fetchall())
    return conflicts


def get_assigned_papers_by_doi(cursor, candidates):
    """Return DOI assignments, including each assigned paper's authors."""
    dois = sorted({normalize_doi(item['doi']) for item in candidates})
    if not dois:
        return {}
    placeholders = ','.join(['%s'] * len(dois))
    cursor.execute(f"""
        SELECT id AS paper_id, arxiv_id, doi, doi_status,
               title AS paper_title
        FROM papers
        WHERE doi IN ({placeholders})
    """, dois)
    assignments = cursor.fetchall()
    paper_ids = [item['paper_id'] for item in assignments]
    authors = {}
    if paper_ids:
        author_placeholders = ','.join(['%s'] * len(paper_ids))
        cursor.execute(f"""
            SELECT pa.paper_id, a.name
            FROM paper_authors pa
            JOIN authors a ON a.id = pa.author_id
            WHERE pa.paper_id IN ({author_placeholders})
            ORDER BY pa.paper_id, pa.author_order
        """, paper_ids)
        for row in cursor.fetchall():
            authors.setdefault(row['paper_id'], []).append(row['name'])
    by_doi = {}
    for assignment in assignments:
        assignment['paper_authors'] = authors.get(assignment['paper_id'], [])
        by_doi.setdefault(normalize_doi(assignment['doi']), []).append(assignment)
    return by_doi


def enrich_conflict_decisions(decisions, candidates_by_id, assignments_by_doi,
                              min_assigned_score=0.90, margin=0.15):
    """Reject a queued conflict only when the existing assignment is stronger."""
    for decision in decisions:
        if not decision['queued_conflict']:
            continue
        assignments = assignments_by_doi.get(decision['queued_doi'], [])
        if not assignments:
            continue
        candidate = candidates_by_id[decision['candidate_id']]
        crossref_authors = _crossref_authors(candidate.get('crossref_authors'))
        scored = [
            (
                score_title_author_match(
                    assignment.get('paper_title') or '',
                    assignment.get('paper_authors') or [],
                    candidate.get('crossref_title') or '',
                    crossref_authors,
                ),
                assignment,
            )
            for assignment in assignments
            if assignment['paper_id'] != decision['paper_id']
        ]
        if not scored:
            continue
        assigned_score, best = max(scored, key=lambda item: item[0])
        decision['conflict_assigned_score'] = round(assigned_score, 3)
        decision['conflict_assigned_paper_id'] = best['paper_id']
        decision['conflict_assigned_arxiv_id'] = best['arxiv_id']
        decision['conflict_assigned_status'] = best['doi_status']
        trusted_assignment = (
            best['doi_status'] in ('arxiv', 'verified')
            or assigned_score >= 0.97
        )
        if (
            trusted_assignment
            and assigned_score >= min_assigned_score
            and assigned_score >= decision['stored_match_score'] + margin
        ):
            decision['decision'] = 'reject_conflict_assigned_better'
        elif decision['stored_match_score'] >= assigned_score + margin:
            decision['decision'] = 'review_conflict_candidate_better'
        else:
            decision['decision'] = 'review_conflict_ambiguous'


def apply_confirmed(cursor, decisions):
    """Apply high-certainty exact agreements after rechecking every guard."""
    applied = 0
    for decision in decisions:
        if decision['decision'] != 'approve_confirmed':
            continue
        cursor.execute("""
            SELECT dc.paper_id, dc.doi, dc.status, p.doi AS current_doi
            FROM doi_candidates dc
            JOIN papers p ON p.id = dc.paper_id
            WHERE dc.id = %s
            FOR UPDATE
        """, (decision['candidate_id'],))
        current = cursor.fetchone()
        if not current or current['status'] != 'pending' or current['current_doi']:
            continue
        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM papers
            WHERE doi = %s AND id <> %s
        """, (current['doi'], current['paper_id']))
        if cursor.fetchone()['count']:
            continue
        confidence = max(
            decision['stored_match_score'], decision['linked_match_score'])
        cursor.execute("""
            UPDATE papers
            SET doi = %s, doi_status = 'auto', doi_confidence = %s,
                doi_checked_at = NOW()
            WHERE id = %s AND doi IS NULL
        """, (current['doi'], confidence, current['paper_id']))
        if cursor.rowcount != 1:
            continue
        cursor.execute("""
            UPDATE doi_candidates
            SET status = 'approved', reviewed_at = NOW()
            WHERE id = %s AND status = 'pending'
        """, (decision['candidate_id'],))
        cursor.execute("""
            UPDATE doi_candidates
            SET status = 'rejected', reviewed_at = NOW()
            WHERE paper_id = %s AND id <> %s AND status = 'pending'
        """, (current['paper_id'], decision['candidate_id']))
        applied += 1
    return applied


def apply_replacements(cursor, decisions):
    """Replace a stale queued candidate after two-source DOI confirmation."""
    applied = 0
    for decision in decisions:
        if decision['decision'] != 'approve_replacement':
            continue
        cursor.execute("""
            SELECT dc.paper_id, dc.status, p.doi AS current_doi
            FROM doi_candidates dc
            JOIN papers p ON p.id = dc.paper_id
            WHERE dc.id = %s
            FOR UPDATE
        """, (decision['candidate_id'],))
        current = cursor.fetchone()
        if not current or current['status'] != 'pending' or current['current_doi']:
            continue
        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM papers
            WHERE doi = %s AND id <> %s
        """, (decision['linked_doi'], current['paper_id']))
        if cursor.fetchone()['count']:
            continue
        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM doi_candidates
            WHERE doi = %s AND paper_id <> %s AND status = 'pending'
        """, (decision['linked_doi'], current['paper_id']))
        if cursor.fetchone()['count']:
            continue

        confidence = decision['replacement_metadata_score']
        cursor.execute("""
            UPDATE papers
            SET doi = %s, doi_status = 'auto', doi_confidence = %s,
                doi_checked_at = NOW()
            WHERE id = %s AND doi IS NULL
        """, (decision['linked_doi'], confidence, current['paper_id']))
        if cursor.rowcount != 1:
            continue
        cursor.execute("""
            UPDATE doi_candidates
            SET status = 'rejected', reviewed_at = NOW()
            WHERE paper_id = %s AND status = 'pending'
        """, (current['paper_id'],))
        cursor.execute("""
            INSERT INTO doi_candidates
                (paper_id, doi, confidence, crossref_title, crossref_authors,
                 crossref_year, status, reviewed_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'approved', NOW())
            ON DUPLICATE KEY UPDATE
                confidence = VALUES(confidence),
                crossref_title = VALUES(crossref_title),
                crossref_authors = VALUES(crossref_authors),
                crossref_year = VALUES(crossref_year),
                status = 'approved',
                reviewed_at = NOW()
        """, (
            current['paper_id'],
            decision['linked_doi'],
            confidence,
            decision['replacement_metadata_title'],
            decision['replacement_metadata_authors'],
            decision['replacement_metadata_year'],
        ))
        applied += 1
    return applied


def apply_exact_metadata(cursor, decisions):
    """Approve candidates whose exact metadata survived a live Crossref check."""
    eligible = []
    for decision in decisions:
        if decision['decision'] != 'approve_metadata_exact':
            continue
        eligible.append({
            **decision,
            'decision': 'approve_confirmed',
            'stored_match_score': decision['metadata_crossref_score'],
            'linked_match_score': decision['metadata_crossref_score'],
        })
    return apply_confirmed(cursor, eligible)


def apply_conflict_rejections(cursor, decisions):
    """Reject stale candidates while leaving existing DOI assignments intact."""
    applied = 0
    for decision in decisions:
        if decision['decision'] != 'reject_conflict_assigned_better':
            continue
        cursor.execute("""
            UPDATE doi_candidates
            SET status = 'rejected', reviewed_at = NOW()
            WHERE id = %s AND status = 'pending'
              AND EXISTS (
                  SELECT 1 FROM papers p
                  WHERE p.doi = doi_candidates.doi
                    AND p.id <> doi_candidates.paper_id
              )
        """, (decision['candidate_id'],))
        applied += cursor.rowcount
    return applied


def apply_exact_external(cursor, decisions):
    """Approve independently linked DOIs corroborated by live metadata."""
    eligible = []
    for decision in decisions:
        if decision['decision'] != 'approve_exact_external':
            continue
        eligible.append({
            **decision,
            'decision': 'approve_confirmed',
            'stored_match_score': decision['exact_external_confidence'],
            'linked_match_score': decision['exact_external_confidence'],
        })
    return apply_confirmed(cursor, eligible)


def apply_journal_references(cursor, decisions):
    """Approve queued DOIs corroborated by arXiv bibliographic references."""
    eligible = []
    for decision in decisions:
        if decision['decision'] != 'approve_journal_reference':
            continue
        eligible.append({
            **decision,
            'decision': 'approve_confirmed',
            'stored_match_score': decision['journal_reference_confidence'],
            'linked_match_score': decision['journal_reference_confidence'],
        })
    return apply_confirmed(cursor, eligible)


def apply_known_doi_less(cursor, decisions):
    """Reject candidates and mark papers from confirmed DOI-less venues."""
    applied = 0
    seen_papers = set()
    for decision in decisions:
        if (
            decision['decision'] != 'skip_known_doi_less'
            or decision['paper_id'] in seen_papers
        ):
            continue
        seen_papers.add(decision['paper_id'])
        cursor.execute("""
            SELECT id, doi, journal_ref
            FROM papers
            WHERE id = %s
            FOR UPDATE
        """, (decision['paper_id'],))
        paper = cursor.fetchone()
        if (
            not paper
            or paper['doi']
            or not is_known_doi_less_journal(paper['journal_ref'])
        ):
            continue
        cursor.execute("""
            UPDATE papers
            SET doi_status = 'skipped', doi_checked_at = NOW()
            WHERE id = %s AND doi IS NULL
        """, (paper['id'],))
        if cursor.rowcount != 1:
            continue
        cursor.execute("""
            UPDATE doi_candidates
            SET status = 'rejected', reviewed_at = NOW()
            WHERE paper_id = %s AND status = 'pending'
        """, (paper['id'],))
        applied += 1
    return applied


def write_report(path, decisions, confirmed_applied, replacements_applied,
                 metadata_applied, conflicts_rejected, exact_external_applied,
                 journal_applied, known_doi_less_applied):
    counts = Counter(item['decision'] for item in decisions)
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'applied': {
            'confirmed': confirmed_applied,
            'replacements': replacements_applied,
            'metadata_exact': metadata_applied,
            'conflicts_rejected': conflicts_rejected,
            'exact_external': exact_external_applied,
            'journal_references': journal_applied,
            'known_doi_less': known_doi_less_applied,
            'total': (
                confirmed_applied + replacements_applied + metadata_applied
                + conflicts_rejected + exact_external_applied + journal_applied
                + known_doi_less_applied
            ),
        },
        'counts': dict(sorted(counts.items())),
        'candidates': decisions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
    os.chmod(path, 0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-confirmed', action='store_true',
                        help='approve only exact, strong, non-conflicting matches')
    parser.add_argument('--validate-replacements', action='store_true',
                        help='cross-check alternative DOIs through Crossref')
    parser.add_argument('--apply-replacements', action='store_true',
                        help='apply alternatives confirmed by Crossref')
    parser.add_argument('--validate-metadata', action='store_true',
                        help='revalidate exact stored metadata through Crossref')
    parser.add_argument('--apply-metadata', action='store_true',
                        help='apply exact metadata matches confirmed by Crossref')
    parser.add_argument('--validate-conflicts', action='store_true',
                        help='compare queued conflicts with existing assignments')
    parser.add_argument('--apply-conflict-rejections', action='store_true',
                        help='reject conflicts whose existing assignment is stronger')
    parser.add_argument('--validate-exact-external', action='store_true',
                        help='validate weak exact DOI links with live metadata')
    parser.add_argument('--apply-exact-external', action='store_true',
                        help='apply live-metadata-confirmed exact DOI links')
    parser.add_argument('--validate-journal-references', action='store_true',
                        help='compare queued DOI metadata with journal references')
    parser.add_argument('--apply-journal-references', action='store_true',
                        help='apply DOIs corroborated by journal references')
    parser.add_argument('--apply-known-doi-less', action='store_true',
                        help='reject candidates for known DOI-less journals')
    parser.add_argument('--min-evidence', type=float, default=0.85,
                        help='minimum title/author evidence score (default 0.85)')
    parser.add_argument('--min-metadata-evidence', type=float, default=0.95,
                        help='minimum live score for metadata-only matches')
    parser.add_argument('--conflict-min-assigned', type=float, default=0.90)
    parser.add_argument('--conflict-margin', type=float, default=0.15)
    parser.add_argument('--exact-min-title', type=float, default=0.45)
    parser.add_argument('--exact-min-author', type=float, default=0.80)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--batch-size', type=int, default=450)
    parser.add_argument('--request-delay', type=float, default=1.0)
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--crossref-cache', type=Path,
                        default=DEFAULT_CROSSREF_CACHE)
    parser.add_argument('--resolver-cache', type=Path,
                        default=DEFAULT_RESOLVER_CACHE)
    parser.add_argument('--crossref-delay', type=float, default=0.1)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args(argv)

    if not 0.0 <= args.min_evidence <= 1.0:
        parser.error('--min-evidence must be between 0 and 1')
    if not 0.0 <= args.min_metadata_evidence <= 1.0:
        parser.error('--min-metadata-evidence must be between 0 and 1')
    if not 0.0 <= args.conflict_min_assigned <= 1.0:
        parser.error('--conflict-min-assigned must be between 0 and 1')
    if not 0.0 <= args.conflict_margin <= 1.0:
        parser.error('--conflict-margin must be between 0 and 1')
    if not 0.0 <= args.exact_min_title <= 1.0:
        parser.error('--exact-min-title must be between 0 and 1')
    if not 0.0 <= args.exact_min_author <= 1.0:
        parser.error('--exact-min-author must be between 0 and 1')
    if not 1 <= args.batch_size <= 500:
        parser.error('--batch-size must be between 1 and 500')

    connection = pymysql.connect(
        **DB_CONFIG,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            candidates = get_pending_candidates(cursor, limit=args.limit)
            conflicting_dois = get_conflicting_dois(cursor)
            base_ids = [arxiv_base_id(item['arxiv_id']) for item in candidates]
            records = fetch_semantic_scholar_records(
                base_ids,
                args.cache,
                refresh=args.refresh,
                batch_size=args.batch_size,
                request_delay=args.request_delay,
            )
            decisions = [
                classify_candidate(
                    candidate,
                    records.get(arxiv_base_id(candidate['arxiv_id'])),
                    conflicting_dois,
                    min_evidence=args.min_evidence,
                )
                for candidate in candidates
            ]
            candidates_by_id = {item['id']: item for item in candidates}
            crossref_records = {}
            resolver_records = {}
            if (
                args.validate_replacements or args.apply_replacements
                or args.validate_metadata or args.apply_metadata
                or args.validate_exact_external or args.apply_exact_external
                or args.validate_journal_references
                or args.apply_journal_references or args.apply_known_doi_less
            ):
                replacement_dois = sorted({
                    item['linked_doi']
                    for item in decisions
                    if item['decision'] == 'replacement_confirmed'
                }) if (args.validate_replacements or args.apply_replacements) else []
                metadata_dois = sorted({
                    item['queued_doi']
                    for item in decisions
                    if item['decision'] == 'metadata_exact'
                }) if (args.validate_metadata or args.apply_metadata) else []
                exact_external_dois = sorted({
                    item['queued_doi']
                    for item in decisions
                    if item['decision'] == 'review_exact_weak_metadata'
                }) if (
                    args.validate_exact_external or args.apply_exact_external
                ) else []
                journal_dois = sorted({
                    item['queued_doi']
                    for item in decisions
                    if candidates_by_id[item['candidate_id']].get('journal_ref')
                }) if (
                    args.validate_journal_references
                    or args.apply_journal_references
                    or args.apply_known_doi_less
                ) else []
                crossref_records = fetch_crossref_records(
                    sorted(
                        set(replacement_dois) | set(metadata_dois)
                        | set(exact_external_dois)
                        | set(journal_dois)
                    ),
                    args.crossref_cache,
                    refresh=args.refresh,
                    request_delay=args.crossref_delay,
                )
                if args.validate_replacements or args.apply_replacements:
                    enrich_replacement_decisions(
                        decisions,
                        candidates_by_id,
                        crossref_records,
                        min_evidence=args.min_evidence,
                    )
                    replacement_resolver_dois = {
                        item['linked_doi']
                        for item in decisions
                        if item['decision'] == 'review_replacement_no_crossref'
                    }
                else:
                    replacement_resolver_dois = set()
                exact_resolver_dois = {
                    doi for doi in exact_external_dois
                    if not crossref_records.get(doi)
                }
                journal_resolver_dois = {
                    doi for doi in journal_dois
                    if not crossref_records.get(doi)
                }
                resolver_dois = sorted(
                    replacement_resolver_dois | exact_resolver_dois
                    | journal_resolver_dois)
                resolver_records = fetch_doi_resolver_records(
                    resolver_dois,
                    args.resolver_cache,
                    refresh=args.refresh,
                    request_delay=args.crossref_delay,
                )
                if args.validate_replacements or args.apply_replacements:
                    enrich_resolver_replacement_decisions(
                        decisions,
                        candidates_by_id,
                        resolver_records,
                        min_evidence=args.min_evidence,
                    )
                if args.validate_metadata or args.apply_metadata:
                    enrich_metadata_decisions(
                        decisions,
                        candidates_by_id,
                        crossref_records,
                        min_evidence=args.min_metadata_evidence,
                    )
                if args.validate_exact_external or args.apply_exact_external:
                    enrich_exact_external_decisions(
                        decisions,
                        candidates_by_id,
                        crossref_records,
                        resolver_records,
                        min_title=args.exact_min_title,
                        min_author=args.exact_min_author,
                    )
            if args.validate_conflicts or args.apply_conflict_rejections:
                assignments_by_doi = get_assigned_papers_by_doi(
                    cursor, candidates)
                enrich_conflict_decisions(
                    decisions,
                    candidates_by_id,
                    assignments_by_doi,
                    min_assigned_score=args.conflict_min_assigned,
                    margin=args.conflict_margin,
                )
            if (
                args.validate_journal_references
                or args.apply_journal_references or args.apply_known_doi_less
            ):
                enrich_journal_reference_decisions(
                    decisions,
                    candidates_by_id,
                    crossref_records,
                    resolver_records,
                    min_title=args.exact_min_title,
                    min_author=args.exact_min_author,
                )
            applied = 0
            replacements_applied = 0
            metadata_applied = 0
            conflicts_rejected = 0
            exact_external_applied = 0
            journal_applied = 0
            known_doi_less_applied = 0
            if args.apply_confirmed:
                applied = apply_confirmed(cursor, decisions)
            if args.apply_replacements:
                replacements_applied = apply_replacements(cursor, decisions)
            if args.apply_metadata:
                metadata_applied = apply_exact_metadata(cursor, decisions)
            if args.apply_conflict_rejections:
                conflicts_rejected = apply_conflict_rejections(
                    cursor, decisions)
            if args.apply_exact_external:
                exact_external_applied = apply_exact_external(
                    cursor, decisions)
            if args.apply_journal_references:
                journal_applied = apply_journal_references(cursor, decisions)
            if args.apply_known_doi_less:
                known_doi_less_applied = apply_known_doi_less(
                    cursor, decisions)
            if (
                args.apply_confirmed or args.apply_replacements
                or args.apply_metadata or args.apply_conflict_rejections
                or args.apply_exact_external
                or args.apply_journal_references or args.apply_known_doi_less
            ):
                connection.commit()
                if (
                    applied or replacements_applied or metadata_applied
                    or exact_external_applied or journal_applied
                    or known_doi_less_applied
                ):
                    mark_index_cache_dirty()
            else:
                connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    counts = Counter(item['decision'] for item in decisions)
    print(f'Pending candidates examined: {len(decisions)}')
    for decision, count in sorted(counts.items()):
        print(f'  {decision}: {count}')
    print(f'Applied confirmed approvals: {applied}')
    print(f'Applied replacement approvals: {replacements_applied}')
    print(f'Applied exact-metadata approvals: {metadata_applied}')
    print(f'Applied conflict rejections: {conflicts_rejected}')
    print(f'Applied exact-external approvals: {exact_external_applied}')
    print(f'Applied journal-reference approvals: {journal_applied}')
    print(f'Applied known DOI-less skips: {known_doi_less_applied}')
    if args.report:
        write_report(
            args.report,
            decisions,
            applied,
            replacements_applied,
            metadata_applied,
            conflicts_rejected,
            exact_external_applied,
            journal_applied,
            known_doi_less_applied,
        )
        print(f'Report: {args.report}')
    if (
        not args.apply_confirmed and not args.apply_replacements
        and not args.apply_metadata and not args.apply_conflict_rejections
        and not args.apply_exact_external
        and not args.apply_journal_references and not args.apply_known_doi_less
    ):
        print('Dry run only; database unchanged.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
