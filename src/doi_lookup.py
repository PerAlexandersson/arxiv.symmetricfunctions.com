#!/usr/bin/env python3
"""
doi_lookup.py - Find DOIs for papers via the Crossref API.

Queries Crossref for papers that lack a DOI, scores matches by title/author
similarity, and inserts candidates into doi_candidates for admin review.

Usage:
    python3 doi_lookup.py                     # 50 papers (default)
    python3 doi_lookup.py --batch 100         # process 100 papers
    python3 doi_lookup.py --min-age 30        # only papers published >30 days ago
    python3 doi_lookup.py --dry-run           # print matches without writing
    python3 doi_lookup.py --auto-approve 0.95 # auto-promote high-confidence matches
"""

import argparse
from datetime import date
import sys
import time

import pymysql
import requests

from config import DB_CONFIG
from title_matching import (
    author_last_name as _last_name,
    normalize_title as _normalize,
    score_title_author_match,
)

CROSSREF_API = "https://api.crossref.org/works"
USER_AGENT = "arxiv-symmetricfunctions/1.0 (mailto:per.alexandersson@math.su.se)"
REQUEST_DELAY = 0.5  # seconds between Crossref requests


def _crossref_date_parts(cr_item, include_created=True):
    """Return (date_parts, field_name) from the first usable Crossref date."""
    fields = ['published-print', 'published-online', 'issued']
    if include_created:
        fields.append('created')

    for field in fields:
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
            return cleaned, field
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


def _crossref_predates_paper(cr_item, paper_year, paper_published_date=None):
    """Return True only when Crossref is definitely earlier than arXiv."""
    arxiv_year, arxiv_date = _paper_year_and_date(paper_year, paper_published_date)
    parts, _ = _crossref_date_parts(cr_item, include_created=False)
    if not parts or arxiv_year is None:
        return False

    cr_year = parts[0]
    if len(parts) >= 3 and arxiv_date is not None:
        try:
            cr_date = date(parts[0], parts[1], parts[2])
        except ValueError:
            return cr_year < arxiv_year
        return cr_date < arxiv_date

    return cr_year < arxiv_year


def score_match(paper_title, paper_authors, paper_year, cr_item,
                paper_published_date=None):
    """Compute a confidence score (0-1) for a Crossref result."""
    cr_title = ' '.join(cr_item.get('title', []))
    cr_authors = []
    for author in cr_item.get('author', []):
        full_name = (
            (author.get('family', '') + ', ' + author.get('given', '')).strip(', ')
            or author.get('name', '')
        )
        if full_name:
            cr_authors.append(full_name)

    # Crossref publication date must not be earlier than the first arXiv date.
    paper_year_val, paper_date = _paper_year_and_date(
        paper_year, paper_published_date)
    parts, _ = _crossref_date_parts(cr_item)
    cr_year = parts[0] if parts else None
    if _crossref_predates_paper(cr_item, paper_year_val, paper_date):
        return 0.0, cr_title, cr_year

    # Year match (weight 0.10)
    if cr_year is not None and paper_year_val is not None:
        diff = abs(int(cr_year) - int(paper_year_val))
        year_score = 1.0 if diff <= 1 else (0.5 if diff <= 2 else 0.0)
    else:
        year_score = 0.3  # unknown

    # DOI sanity (weight 0.10)
    has_journal = bool(cr_item.get('container-title'))
    doi_sanity = 1.0 if has_journal else 0.5

    text_author_score = score_title_author_match(
        paper_title, paper_authors, cr_title, cr_authors)
    confidence = (0.80 * text_author_score +
                  0.10 * year_score + 0.10 * doi_sanity)

    return round(confidence, 3), cr_title, cr_year


def query_crossref(title, first_author_last):
    """Query Crossref and return top results."""
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
        return []


def get_papers_needing_doi(cursor, batch_size, min_age_days,
                           recheck_days=180, from_date=None, to_date=None):
    """Find papers without DOI that haven't been checked recently.

    Skips papers with doi_checked_at within the last recheck_days,
    and papers with pending/approved candidates.
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
        SELECT p.id, p.arxiv_id, p.title, p.published_date
        FROM papers p
        WHERE {' AND '.join(conditions)}
        ORDER BY p.published_date DESC
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


def main():
    parser = argparse.ArgumentParser(description='Find DOIs via Crossref')
    parser.add_argument('--batch', type=int, default=50, help='papers per run')
    parser.add_argument('--min-age', type=int, default=30,
                        help='skip papers published fewer than N days ago')
    parser.add_argument('--recheck', type=int, default=180,
                        help='skip papers checked within N days (default 180)')
    parser.add_argument('--from-date', type=str, default=None,
                        help='only papers published on or after this date (YYYY-MM-DD)')
    parser.add_argument('--to-date', type=str, default=None,
                        help='only papers published on or before this date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='print matches without writing to DB')
    parser.add_argument('--auto-approve', type=float, default=None,
                        help='auto-promote DOIs with confidence >= threshold')
    args = parser.parse_args()

    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cursor = conn.cursor()

    papers = get_papers_needing_doi(cursor, args.batch, args.min_age,
                                    recheck_days=args.recheck,
                                    from_date=args.from_date,
                                    to_date=args.to_date)
    print(f"Found {len(papers)} papers to query.")

    stats = {'queried': 0, 'found': 0, 'auto_approved': 0, 'skipped': 0}

    for paper in papers:
        authors = get_paper_authors(cursor, paper['id'])
        first_last = _last_name(authors[0]) if authors else ''
        year = (paper['published_date'].year
                if hasattr(paper['published_date'], 'year')
                else int(str(paper['published_date'])[:4]))

        items = query_crossref(paper['title'], first_last)
        stats['queried'] += 1

        best = None
        for item in items:
            doi = item.get('DOI')
            if not doi:
                continue
            conf, cr_title, cr_year = score_match(
                paper['title'], authors, year, item,
                paper_published_date=paper['published_date'])
            cr_authors_str = '; '.join(
                (a.get('family', '') + ', ' + a.get('given', '')).strip(', ')
                for a in item.get('author', [])
            )
            if best is None or conf > best[0]:
                best = (conf, doi, cr_title, cr_authors_str, cr_year)

        if best and best[0] >= 0.60:
            conf, doi, cr_title, cr_authors_str, cr_year = best
            stats['found'] += 1
            flag = ''

            if args.auto_approve and conf >= args.auto_approve:
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

            print(f"  {paper['arxiv_id']}  conf={conf:.3f}  doi={doi}{flag}")
        else:
            stats['skipped'] += 1
            if best:
                print(f"  {paper['arxiv_id']}  conf={best[0]:.3f}  (below threshold)")
            else:
                print(f"  {paper['arxiv_id']}  no Crossref results")

        # Mark paper as checked regardless of outcome
        if not args.dry_run:
            cursor.execute(
                "UPDATE papers SET doi_checked_at = NOW() WHERE id = %s",
                (paper['id'],))

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()

    cursor.close()
    conn.close()

    print(f"\nDone. Queried {stats['queried']}, found {stats['found']} "
          f"({stats['auto_approved']} auto-approved), "
          f"{stats['skipped']} below threshold.")


if __name__ == '__main__':
    main()
