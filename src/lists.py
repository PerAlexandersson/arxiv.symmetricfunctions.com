"""
lists.py - User saved-paper lists ("My Lists")

Routes (pages):
    GET  /lists                          → overview of all user categories
    GET  /lists/<int:cat_id>             → papers in a specific category
    GET  /my-papers                      → redirect to /author/<slug> for the logged-in user

Routes (API — JSON, CSRF-protected POST):
    POST /api/lists/star/<arxiv_id>      → toggle Starred
    POST /api/lists/save                 → add paper to a category
    POST /api/lists/remove               → remove paper from a category
    GET  /api/lists/categories           → list user's categories as JSON
    GET  /api/lists/<id>/bibtex          → all BibTeX entries for a list (plain text)
    POST /api/lists/categories/new       → create a new category
    POST /api/lists/categories/<id>/rename
    POST /api/lists/categories/<id>/delete
"""

import pymysql
import logging
from flask import (Blueprint, render_template, request, jsonify,
                   redirect, url_for, session, abort, g)
from config import DB_CONFIG
from utils import arxiv2bib, slugify

logger = logging.getLogger(__name__)
lists_bp = Blueprint('lists', __name__)

STARRED_NAME = 'Starred'


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_db():
    """Return a per-request DB connection (shared with app.py via g)."""
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    return g.db


def _require_user():
    """Return user_id from session or abort 401."""
    user_id = session.get('user_id')
    if not user_id:
        abort(401)
    return user_id


