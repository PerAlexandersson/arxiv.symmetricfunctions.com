#!/usr/bin/env python3
"""
fetch_arxiv.py - Fetch papers from arXiv and store in database

Usage:
    # Resume from the latest publication date already stored
    python fetch_arxiv.py --recent

    # Override the checkpoint with an explicit rolling window
    python fetch_arxiv.py --recent --days 2
    
    # Backfill papers from a date range
    python fetch_arxiv.py --backfill --start-date 2000-01-01 --end-date 2000-12-31
    
    # Fetch a specific arXiv ID
    python fetch_arxiv.py --arxiv-id 2401.12345
"""

import argparse
import arxiv
import pymysql
from calendar import monthrange
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import os
from pathlib import Path
import sys
from arxiv_oai import PoliteRequester, fetch_oai_papers, fetch_rss_ids
from config import DB_CONFIG, validate_config
from publication import normalize_doi
from site_stats import refresh_site_stats
from utils import slugify, split_arxiv_id_version

# Max results per query
MAX_RESULTS_RECENT = 500
MAX_RESULTS_BACKFILL = 5000

# Validate configuration on startup
validate_config()


class FetchAlreadyRunning(RuntimeError):
    """Raised when another cron or browser fetch owns the update lock."""


@contextmanager
def fetch_lock():
    """Prevent cron, CLI, and browser fetches from overlapping."""
    if os.environ.get('ARXIV_UPDATE_LOCK_HELD') == '1':
        yield
        return

    lock_dir = Path(
        os.environ.get('ARXIV_CRON_LOCK_DIR', Path.home() / '.cache/arxiv-cron')
    ).expanduser()
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / 'update.lock'
    with lock_path.open('a+') as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FetchAlreadyRunning('Another arXiv update is already running') from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def get_db_connection():
    """Create and return a database connection."""
    return pymysql.connect(**DB_CONFIG)


