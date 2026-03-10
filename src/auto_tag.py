#!/usr/bin/env python3
"""
auto_tag.py - Tag papers with keywords from the keywords table.

Loads all active keywords, tokenizes paper titles/abstracts using the same
pipeline as extract_keywords.py, and writes matches to the paper_keywords table.

Usage:
    python3 auto_tag.py                    # last 180 days (6 months)
    python3 auto_tag.py --days 30          # last 30 days
    python3 auto_tag.py --since 2025-01-01 # since a specific date
    python3 auto_tag.py --all              # all papers (slow)
"""

import argparse
import sys
from datetime import date, timedelta

import pymysql
from config import DB_CONFIG

# Reuse tokenization from extract_keywords
from extract_keywords import tokenize


def load_keywords(cursor):
    """Load all active keywords and aliases as {phrase: keyword_id}."""
    cursor.execute("SELECT id, phrase FROM keywords WHERE active = 1")
    rows = cursor.fetchall()
    if rows and isinstance(rows[0], dict):
        phrase_to_id = {r['phrase']: r['id'] for r in rows}
    else:
        phrase_to_id = {phrase: kid for kid, phrase in rows}

    # Also load aliases so they match papers to the canonical keyword
    cursor.execute("""
        SELECT ka.alias, ka.keyword_id
        FROM keyword_aliases ka
        JOIN keywords k ON ka.keyword_id = k.id
        WHERE k.active = 1
    """)
    alias_rows = cursor.fetchall()
    if alias_rows and isinstance(alias_rows[0], dict):
        for r in alias_rows:
            phrase_to_id[r['alias']] = r['keyword_id']
    else:
        for alias, kid in alias_rows:
            phrase_to_id[alias] = kid

    print(f"  {len(phrase_to_id)} active keywords+aliases loaded.")
    return phrase_to_id


def extract_matching_keyword_ids(text, phrase_to_id, max_ngram):
    """Return set of keyword_ids matched in text."""
    tokens = tokenize(text)
    matched = set()
    n = len(tokens)
    for size in range(1, max_ngram + 1):
        for i in range(n - size + 1):
            phrase = ' '.join(tokens[i:i + size])
            if phrase in phrase_to_id:
                matched.add(phrase_to_id[phrase])
    return matched


def tag_papers(cursor, papers, phrase_to_id, max_ngram):
    """Tag a list of (id, title, abstract) rows. Returns count of tags inserted."""
    if not papers:
        return 0

    paper_ids = [p[0] for p in papers]

    # Clear existing tags for these papers so re-runs are clean
    placeholders = ','.join(['%s'] * len(paper_ids))
    cursor.execute(
        f"DELETE FROM paper_keywords WHERE paper_id IN ({placeholders})",
        paper_ids
    )

    rows_to_insert = []
    for paper_id, title, abstract in papers:
        text = (title or '') + ' ' + (abstract or '')
        matched_ids = extract_matching_keyword_ids(text, phrase_to_id, max_ngram)
        for kid in matched_ids:
            rows_to_insert.append((paper_id, kid))

    if rows_to_insert:
        cursor.executemany(
            "INSERT IGNORE INTO paper_keywords (paper_id, keyword_id) VALUES (%s, %s)",
            rows_to_insert
        )

    return len(rows_to_insert)


def main():
    parser = argparse.ArgumentParser(
        description='Tag papers with curated keywords.'
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--days', type=int, default=180,
                       help='Tag papers from last N days (default: 180)')
    group.add_argument('--since', metavar='YYYY-MM-DD',
                       help='Tag papers published on or after this date')
    group.add_argument('--all', action='store_true',
                       help='Tag all papers (slow for large DBs)')
    parser.add_argument('--max-ngram', type=int, default=4,
                        help='Max n-gram length to match (default: 4)')
    parser.add_argument('--batch', type=int, default=1000,
                        help='Papers per DB commit batch (default: 1000)')
    args = parser.parse_args()

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    print("Loading keywords...")
    phrase_to_id = load_keywords(cursor)
    if not phrase_to_id:
        print("No active keywords found. Add some via the admin UI first.")
        sys.exit(0)

    max_ngram = max(len(p.split()) for p in phrase_to_id)
    print(f"  Max keyword length: {max_ngram} words")

    # Build date filter
    if args.all:
        cursor.execute("SELECT id, title, abstract FROM papers ORDER BY published_date")
        date_desc = "all papers"
    elif args.since:
        since_date = args.since
        cursor.execute(
            "SELECT id, title, abstract FROM papers WHERE published_date >= %s ORDER BY published_date",
            (since_date,)
        )
        date_desc = f"papers since {since_date}"
    else:
        since_date = (date.today() - timedelta(days=args.days)).isoformat()
        cursor.execute(
            "SELECT id, title, abstract FROM papers WHERE published_date >= %s ORDER BY published_date",
            (since_date,)
        )
        date_desc = f"papers from last {args.days} days (since {since_date})"

    papers = cursor.fetchall()
    total = len(papers)
    print(f"Tagging {total:,} {date_desc}...")

    total_tags = 0
    for i in range(0, total, args.batch):
        batch = papers[i:i + args.batch]
        tags = tag_papers(cursor, batch, phrase_to_id, max_ngram)
        conn.commit()
        total_tags += tags
        print(f"  {min(i + args.batch, total):,} / {total:,} papers — {total_tags:,} tags so far")

    cursor.close()
    conn.close()
    print(f"Done. {total_tags:,} keyword tags applied to {total:,} papers.")


if __name__ == '__main__':
    main()
