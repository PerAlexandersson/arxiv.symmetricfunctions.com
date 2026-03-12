"""
watch.py - Watched keywords and authors ("My Feed")

Routes (pages):
    GET  /my-feed                        → personalised feed of recent papers

Routes (API — JSON, CSRF-protected POST):
    POST /api/watch/keyword/<int:kid>    → toggle watching a keyword
    POST /api/watch/author/<int:aid>     → toggle watching an author
"""

import logging
from flask import (Blueprint, render_template, request, jsonify,
                   redirect, url_for, session, abort)
from db import get_db_connection, attach_authors, attach_keywords

logger = logging.getLogger(__name__)
watch_bp = Blueprint('watch', __name__)


def _require_user():
    """Return user_id from session or abort 401."""
    user_id = session.get('user_id')
    if not user_id:
        abort(401)
    return user_id


# ── API routes ─────────────────────────────────────────────────────────────────

@watch_bp.route('/api/watch/keyword/<int:kid>', methods=['POST'])
def toggle_watch_keyword(kid):
    user_id = _require_user()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM keywords WHERE id=%s AND active=1", (kid,))
        if not cursor.fetchone():
            return jsonify({'error': 'Keyword not found'}), 404

        cursor.execute(
            "SELECT 1 FROM user_watched_keywords WHERE user_id=%s AND keyword_id=%s",
            (user_id, kid)
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM user_watched_keywords WHERE user_id=%s AND keyword_id=%s",
                (user_id, kid)
            )
            conn.commit()
            return jsonify({'watching': False})
        else:
            cursor.execute(
                "INSERT IGNORE INTO user_watched_keywords (user_id, keyword_id) VALUES (%s, %s)",
                (user_id, kid)
            )
            conn.commit()
            return jsonify({'watching': True})
    finally:
        cursor.close()


@watch_bp.route('/api/watch/author/<int:aid>', methods=['POST'])
def toggle_watch_author(aid):
    user_id = _require_user()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM authors WHERE id=%s", (aid,))
        if not cursor.fetchone():
            return jsonify({'error': 'Author not found'}), 404

        cursor.execute(
            "SELECT 1 FROM user_watched_authors WHERE user_id=%s AND author_id=%s",
            (user_id, aid)
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM user_watched_authors WHERE user_id=%s AND author_id=%s",
                (user_id, aid)
            )
            conn.commit()
            return jsonify({'watching': False})
        else:
            cursor.execute(
                "INSERT IGNORE INTO user_watched_authors (user_id, author_id) VALUES (%s, %s)",
                (user_id, aid)
            )
            conn.commit()
            return jsonify({'watching': True})
    finally:
        cursor.close()


# ── Page routes ────────────────────────────────────────────────────────────────

@watch_bp.route('/my-feed')
def my_feed():
    user_id = session.get('user_id')
    if not user_id:
        session['login_next'] = url_for('watch.my_feed')
        return redirect(url_for('auth.login'))

    page = max(1, request.args.get('page', 1, type=int))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """SELECT k.id, k.phrase FROM user_watched_keywords uwk
           JOIN keywords k ON k.id = uwk.keyword_id
           WHERE uwk.user_id = %s ORDER BY k.phrase""",
        (user_id,)
    )
    watched_keywords = cursor.fetchall()

    cursor.execute(
        """SELECT a.id, a.name, a.slug FROM user_watched_authors uwa
           JOIN authors a ON a.id = uwa.author_id
           WHERE uwa.user_id = %s ORDER BY a.name""",
        (user_id,)
    )
    watched_authors = cursor.fetchall()

    papers = []
    has_more = False

    if watched_keywords or watched_authors:
        feed_subquery = """
            SELECT pk.paper_id FROM paper_keywords pk
            JOIN user_watched_keywords uwk ON pk.keyword_id = uwk.keyword_id
            WHERE uwk.user_id = %s
            UNION
            SELECT pa.paper_id FROM paper_authors pa
            JOIN user_watched_authors uwa ON pa.author_id = uwa.author_id
            WHERE uwa.user_id = %s
        """
        cursor.execute(f"""
            SELECT DISTINCT p.id, p.arxiv_id, p.title, p.abstract,
                   p.published_date, p.updated_date, p.journal_ref, p.doi,
                   p.comment, p.primary_category
            FROM papers p
            WHERE p.id IN ({feed_subquery})
            ORDER BY p.published_date DESC, p.id DESC
            LIMIT %s OFFSET %s
        """, (user_id, user_id, per_page + 1, offset))
        rows = cursor.fetchall()
        has_more = len(rows) > per_page
        papers = list(rows[:per_page])

        if papers:
            attach_authors(cursor, papers)
            attach_keywords(cursor, papers)

    cursor.close()

    return render_template('feed.html',
                           papers=papers,
                           watched_keywords=watched_keywords,
                           watched_authors=watched_authors,
                           page=page,
                           has_more=has_more)