def insert_or_update_paper(cursor, paper):
    """
    Insert a paper into the database, or update if it already exists.
    Also handles authors and the paper-author relationship.
    
    Args:
        cursor: Database cursor
        paper: arxiv.Result object
    
    Returns:
        paper_id: The database ID of the inserted/updated paper
    """
    
    # Extract paper metadata
    arxiv_id = paper.entry_id.split('/abs/')[-1]  # Exact revision from URL
    arxiv_base_id, arxiv_version = split_arxiv_id_version(arxiv_id)
    if not arxiv_base_id:
        raise ValueError(f"Invalid arXiv identifier from entry URL: {arxiv_id!r}")
    title = paper.title
    abstract = paper.summary
    published_date = paper.published.date()
    updated_date = paper.updated.date() if paper.updated else None
    comment = paper.comment if hasattr(paper, 'comment') else None
    journal_ref = paper.journal_ref if hasattr(paper, 'journal_ref') else None
    doi = paper.doi if hasattr(paper, 'doi') else None
    primary_category = paper.primary_category
    
    # Check if paper already exists
    cursor.execute(
        """SELECT id, arxiv_id, arxiv_version, doi, doi_status,
                  publication_status
           FROM papers WHERE arxiv_base_id = %s""",
        (arxiv_base_id,),
    )
    result = cursor.fetchone()
    
    if result:
        # Update existing paper
        paper_id = result[0]
        existing_arxiv_id = result[1]
        existing_doi = result[3]
        existing_doi_status = result[4]
        existing_publication_status = result[5]
        if arxiv_version < result[2]:
            print(
                f"  Kept newer revision: {arxiv_base_id}v{result[2]} "
                f"(ignored requested v{arxiv_version})"
            )
            return paper_id
        # A manually verified publisher DOI outranks later arXiv metadata. arXiv
        # occasionally attaches an unrelated DOI, so never undo a correction.
        if doi:
            arxiv_doi = normalize_doi(doi)
            verified_doi = normalize_doi(existing_doi)
            if (
                existing_doi_status == 'verified'
                and verified_doi
                and verified_doi.casefold() != (arxiv_doi or '').casefold()
            ):
                update_doi = verified_doi
                update_doi_status = 'verified'
                update_publication_status = (
                    existing_publication_status or 'published'
                )
                print(
                    f"  Kept verified DOI {verified_doi}; ignored conflicting "
                    f"arXiv DOI {arxiv_doi or doi}"
                )
            else:
                cursor.execute("""
                    SELECT 1
                    FROM doi_candidates
                    WHERE paper_id = %s AND LOWER(doi) = LOWER(%s)
                      AND status = 'rejected'
                    LIMIT 1
                """, (paper_id, arxiv_doi or doi))
                rejected_arxiv_doi = cursor.fetchone() is not None
                if rejected_arxiv_doi:
                    if (verified_doi or '').casefold() == (
                        arxiv_doi or ''
                    ).casefold():
                        update_doi = None
                        update_doi_status = None
                    else:
                        update_doi = existing_doi
                        update_doi_status = existing_doi_status
                    update_publication_status = existing_publication_status
                    print(
                        f"  Ignored previously rejected arXiv DOI "
                        f"{arxiv_doi or doi}"
                    )
                else:
                    update_doi = arxiv_doi or doi
                    update_doi_status = 'arxiv'
                    update_publication_status = 'published'
        else:
            if existing_doi:
                update_doi, update_doi_status = existing_doi, existing_doi_status
                update_publication_status = (
                    existing_publication_status or 'published'
                )
            else:
                update_doi, update_doi_status = None, None
                update_publication_status = existing_publication_status
        if existing_arxiv_id != arxiv_id:
            cursor.execute("""
                INSERT IGNORE INTO user_lists (user_id, list_name, arxiv_id, added_at)
                SELECT user_id, list_name, %s, added_at
                FROM user_lists
                WHERE arxiv_id = %s
            """, (arxiv_id, existing_arxiv_id))
            cursor.execute(
                "DELETE FROM user_lists WHERE arxiv_id = %s",
                (existing_arxiv_id,),
            )
        cursor.execute("""
            UPDATE papers SET
                title = %s,
                abstract = %s,
                published_date = %s,
                updated_date = %s,
                comment = %s,
                journal_ref = %s,
                doi = %s,
                doi_status = %s,
                publication_status = %s,
                primary_category = %s,
                arxiv_id = %s,
                arxiv_version = %s
            WHERE id = %s
        """, (title, abstract, published_date, updated_date, comment,
              journal_ref, update_doi, update_doi_status,
              update_publication_status, primary_category,
              arxiv_id, arxiv_version, paper_id))
        
        # Clear existing author relationships
        cursor.execute("DELETE FROM paper_authors WHERE paper_id = %s", (paper_id,))
        print(f"  Updated: {arxiv_id} - {title[:60]}...")
    else:
        # Insert new paper
        doi_status = 'arxiv' if doi else None
        publication_status = 'published' if doi else None
        cursor.execute("""
            INSERT INTO papers
            (arxiv_id, arxiv_base_id, arxiv_version,
             title, abstract, published_date, updated_date,
             comment, journal_ref, doi, doi_status, publication_status, primary_category)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (arxiv_id, arxiv_base_id, arxiv_version,
              title, abstract, published_date, updated_date,
              comment, journal_ref, doi, doi_status, publication_status, primary_category))
        paper_id = cursor.lastrowid
        print(f"  Inserted: {arxiv_id} - {title[:60]}...")
    
    # Handle authors
    for order, author in enumerate(paper.authors, start=1):
        author_name = str(author)
        author_slug = slugify(author_name)

        # Insert author if not exists (or get existing ID)
        cursor.execute("""
            INSERT INTO authors (name, slug) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), slug=COALESCE(slug, VALUES(slug))
        """, (author_name, author_slug))
        author_id = cursor.lastrowid
        
        # Link paper to author (ignore if duplicate)
        cursor.execute("""
            INSERT IGNORE INTO paper_authors (paper_id, author_id, author_order)
            VALUES (%s, %s, %s)
        """, (paper_id, author_id, order))

    # Store all arXiv subject categories (primary + secondary cross-listings)
    cursor.execute("DELETE FROM paper_categories WHERE paper_id = %s", (paper_id,))
    for cat in paper.categories:
        cursor.execute(
            "INSERT IGNORE INTO paper_categories (paper_id, category) VALUES (%s, %s)",
            (paper_id, cat)
        )

    return paper_id


def _auto_tag_papers(conn, cursor, papers):
    """Tag a list of (paper_id, title, abstract) using active keywords from the DB."""
    from auto_tag import load_keywords, tag_papers
    phrase_to_id = load_keywords(cursor)
    if not phrase_to_id:
        print("  (No active keywords — skipping auto-tagging)")
        return
    max_ngram = max(len(p.split()) for p in phrase_to_id)
    n_tags = tag_papers(cursor, papers, phrase_to_id, max_ngram)
    conn.commit()
    print(f"  Auto-tagged: {n_tags} keyword tags across {len(papers)} papers.")


def _store_papers(papers):
    """Store an iterable of arXiv-compatible paper objects transactionally."""
    conn = get_db_connection()
    cursor = conn.cursor()
    count = 0
    errors = 0
    processed_papers = []
    try:
        for paper in papers:
            cursor.execute("SAVEPOINT fetch_one_paper")
            try:
                paper_id = insert_or_update_paper(cursor, paper)
                cursor.execute("RELEASE SAVEPOINT fetch_one_paper")
                processed_papers.append((paper_id, paper.title, paper.summary))
                count += 1
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT fetch_one_paper")
                cursor.execute("RELEASE SAVEPOINT fetch_one_paper")
                errors += 1
                arxiv_id = (
                    paper.entry_id.split('/abs/')[-1]
                    if hasattr(paper, 'entry_id') else 'unknown'
                )
                print(f"  Error processing {arxiv_id}: {e}")

        conn.commit()
        print(f"\nSuccessfully processed {count} papers.")
        if errors > 0:
            print(f"Encountered {errors} errors (skipped those papers).")
        if processed_papers:
            _auto_tag_papers(conn, cursor, processed_papers)
        return count, errors
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _fetch_papers(query, max_results, client=None):
    """
    Fetch papers from arXiv matching a query and store in database.

    Args:
        query: arXiv search query string
        max_results: Maximum number of results to fetch
    """
    print(f"Query: {query}")

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    client = client or arxiv.Client(delay_seconds=3.5)
    try:
        return _store_papers(client.results(search))
    except Exception as e:
        print(f"Fatal error: {e}")
        raise


def _refresh_site_stats_after_fetch():
    """Refresh persisted homepage counters after a successful fetch."""
    try:
        stats = refresh_site_stats()
        print(
            "  Site stats refreshed: "
            f"{stats['paper_count']} papers, latest {stats['latest_date']}."
        )
    except Exception as e:
        print(f"  WARNING: Could not refresh site stats: {e}", file=sys.stderr)


def _latest_published_date():
    """Return the newest populated publication date, used as an inclusive checkpoint."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT MAX(published_date) FROM papers")
        row = cursor.fetchone()
        value = row[0] if row else None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value
    finally:
        cursor.close()
        conn.close()


