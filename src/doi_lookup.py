#!/usr/bin/env python3
"""
doi_lookup.py - Find DOIs for papers via the Crossref API.

Queries Crossref for papers that lack a DOI, scores matches by title/author
similarity, and inserts candidates into doi_candidates for admin review.

Usage:
    python3 doi_lookup.py                     # top 250 queued papers (default)
    python3 doi_lookup.py --batch 100         # process 100 papers
    python3 doi_lookup.py --min-age 180       # only papers published >6 months ago
    python3 doi_lookup.py --dry-run           # print matches without writing
    python3 doi_lookup.py --auto-approve 0.93 # auto-promote high-scoring matches
"""

import argparse
from datetime import date
import sys
import time

import pymysql
import requests

from config import DB_CONFIG
from title_matching import (
    author_changes,
    author_last_name as _last_name,
    normalize_title as _normalize,
    score_title_author_match,
)
from site_stats import mark_index_cache_dirty

CROSSREF_API = "https://api.crossref.org/works"
USER_AGENT = "arxiv-symmetricfunctions/1.0 (mailto:per.alexandersson@math.su.se)"
REQUEST_DELAY = 0.5  # seconds between Crossref requests
DEFAULT_BATCH_SIZE = 250
DEFAULT_MIN_AGE_DAYS = 180
DEFAULT_RECHECK_DAYS = 180
RECENT_PRIORITY_DAYS = 730


def _mark_index_cache_dirty_after_doi_changes(count):
    """Best-effort cache invalidation after visible DOI metadata changes."""
    if count <= 0:
        return
    try:
        mark_index_cache_dirty()
        print("Homepage cache rebuild scheduled.")
    except Exception as e:
        print(f"Warning: could not schedule cache rebuild: {e}", file=sys.stderr)


def _crossref_date_parts(cr_item, include_created=True, target_year=None):
    """Return a usable Crossref date, preferring one near ``target_year``."""
    fields = ['published-print', 'published-online', 'issued']

    candidates = []
    for field_order, field in enumerate(fields):
        parts = (cr_item.get(field) or {}).get('date-parts', [[]])
        if not parts or not parts[0]:
            continue
        cleaned = []
        for part in parts[0][:3]:
            try:
                cleaned.append(int(part))
            except (TypeError, ValueError):
                break
        if cleaned:
            candidates.append((cleaned, field, field_order))
    if not candidates and include_created:
        parts = (cr_item.get('created') or {}).get('date-parts', [[]])
        if parts and parts[0]:
            try:
                cleaned = [int(part) for part in parts[0][:3]]
            except (TypeError, ValueError):
                cleaned = []
            if cleaned:
                candidates.append((cleaned, 'created', len(fields)))
    if target_year is not None and candidates:
        candidates.sort(key=lambda item: (
            abs(item[0][0] - target_year), item[2]
        ))
    if candidates:
        parts, field, _ = candidates[0]
        return parts, field
    return None, None


def _paper_year_and_date(paper_year, paper_published_date=None):
    """Coerce caller input to a paper year and, when possible, a full date."""
    paper_date = None

    if paper_published_date is not None:
        if isinstance(paper_published_date, date):
            paper_date = paper_published_date
        else:
            try:
                paper_date = date.fromisoformat(str(paper_published_date)[:10])
            except ValueError:
                paper_date = None
    elif isinstance(paper_year, date):
        paper_date = paper_year

    year = None
    if paper_date is not None:
        year = paper_date.year
    elif paper_year not in (None, ''):
        try:
            year = int(str(paper_year)[:4])
        except (TypeError, ValueError):
            year = None

    return year, paper_date


