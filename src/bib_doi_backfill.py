#!/usr/bin/env python3
"""
bib_doi_backfill.py - Extract arXiv IDs from a .bib file, find DOIs for
papers in the DB that lack them, and list IDs not in the DB.

Usage:
    python3 bib_doi_backfill.py /path/to/bibliography.bib
    python3 bib_doi_backfill.py /path/to/bibliography.bib --dry-run
    python3 bib_doi_backfill.py /path/to/bibliography.bib --auto-approve 0.90
"""

import argparse
import re
import sys
import time

import pymysql

from config import DB_CONFIG
from doi_lookup import (query_crossref, score_match, _last_name,
                        get_paper_authors, REQUEST_DELAY)


def extract_arxiv_ids(bib_path):
    """Extract arXiv IDs from Eprint fields in a .bib file."""
    ids = []
    with open(bib_path, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'\s*[Ee]print\s*=\s*\{([^}]+)\}', line)
            if m:
                arxiv_id = m.group(1).strip()
                # Strip version suffix for matching
                arxiv_id_base = re.sub(r'v\d+$', '', arxiv_id)
                ids.append(arxiv_id_base)
    return ids


def extract_bib_dois(bib_path):
    """Extract DOIs already present in the .bib file, keyed by arXiv ID.

    Returns {arxiv_id: doi} for entries that have both Eprint and DOI/doi.
    """
    entries = {}
    current_eprint = None
    current_doi = None

    with open(bib_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('@'):
                # Save previous entry
                if current_eprint and current_doi:
                    entries[current_eprint] = current_doi
                current_eprint = None
                current_doi = None

            m_ep = re.match(r'\s*[Ee]print\s*=\s*\{([^}]+)\}', line)
            if m_ep:
                current_eprint = re.sub(r'v\d+$', '', m_ep.group(1).strip())

            m_doi = re.match(r'\s*[Dd][Oo][Ii]\s*=\s*\{([^}]+)\}', line)
            if m_doi:
                current_doi = m_doi.group(1).strip()

    # Last entry
    if current_eprint and current_doi:
        entries[current_eprint] = current_doi
    return entries


def main():
    parser = argparse.ArgumentParser(
        description='Backfill DOIs from a .bib file into the local DB')
    parser.add_argument('bibfile', help='Path to .bib file')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--auto-approve', type=float, default=0.90,
                        help='Auto-approve Crossref matches above this threshold')
    args = parser.parse_args()

    arxiv_ids = extract_arxiv_ids(args.bibfile)
    bib_dois = extract_bib_dois(args.bibfile)
    print(f"Found {len(arxiv_ids)} arXiv IDs in bib file "
          f"({len(bib_dois)} already have DOIs in bib).")

    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cursor = conn.cursor()

    not_in_db = []
    already_has_doi = 0
    doi_from_bib = 0
    doi_from_crossref = 0
    crossref_pending = 0
    below_threshold = 0

    for arxiv_id in arxiv_ids:
        cursor.execute(
            """SELECT id, title, doi, doi_status, published_date
               FROM papers WHERE arxiv_id LIKE %s""",
            (f"{arxiv_id}%",))
        paper = cursor.fetchone()

        if not paper:
            not_in_db.append(arxiv_id)
            continue

        if paper['doi']:
            already_has_doi += 1
            continue

        if paper['doi_status'] == 'skipped':
            continue

        # First: check if the .bib file itself has a DOI for this entry
        if arxiv_id in bib_dois:
            doi = bib_dois[arxiv_id]
            print(f"  {arxiv_id}  doi={doi}  [from bib]")
            if not args.dry_run:
                cursor.execute("""
                    UPDATE papers SET doi=%s, doi_status='verified',
                           doi_confidence=1.000 WHERE id=%s
                """, (doi, paper['id']))
            doi_from_bib += 1
            continue

        # Otherwise: query Crossref
        authors = get_paper_authors(cursor, paper['id'])
        first_last = _last_name(authors[0]) if authors else ''
        year = (paper['published_date'].year
                if hasattr(paper.get('published_date'), 'year')
                else None)

        items = query_crossref(paper['title'], first_last)

        best = None
        for item in items:
            doi = item.get('DOI')
            if not doi:
                continue
            conf, cr_title, cr_year = score_match(
                paper['title'], authors, year, item,
                paper_published_date=paper.get('published_date'))
            cr_authors_str = '; '.join(
                (a.get('family', '') + ', ' + a.get('given', '')).strip(', ')
                for a in item.get('author', [])
            )
            if best is None or conf > best[0]:
                best = (conf, doi, cr_title, cr_authors_str, cr_year)

        if best and best[0] >= 0.60:
            conf, doi, cr_title, cr_authors_str, cr_year = best

            if conf >= args.auto_approve:
                print(f"  {arxiv_id}  conf={conf:.3f}  doi={doi}  [auto-approved]")
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
                doi_from_crossref += 1
            else:
                print(f"  {arxiv_id}  conf={conf:.3f}  doi={doi}  [pending review]")
                if not args.dry_run:
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
                crossref_pending += 1
        else:
            conf_str = f"conf={best[0]:.3f}" if best else "no results"
            print(f"  {arxiv_id}  {conf_str}  [below threshold]")
            below_threshold += 1

        # Mark paper as checked
        if not args.dry_run:
            cursor.execute(
                "UPDATE papers SET doi_checked_at = NOW() WHERE id = %s",
                (paper['id'],))

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()
    cursor.close()
    conn.close()

    print(f"\n{'=' * 50}")
    print(f"Total arXiv IDs:       {len(arxiv_ids)}")
    print(f"Already have DOI:      {already_has_doi}")
    print(f"DOI added from bib:    {doi_from_bib}")
    print(f"DOI from Crossref:     {doi_from_crossref} (auto-approved)")
    print(f"Crossref pending:      {crossref_pending}")
    print(f"Below threshold:       {below_threshold}")
    print(f"Not in DB:             {len(not_in_db)}")

    if not_in_db:
        print(f"\nArXiv IDs not in database ({len(not_in_db)}):")
        for aid in sorted(not_in_db):
            print(f"  {aid}")

    return not_in_db


if __name__ == '__main__':
    missing = main()
    # Write NOT_COMBINATORICS.md if there are missing IDs
    if missing:
        out_path = 'NOT_COMBINATORICS.md'
        with open(out_path, 'w') as f:
            f.write("# arXiv IDs from bibliography.bib not in the database\n\n")
            f.write("These papers are likely not in math.CO and were not fetched.\n\n")
            for aid in sorted(missing):
                f.write(f"- [{aid}](https://arxiv.org/abs/{aid})\n")
        print(f"\nWrote {len(missing)} IDs to {out_path}")
