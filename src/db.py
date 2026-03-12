"""
db.py - Shared database helpers for all Flask blueprints.

All modules should import get_db_connection from here instead of duplicating
the per-request g.db caching pattern.  app.py registers close_db_connection
as a teardown handler so the connection is closed once at end-of-request.
"""

import pymysql
from flask import g
from config import DB_CONFIG


def get_db_connection():
    """Return a per-request DB connection (cached on g, closed on teardown)."""
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    return g.db


def close_db_connection(e=None):
    """Teardown: close the per-request DB connection if one was opened."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


# ── Paper data helpers ─────────────────────────────────────────────────────────

def get_paper_authors(cursor, paper_id):
    """Return an ordered list of author names for a single paper."""
    cursor.execute("""
        SELECT a.name
        FROM authors a
        JOIN paper_authors pa ON a.id = pa.author_id
        WHERE pa.paper_id = %s
        ORDER BY pa.author_order
    """, (paper_id,))
    return [row['name'] for row in cursor.fetchall()]


def attach_authors(cursor, papers):
    """Attach an 'authors' list to each paper dict (single batched query)."""
    if not papers:
        return
    paper_ids = [p['id'] for p in papers]
    placeholders = ','.join(['%s'] * len(paper_ids))
    cursor.execute(f"""
        SELECT pa.paper_id, a.name
        FROM authors a
        JOIN paper_authors pa ON a.id = pa.author_id
        WHERE pa.paper_id IN ({placeholders})
        ORDER BY pa.paper_id, pa.author_order
    """, paper_ids)
    by_paper = {}
    for row in cursor.fetchall():
        by_paper.setdefault(row['paper_id'], []).append(row['name'])
    for paper in papers:
        paper['authors'] = by_paper.get(paper['id'], [])


def attach_keywords(cursor, papers):
    """Attach a 'keywords' list to each paper dict (single batched query)."""
    if not papers:
        return
    paper_ids = [p['id'] for p in papers]
    placeholders = ','.join(['%s'] * len(paper_ids))
    cursor.execute(f"""
        SELECT pk.paper_id, k.phrase, k.url
        FROM paper_keywords pk
        JOIN keywords k ON pk.keyword_id = k.id
        WHERE pk.paper_id IN ({placeholders})
        ORDER BY pk.paper_id, k.score DESC, k.phrase ASC
    """, paper_ids)
    by_paper = {}
    for row in cursor.fetchall():
        by_paper.setdefault(row['paper_id'], []).append(
            {'phrase': row['phrase'], 'url': row['url']}
        )
    for paper in papers:
        paper['keywords'] = by_paper.get(paper['id'], [])