def score_match(paper_title, paper_authors, paper_year, cr_item,
                paper_published_date=None):
    """Compute a match score (0-1), not a probability, for one Crossref result."""
    cr_title = ' '.join(cr_item.get('title', []))
    cr_authors = []
    for author in cr_item.get('author', []):
        full_name = (
            (author.get('family', '') + ', ' + author.get('given', '')).strip(', ')
            or author.get('name', '')
        )
        if full_name:
            cr_authors.append(full_name)

    # published_date is the first arXiv submission, not the latest revision.
    paper_year_val, _ = _paper_year_and_date(
        paper_year, paper_published_date)
    parts, _ = _crossref_date_parts(cr_item, target_year=paper_year_val)
    cr_year = parts[0] if parts else None

    # Publication 0--4 calendar years later is ordinary publication lag.
    # Deduct one percentage point per extra year, or two per year earlier.
    if cr_year is not None and paper_year_val is not None:
        lag = int(cr_year) - int(paper_year_val)
        date_penalty = 0.01 * max(lag - 4, 0) if lag >= 0 else 0.02 * -lag
    else:
        date_penalty = 0.07  # Preserve the existing unknown-date deduction.

    # Missing journal metadata deducts five points.
    has_journal = bool(cr_item.get('container-title'))
    doi_sanity = 1.0 if has_journal else 0.5

    text_author_score = score_title_author_match(
        paper_title, paper_authors, cr_title, cr_authors)
    confidence = text_author_score - 0.10 * (1.0 - doi_sanity) - date_penalty

    return round(max(0.0, min(1.0, confidence)), 3), cr_title, cr_year


def rank_crossref_matches(title, authors, year, items, paper_published_date=None):
    """Rank distinct DOIs and discount a close, plausible alternative.

    A rival scoring at least 80/100 within five points deducts up to eight
    points, linearly decreasing to zero at a five-point lead. Such ambiguity
    and contradictory coauthors require review regardless of the threshold.
    Duplicate Crossref hits for the same DOI are not competitors.
    """
    distinct = {}
    for item in items or []:
        doi = (item.get('DOI') or '').strip()
        if not doi:
            continue
        score, cr_title, cr_year = score_match(
            title, authors, year, item, paper_published_date=paper_published_date)
        names = [((a.get('family', '') + ', ' + a.get('given', '')).strip(', ')
                  or a.get('name', '')) for a in item.get('author', [])]
        changes = author_changes(authors, names)
        row = dict(doi=doi, score=score, raw_score=score, title=cr_title,
                   authors='; '.join(names), year=cr_year, author_changes=changes,
                   auto_eligible=changes['complete'] and not changes['conflicting'],
                   ambiguity_penalty=0.0, runner_up_doi=None, runner_up_score=None)
        key = doi.lower()
        if key not in distinct or score > distinct[key]['raw_score']:
            distinct[key] = row
    ranked = sorted(distinct.values(), key=lambda row: (-row['raw_score'], row['doi'].lower()))
    if len(ranked) > 1:
        best, second = ranked[:2]
        gap = best['raw_score'] - second['raw_score']
        best.update(runner_up_doi=second['doi'], runner_up_score=second['raw_score'])
        if second['raw_score'] >= 0.80 and gap < 0.05 - 1e-9:
            best['ambiguity_penalty'] = round(0.08 * (1.0 - gap / 0.05), 3)
            best['score'] = round(max(0.0, best['raw_score'] - best['ambiguity_penalty']), 3)
            best['auto_eligible'] = False
    # Keep raw ranking: penalizing the winner must not silently promote its rival.
    return ranked


def query_crossref(title, first_author_last):
    """Query Crossref, returning results or ``None`` on request failure.

    An empty list is a successful lookup with no matches.  Keeping failures
    distinct prevents callers from recording a transient 429/network error as
    a completed DOI check.
    """
    params = {
        'query.bibliographic': title,
        'rows': 3,
    }
    if first_author_last:
        params['query.author'] = first_author_last
    try:
        resp = requests.get(
            CROSSREF_API, params=params, timeout=15,
            headers={'User-Agent': USER_AGENT}
        )
        resp.raise_for_status()
        return resp.json().get('message', {}).get('items', [])
    except Exception as e:
        print(f"    Crossref error: {e}", file=sys.stderr)
        return None