def _report_rss_coverage(requester):
    """Use today's RSS announcement as an independent completeness signal."""
    try:
        rss_ids = fetch_rss_ids(requester)
    except Exception as exc:
        print(f"  WARNING: Could not check the math.CO RSS feed: {exc}")
        return
    if not rss_ids:
        print("  RSS coverage: current math.CO feed is empty.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        placeholders = ','.join(['%s'] * len(rss_ids))
        cursor.execute(
            f"SELECT arxiv_base_id FROM papers WHERE arxiv_base_id IN ({placeholders})",
            tuple(sorted(rss_ids)),
        )
        stored = {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

    missing = sorted(rss_ids - stored)
    if missing:
        preview = ', '.join(missing[:10])
        suffix = ' ...' if len(missing) > 10 else ''
        print(
            f"  WARNING: RSS coverage found {len(missing)} missing of "
            f"{len(rss_ids)} announced papers: {preview}{suffix}"
        )
    else:
        print(f"  RSS coverage: all {len(rss_ids)} announced papers are stored.")


def fetch_recent_papers(days=None, retry_delays=None):
    """Resume recent ingestion from the newest stored publication date."""
    end_date = datetime.now().date()
    if days is None:
        start_date = _latest_published_date() or (end_date - timedelta(days=3))
        print(
            f"Fetching arXiv changes from database checkpoint {start_date} "
            f"through {end_date} (inclusive)..."
        )
    else:
        if days < 1:
            raise ValueError('days must be positive')
        start_date = end_date - timedelta(days=days)
        print(f"Fetching arXiv changes from explicit {days}-day window...")

    requester = PoliteRequester(retry_delays=retry_delays)
    try:
        papers = fetch_oai_papers(start_date, end_date, requester=requester)
        print(f"OAI-PMH returned {len(papers)} changed math.CO records.")
        _store_papers(papers)
    except Exception as oai_error:
        print(f"WARNING: OAI-PMH fetch failed: {oai_error}")
        print("Falling back to the legacy arXiv query API...")
        date_range = (
            f"[{start_date.strftime('%Y%m%d')}0000 TO "
            f"{end_date.strftime('%Y%m%d')}2359]"
        )
        client = arxiv.Client(delay_seconds=3.5, num_retries=3)
        _fetch_papers(
            f"cat:math.CO AND submittedDate:{date_range}",
            MAX_RESULTS_RECENT,
            client=client,
        )
        print("Checking for updates to older papers...")
        _fetch_papers(
            f"cat:math.CO AND lastUpdatedDate:{date_range}",
            MAX_RESULTS_RECENT,
            client=client,
        )

    _report_rss_coverage(requester)
    _refresh_site_stats_after_fetch()


def fetch_date_range(start_date_str, end_date_str):
    """Fetch papers from a specific date range (YYYY-MM-DD format)."""
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    print(f"Fetching papers from {start_date_str} to {end_date_str}...")
    query = (
        f"cat:math.CO AND submittedDate:[{start_date.strftime('%Y%m%d')}0000 "
        f"TO {end_date.strftime('%Y%m%d')}2359]"
    )
    _fetch_papers(query, MAX_RESULTS_BACKFILL)
    _refresh_site_stats_after_fetch()


def fetch_by_arxiv_id(arxiv_id):
    """
    Fetch a specific paper by arXiv ID.

    Args:
        arxiv_id: The arXiv ID (e.g., "2401.12345")
    """
    print(f"Fetching paper: {arxiv_id}...")

    search = arxiv.Search(id_list=[arxiv_id])
    client = arxiv.Client()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        paper = next(client.results(search))
        paper_id = insert_or_update_paper(cursor, paper)
        conn.commit()
        print(f"Successfully processed {arxiv_id}")
        _auto_tag_papers(conn, cursor, [(paper_id, paper.title, paper.summary)])
        _refresh_site_stats_after_fetch()
    except StopIteration:
        print(f"Paper {arxiv_id} not found on arXiv")
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def fill_gap():
    """
    Find the first month (from 1991-01 onward) with no papers and backfill it.
    Scans forward from arXiv founding to the present, finds the earliest
    gap, and fills it. Run repeatedly to gradually fill all months.
    """
    ARXIV_START_YEAR = 1991
    ARXIV_START_MONTH = 1

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all months that have at least one paper
    cursor.execute("""
        SELECT DISTINCT YEAR(published_date) as y, MONTH(published_date) as m
        FROM papers
        ORDER BY y, m
    """)
    filled_months = {(row[0], row[1]) for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    now = datetime.now()
    current_year, current_month = now.year, now.month

    # Scan backward from current month to find most recent unfilled month
    y, m = current_year, current_month
    target = None
    while (y, m) >= (ARXIV_START_YEAR, ARXIV_START_MONTH):
        if (y, m) not in filled_months:
            target = (y, m)
            break
        m -= 1
        if m < 1:
            m = 12
            y -= 1

    if target is None:
        print("All months from 1991-01 to present are filled!")
        print("Nothing to do.")
        return

    target_year, target_month = target
    _, last_day = monthrange(target_year, target_month)
    start_date = f"{target_year}-{target_month:02d}-01"
    end_date = f"{target_year}-{target_month:02d}-{last_day:02d}"

    print(f"Filling gap: {start_date} to {end_date}")
    fetch_date_range(start_date, end_date)


def main():
    parser = argparse.ArgumentParser(description='Fetch arXiv papers and store in database')

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--recent', action='store_true',
                           help='Fetch recent papers')
    mode_group.add_argument('--backfill', action='store_true',
                           help='Backfill papers from a date range')
    mode_group.add_argument('--arxiv-id', type=str,
                           help='Fetch a specific paper by arXiv ID')
    mode_group.add_argument('--fill-gap', action='store_true',
                           help='Auto-fill the month before the earliest data')

    # Options for different modes
    parser.add_argument(
        '--days',
        type=int,
        default=None,
        help=(
            'Override the database checkpoint with a rolling lookback window '
            '(for --recent mode)'
        ),
    )
    parser.add_argument('--start-date', type=str,
                       help='Start date in YYYY-MM-DD format (for --backfill mode)')
    parser.add_argument('--end-date', type=str,
                       help='End date in YYYY-MM-DD format (for --backfill mode)')

    args = parser.parse_args()

    try:
        with fetch_lock():
            if args.recent:
                fetch_recent_papers(args.days)
            elif args.backfill:
                if not args.start_date or not args.end_date:
                    print("Error: --backfill requires --start-date and --end-date")
                    sys.exit(1)
                fetch_date_range(args.start_date, args.end_date)
            elif args.arxiv_id:
                fetch_by_arxiv_id(args.arxiv_id)
            elif args.fill_gap:
                fill_gap()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