def _ensure_starred(user_id):
    """Return the id of the Starred category, creating it if needed."""
    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM user_categories WHERE user_id=%s AND is_starred=1",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return row['id']
        cursor.execute(
            "INSERT INTO user_categories (user_id, name, is_starred) VALUES (%s, %s, 1)",
            (user_id, STARRED_NAME)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()


def _get_user_categories(user_id):
    """Return all categories for a user, Starred first, with paper counts."""
    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT uc.id, uc.name, uc.is_starred,
                      COUNT(ul.id) AS paper_count
               FROM user_categories uc
               LEFT JOIN user_lists ul
                      ON ul.user_id = uc.user_id AND ul.list_name = uc.name
               WHERE uc.user_id = %s
               GROUP BY uc.id, uc.name, uc.is_starred, uc.created_at
               ORDER BY uc.is_starred DESC, uc.created_at ASC""",
            (user_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()


def _get_papers_in_category(user_id, cat_id):
    """Return (category_row, [paper_rows]) or (None, None) if not found."""
    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, name, is_starred FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        cat = cursor.fetchone()
        if not cat:
            return None, None

        cursor.execute(
            """SELECT p.arxiv_id, p.title, p.abstract, p.published_date,
                      p.journal_ref, p.doi, ul.added_at AS saved_at,
                      GROUP_CONCAT(a.name ORDER BY pa.author_order SEPARATOR '\t') AS authors_str
               FROM user_lists ul
               JOIN papers p ON p.arxiv_id = ul.arxiv_id
               LEFT JOIN paper_authors pa ON pa.paper_id = p.id
               LEFT JOIN authors a ON a.id = pa.author_id
               WHERE ul.user_id = %s AND ul.list_name = %s
               GROUP BY p.arxiv_id, p.title, p.abstract, p.published_date,
                        p.journal_ref, p.doi, ul.added_at
               ORDER BY ul.added_at DESC""",
            (user_id, cat['name'])
        )
        rows = cursor.fetchall()

        # Fetch keywords for these papers in one query
        if rows:
            arxiv_ids = [r['arxiv_id'] for r in rows]
            fmt = ','.join(['%s'] * len(arxiv_ids))
            cursor.execute(
                f"""SELECT p.arxiv_id, k.phrase
                    FROM paper_keywords pk
                    JOIN papers p ON p.id = pk.paper_id
                    JOIN keywords k ON k.id = pk.keyword_id
                    WHERE p.arxiv_id IN ({fmt}) AND k.active = 1
                    ORDER BY k.score DESC""",
                arxiv_ids
            )
            kw_map = {}
            for kw in cursor.fetchall():
                kw_map.setdefault(kw['arxiv_id'], []).append({'phrase': kw['phrase']})

            for r in rows:
                r['authors'] = [a for a in (r['authors_str'] or '').split('\t') if a]
                r['keywords'] = kw_map.get(r['arxiv_id'], [])

        return cat, rows
    finally:
        cursor.close()


# ── Page routes ────────────────────────────────────────────────────────────────

@lists_bp.route('/lists')
def my_lists():
    user_id = session.get('user_id')
    if not user_id:
        session['login_next'] = url_for('lists.my_lists')
        return redirect(url_for('auth.login'))
    categories = _get_user_categories(user_id)

    conn = _get_db()
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
    cursor.close()

    return render_template('lists.html', categories=categories,
                           watched_keywords=watched_keywords,
                           watched_authors=watched_authors)


@lists_bp.route('/my-papers')
def my_papers():
    user_id = session.get('user_id')
    if not user_id:
        session['login_next'] = url_for('lists.my_papers')
        return redirect(url_for('auth.login'))
    name = session.get('user_name', '')
    if not name:
        abort(404)
    return redirect(url_for('author_papers', author_slug=slugify(name)))


@lists_bp.route('/lists/<int:cat_id>')
def list_detail(cat_id):
    user_id = session.get('user_id')
    if not user_id:
        session['login_next'] = request.url
        return redirect(url_for('auth.login'))
    cat, papers = _get_papers_in_category(user_id, cat_id)
    if cat is None:
        abort(404)
    categories = _get_user_categories(user_id)
    return render_template('list_detail.html',
                           category=cat,
                           cat_id=cat_id,
                           papers=papers,
                           categories=categories)


# ── API routes ─────────────────────────────────────────────────────────────────

@lists_bp.route('/api/lists/star/<arxiv_id>', methods=['POST'])
def toggle_star(arxiv_id):
    user_id = _require_user()
    starred_cat_id = _ensure_starred(user_id)

    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name FROM user_categories WHERE id=%s",
            (starred_cat_id,)
        )
        cat_name = cursor.fetchone()['name']

        cursor.execute(
            "SELECT id FROM user_lists WHERE user_id=%s AND list_name=%s AND arxiv_id=%s",
            (user_id, cat_name, arxiv_id)
        )
        if cursor.fetchone():
            cursor.execute(
                "DELETE FROM user_lists WHERE user_id=%s AND list_name=%s AND arxiv_id=%s",
                (user_id, cat_name, arxiv_id)
            )
            conn.commit()
            return jsonify({'starred': False})
        else:
            cursor.execute(
                "INSERT IGNORE INTO user_lists (user_id, list_name, arxiv_id) VALUES (%s,%s,%s)",
                (user_id, cat_name, arxiv_id)
            )
            conn.commit()
            return jsonify({'starred': True})
    finally:
        cursor.close()


@lists_bp.route('/api/lists/save', methods=['POST'])
def save_paper():
    user_id = _require_user()
    arxiv_id  = request.form.get('arxiv_id',    '').strip()
    cat_id    = request.form.get('category_id', type=int)
    new_name  = request.form.get('new_name',    '').strip()[:100]

    if not arxiv_id:
        return jsonify({'error': 'arxiv_id required'}), 400

    conn = _get_db()
    cursor = conn.cursor()
    try:
        if new_name:
            cursor.execute(
                "INSERT INTO user_categories (user_id, name) VALUES (%s, %s)",
                (user_id, new_name)
            )
            conn.commit()
            cat_name = new_name
            cat_id = cursor.lastrowid
        elif cat_id:
            cursor.execute(
                "SELECT name FROM user_categories WHERE id=%s AND user_id=%s",
                (cat_id, user_id)
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Category not found'}), 404
            cat_name = row['name']
        else:
            return jsonify({'error': 'category_id or new_name required'}), 400

        cursor.execute(
            "INSERT IGNORE INTO user_lists (user_id, list_name, arxiv_id) VALUES (%s,%s,%s)",
            (user_id, cat_name, arxiv_id)
        )
        conn.commit()
        return jsonify({'saved': True, 'category_id': cat_id, 'category_name': cat_name})
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'List name already exists'}), 409
    finally:
        cursor.close()


@lists_bp.route('/api/lists/remove', methods=['POST'])
def remove_paper():
    user_id  = _require_user()
    arxiv_id = request.form.get('arxiv_id',    '').strip()
    cat_id   = request.form.get('category_id', type=int)

    if not arxiv_id or not cat_id:
        return jsonify({'error': 'arxiv_id and category_id required'}), 400

    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Category not found'}), 404

        cursor.execute(
            "DELETE FROM user_lists WHERE user_id=%s AND list_name=%s AND arxiv_id=%s",
            (user_id, row['name'], arxiv_id)
        )
        conn.commit()
        return jsonify({'removed': True})
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories')
def get_categories():
    user_id = _require_user()
    cats = _get_user_categories(user_id)
    return jsonify([dict(c) for c in cats])


@lists_bp.route('/api/lists/categories/new', methods=['POST'])
def new_category():
    user_id = _require_user()
    name = request.form.get('name', '').strip()[:100]
    if not name:
        return jsonify({'error': 'name required'}), 400

    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO user_categories (user_id, name) VALUES (%s, %s)",
            (user_id, name)
        )
        conn.commit()
        return jsonify({'id': cursor.lastrowid, 'name': name,
                        'is_starred': 0, 'paper_count': 0})
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'A list with that name already exists'}), 409
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories/<int:cat_id>/rename', methods=['POST'])
def rename_category(cat_id):
    user_id  = _require_user()
    new_name = request.form.get('name', '').strip()[:100]
    if not new_name:
        return jsonify({'error': 'name required'}), 400

    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Category not found'}), 404

        old_name = row['name']
        cursor.execute(
            "UPDATE user_lists SET list_name=%s WHERE user_id=%s AND list_name=%s",
            (new_name, user_id, old_name)
        )
        cursor.execute(
            "UPDATE user_categories SET name=%s WHERE id=%s AND user_id=%s",
            (new_name, cat_id, user_id)
        )
        conn.commit()
        return jsonify({'renamed': True, 'name': new_name})
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'A list with that name already exists'}), 409
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories/<int:cat_id>/delete', methods=['POST'])
def delete_category(cat_id):
    user_id = _require_user()

    conn = _get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name, is_starred FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Category not found'}), 404
        if row['is_starred']:
            return jsonify({'error': 'Cannot delete the Starred list'}), 403

        cursor.execute(
            "DELETE FROM user_lists WHERE user_id=%s AND list_name=%s",
            (user_id, row['name'])
        )
        cursor.execute(
            "DELETE FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        conn.commit()
        return jsonify({'deleted': True})
    finally:
        cursor.close()


@lists_bp.route('/api/lists/<int:cat_id>/bibtex')
def list_bibtex(cat_id):
    """Return all BibTeX entries for a list as plain text."""
    user_id = _require_user()
    cat, papers = _get_papers_in_category(user_id, cat_id)
    if cat is None:
        abort(404)
    entries = [arxiv2bib(p) for p in papers]
    text = '\n\n'.join(entries)
    return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