def get_papers_needing_doi(cursor, batch_size, min_age_days,
                           recheck_days=180, from_date=None, to_date=None):
    """Return the highest-priority papers currently due for a DOI check.

    Skips papers with doi_checked_at within the last recheck_days,
    and papers with pending/approved candidates. Within the due queue, journal
    references come first, followed by never-checked papers between the minimum
    age and two years, older never-checked papers, and finally due rechecks.
    """
    conditions = [
        "p.doi IS NULL",
        "(p.doi_status IS NULL OR p.doi_status NOT IN ('skipped'))",
        "p.published_date <= DATE_SUB(CURDATE(), INTERVAL %s DAY)",
        "(p.doi_checked_at IS NULL OR p.doi_checked_at < DATE_SUB(NOW(), INTERVAL %s DAY))",
        """NOT EXISTS (
              SELECT 1 FROM doi_candidates dc
              WHERE dc.paper_id = p.id
                AND dc.status IN ('pending', 'approved')
          )""",
    ]
    params = [min_age_days, recheck_days]

    if from_date:
        conditions.append("p.published_date >= %s")
        params.append(from_date)
    if to_date:
        conditions.append("p.published_date <= %s")
        params.append(to_date)

    params.append(batch_size)
    cursor.execute(f"""
        SELECT p.id, p.arxiv_id, p.title, p.published_date,
               CASE
                 WHEN p.journal_ref IS NOT NULL AND TRIM(p.journal_ref) <> '' THEN 0
                 WHEN p.doi_checked_at IS NULL
                  AND p.published_date > DATE_SUB(
                      CURDATE(), INTERVAL {RECENT_PRIORITY_DAYS} DAY
                  ) THEN 1
                 WHEN p.doi_checked_at IS NULL THEN 2
                 ELSE 3
               END AS queue_priority
        FROM papers p
        WHERE {' AND '.join(conditions)}
        ORDER BY queue_priority,
                 CASE WHEN p.doi_checked_at IS NULL
                      THEN p.published_date END DESC,
                 p.doi_checked_at ASC,
                 p.id ASC
        LIMIT %s
    """, params)
    return cursor.fetchall()


def get_paper_authors(cursor, paper_id):
    """Return list of author name strings for a paper."""
    cursor.execute("""
        SELECT a.name FROM authors a
        JOIN paper_authors pa ON a.id = pa.author_id
        WHERE pa.paper_id = %s
        ORDER BY pa.author_order
    """, (paper_id,))
    return [row['name'] for row in cursor.fetchall()]


def get_rejected_dois(cursor, paper_id):
    """Return normalized DOI values previously rejected for one paper."""
    cursor.execute("""
        SELECT LOWER(TRIM(doi)) AS doi
        FROM doi_candidates
        WHERE paper_id = %s AND status = 'rejected'
    """, (paper_id,))
    return {row['doi'] for row in cursor.fetchall() if row.get('doi')}


