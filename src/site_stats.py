"""
site_stats.py - Shared helpers for keeping homepage statistics current.

The fetch cron runs as a separate process from the Passenger web app, so any
state needed by the web process must be persisted in the database.
"""

import pymysql
from datetime import datetime

from config import DB_CONFIG

DEFAULT_CACHE_REBUILD_DELAY_SECONDS = 10 * 60


def _connect():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def refresh_site_stats():
    """
    Recompute persisted homepage statistics from the database.

    updated_at is always bumped so the web process can notice that an external
    fetch process ran, even when only existing paper metadata changed.
    """
    conn = _connect()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO site_stats (id, paper_count, author_count, latest_date)
            SELECT 1, COUNT(*), (SELECT COUNT(*) FROM authors), MAX(published_date)
            FROM papers
            ON DUPLICATE KEY UPDATE
                paper_count = VALUES(paper_count),
                author_count = VALUES(author_count),
                latest_date = VALUES(latest_date),
                cache_dirty_at = NULL,
                cache_rebuild_after = NULL,
                updated_at = CURRENT_TIMESTAMP
        """)
        conn.commit()
        cursor.execute("""
            SELECT paper_count, author_count, latest_date, updated_at,
                   cache_dirty_at, cache_rebuild_after
            FROM site_stats
            WHERE id = 1
        """)
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def get_site_stats():
    """Return persisted homepage statistics, creating them if necessary."""
    conn = _connect()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT paper_count, author_count, latest_date, updated_at,
                   cache_dirty_at, cache_rebuild_after
            FROM site_stats
            WHERE id = 1
        """)
        row = cursor.fetchone()
        if row:
            return row
    finally:
        cursor.close()
        conn.close()
    return refresh_site_stats()


def mark_index_cache_dirty(delay_seconds=DEFAULT_CACHE_REBUILD_DELAY_SECONDS):
    """
    Schedule a debounced rebuild of the anonymous homepage cache.

    Keep updated_at unchanged: updated_at is the cache version for completed
    rebuilds, while cache_rebuild_after is only a future rebuild deadline.
    """
    conn = _connect()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE site_stats
            SET cache_dirty_at = NOW(),
                cache_rebuild_after = DATE_ADD(NOW(), INTERVAL %s SECOND),
                updated_at = updated_at
            WHERE id = 1
        """, (delay_seconds,))
        conn.commit()
        cursor.execute("""
            SELECT paper_count, author_count, latest_date, updated_at,
                   cache_dirty_at, cache_rebuild_after
            FROM site_stats
            WHERE id = 1
        """)
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def index_cache_rebuild_due(stats, now=None):
    """Return True when persisted cache-dirty state has reached its deadline."""
    if not stats or not stats.get('cache_dirty_at'):
        return False
    rebuild_after = stats.get('cache_rebuild_after')
    if not rebuild_after:
        return True
    return (now or datetime.now()) >= rebuild_after
