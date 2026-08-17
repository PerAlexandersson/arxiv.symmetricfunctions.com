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
from title_matching import normalize_title, score_title_author_match


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

    if not linked_doi:
        if (
            not queued_conflict
            and exact_stored_title
            and stored_score >= min_evidence
        ):
            result['decision'] = 'metadata_exact'
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
        decision['replacement_crossref_score'] = confidence
        decision['replacement_crossref_title'] = title
        decision['replacement_crossref_year'] = year
        decision['replacement_crossref_authors'] = '; '.join(
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


def get_pending_candidates(cursor, limit=None):
    limit_sql = ' LIMIT %s' if limit else ''
    params = [limit] if limit else []
    cursor.execute(f"""
        SELECT dc.id, dc.paper_id, dc.doi, dc.confidence,
               dc.crossref_title, dc.crossref_authors, dc.crossref_year,
               p.arxiv_id, p.title AS paper_title, p.published_date,
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

        confidence = decision['replacement_crossref_score']
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
            decision['replacement_crossref_title'],
            decision['replacement_crossref_authors'],
            decision['replacement_crossref_year'],
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


def write_report(path, decisions, confirmed_applied, replacements_applied,
                 metadata_applied):
    counts = Counter(item['decision'] for item in decisions)
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'applied': {
            'confirmed': confirmed_applied,
            'replacements': replacements_applied,
            'metadata_exact': metadata_applied,
            'total': confirmed_applied + replacements_applied + metadata_applied,
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
    parser.add_argument('--min-evidence', type=float, default=0.85,
                        help='minimum title/author evidence score (default 0.85)')
    parser.add_argument('--min-metadata-evidence', type=float, default=0.95,
                        help='minimum live score for metadata-only matches')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--batch-size', type=int, default=450)
    parser.add_argument('--request-delay', type=float, default=1.0)
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--crossref-cache', type=Path,
                        default=DEFAULT_CROSSREF_CACHE)
    parser.add_argument('--crossref-delay', type=float, default=0.1)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args(argv)

    if not 0.0 <= args.min_evidence <= 1.0:
        parser.error('--min-evidence must be between 0 and 1')
    if not 0.0 <= args.min_metadata_evidence <= 1.0:
        parser.error('--min-metadata-evidence must be between 0 and 1')
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
            if (
                args.validate_replacements or args.apply_replacements
                or args.validate_metadata or args.apply_metadata
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
                crossref_records = fetch_crossref_records(
                    sorted(set(replacement_dois) | set(metadata_dois)),
                    args.crossref_cache,
                    refresh=args.refresh,
                    request_delay=args.crossref_delay,
                )
                candidates_by_id = {item['id']: item for item in candidates}
                if args.validate_replacements or args.apply_replacements:
                    enrich_replacement_decisions(
                        decisions,
                        candidates_by_id,
                        crossref_records,
                        min_evidence=args.min_evidence,
                    )
                if args.validate_metadata or args.apply_metadata:
                    enrich_metadata_decisions(
                        decisions,
                        candidates_by_id,
                        crossref_records,
                        min_evidence=args.min_metadata_evidence,
                    )
            applied = 0
            replacements_applied = 0
            metadata_applied = 0
            if args.apply_confirmed:
                applied = apply_confirmed(cursor, decisions)
            if args.apply_replacements:
                replacements_applied = apply_replacements(cursor, decisions)
            if args.apply_metadata:
                metadata_applied = apply_exact_metadata(cursor, decisions)
            if (
                args.apply_confirmed or args.apply_replacements
                or args.apply_metadata
            ):
                connection.commit()
                if applied or replacements_applied or metadata_applied:
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
    if args.report:
        write_report(
            args.report,
            decisions,
            applied,
            replacements_applied,
            metadata_applied,
        )
        print(f'Report: {args.report}')
    if (
        not args.apply_confirmed and not args.apply_replacements
        and not args.apply_metadata
    ):
        print('Dry run only; database unchanged.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