def filter_rejected_doi_items(items, rejected_dois):
    """Keep Crossref results except DOI values rejected by an editor."""
    normalized_rejections = {
        doi.strip().lower() for doi in rejected_dois if doi
    }
    return [
        item for item in items
        if not item.get('DOI')
        or item['DOI'].strip().lower() not in normalized_rejections
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Find DOIs via Crossref')
    parser.add_argument('--batch', type=int, default=DEFAULT_BATCH_SIZE,
                        help='papers per run')
    parser.add_argument('--min-age', type=int, default=DEFAULT_MIN_AGE_DAYS,
                        help='skip papers published fewer than N days ago')
    parser.add_argument('--recheck', type=int, default=DEFAULT_RECHECK_DAYS,
                        help='skip papers checked within N days (default 180)')
    parser.add_argument('--from-date', type=str, default=None,
                        help='only papers published on or after this date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, default=None,
                        help='only papers published on or before this date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print matches without writing to DB')
    parser.add_argument('--auto-approve', type=float, default=None,
                        help='auto-promote DOIs with match score / 100 >= threshold')
    args = parser.parse_args(argv)
    if args.auto_approve is not None and not 0.60 <= args.auto_approve <= 1:
        parser.error('--auto-approve must be between 0.60 and 1')

    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cursor = conn.cursor()

    papers = get_papers_needing_doi(cursor, args.batch, args.min_age,
                                    recheck_days=args.recheck,
                                    from_date=args.from_date,
                                    to_date=args.to_date)
    print(f"Found {len(papers)} papers to query.")

    stats = {
        'queried': 0,
        'found': 0,
        'auto_approved': 0,
        'skipped': 0,
        'errors': 0,
    }

    for paper in papers:
        authors = get_paper_authors(cursor, paper['id'])
        first_last = _last_name(authors[0]) if authors else ''
        year = (paper['published_date'].year
                if hasattr(paper['published_date'], 'year')
                else int(str(paper['published_date'])[:4]))

        items = query_crossref(paper['title'], first_last)
        stats['queried'] += 1
        if items is None:
            stats['errors'] += 1
            print(
                f"  {paper['arxiv_id']}  Crossref request failed "
                "[left eligible for retry]"
            )
            time.sleep(REQUEST_DELAY)
            continue

        items = filter_rejected_doi_items(
            items,
            get_rejected_dois(cursor, paper['id']),
        )

        ranked = rank_crossref_matches(paper['title'], authors, year, items,
                                       paper_published_date=paper['published_date'])
        leader = ranked[0] if ranked else None
        best = (tuple(leader[key] for key in ('score', 'doi', 'title', 'authors', 'year'))
                if leader else None)

        if best and best[0] >= 0.60:
            conf, doi, cr_title, cr_authors_str, cr_year = best
            stats['found'] += 1
            flag = '' if leader['auto_eligible'] else ' [AMBIGUOUS MATCH OR AUTHOR CHANGES: REVIEW REQUIRED]'

            auto_approve = (args.auto_approve is not None and conf >= args.auto_approve
                            and leader['auto_eligible'])
            if auto_approve:
                # Recheck and lock current assignments before promoting a queued result.
                lock = '' if args.dry_run else ' FOR UPDATE'
                cursor.execute("SELECT doi, doi_status FROM papers WHERE id = %s" + lock,
                               (paper['id'],))
                current = cursor.fetchone()
                cursor.execute("""SELECT id FROM papers
                    WHERE id <> %s AND LOWER(TRIM(doi)) = %s LIMIT 1""" + lock,
                               (paper['id'], doi.strip().lower()))
                conflict = cursor.fetchone()
                cursor.execute("""SELECT status FROM doi_candidates
                    WHERE paper_id = %s AND LOWER(TRIM(doi)) = %s""" + lock,
                               (paper['id'], doi.strip().lower()))
                candidate_state = cursor.fetchone()
                if (not current or current['doi'] or current['doi_status'] == 'skipped'
                        or conflict or (candidate_state and candidate_state['status'] == 'rejected')):
                    auto_approve = False
                    flag = ' [DOI CONFLICT OR CHANGED PAPER: REVIEW REQUIRED]'

            if auto_approve:
                flag = ' [AUTO-APPROVED]'
                stats['auto_approved'] += 1
                if not args.dry_run:
                    cursor.execute("""
                        UPDATE papers SET doi=%s, doi_status='auto',
                               doi_confidence=%s WHERE id=%s
                    """, (doi, conf, paper['id']))
                    cursor.execute("""
                        INSERT INTO doi_candidates
                            (paper_id, doi, confidence, crossref_title,
                             crossref_authors, crossref_year, status, reviewed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'approved', NOW())
                        ON DUPLICATE KEY UPDATE
                            status='approved', reviewed_at=NOW()
                    """, (paper['id'], doi, conf, cr_title,
                          cr_authors_str, cr_year))
            elif not args.dry_run:
                cursor.execute("""
                    INSERT INTO doi_candidates
                        (paper_id, doi, confidence, crossref_title,
                         crossref_authors, crossref_year)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        confidence=VALUES(confidence),
                        crossref_title=VALUES(crossref_title),
                        crossref_authors=VALUES(crossref_authors),
                        crossref_year=VALUES(crossref_year)
                """, (paper['id'], doi, conf, cr_title,
                      cr_authors_str, cr_year))

            print(f"  {paper['arxiv_id']}  score={conf * 100:.1f}/100  doi={doi}{flag}")
        else:
            stats['skipped'] += 1
            if best:
                print(f"  {paper['arxiv_id']}  score={best[0] * 100:.1f}/100  (below threshold)")
            else:
                print(f"  {paper['arxiv_id']}  no Crossref results")

        # Mark paper as checked regardless of outcome
        if not args.dry_run:
            cursor.execute(
                "UPDATE papers SET doi_checked_at = NOW() WHERE id = %s",
                (paper['id'],))
            # Release assignment locks before the next network call or rate-limit wait.
            conn.commit()

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()

    cursor.close()
    conn.close()

    if not args.dry_run:
        _mark_index_cache_dirty_after_doi_changes(stats['auto_approved'])

    print(f"\nDone. Queried {stats['queried']}, found {stats['found']} "
          f"({stats['auto_approved']} auto-approved), "
          f"{stats['skipped']} below threshold, "
          f"{stats['errors']} request errors left eligible.")
    return 1 if stats['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
