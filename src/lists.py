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
                   redirect, url_for, session, abort)
from utils import arxiv2bib, slugify
from db import attach_authors, attach_keywords, require_user
from db import get_db_connection

logger = logging.getLogger(__name__)
lists_bp = Blueprint('lists', __name__)

STARRED_NAME = 'Starred'


# ── Helpers ────────────────────────────────────────────────────────────────────


_require_user = require_user  # back-compat alias


def _ensure_starred(cursor, user_id):
    """Return ``(id, name)`` for the Starred category, creating it atomically."""
    cursor.execute(
        "SELECT id, name FROM user_categories WHERE user_id=%s AND is_starred=1 LIMIT 1",
        (user_id,)
    )
    row = cursor.fetchone()
    if row:
        return row['id'], row['name']

    # A user may have created a custom list named Starred before starring a
    # paper. Promote that row instead of failing the unique (user_id, name) key.
    cursor.execute(
        """INSERT INTO user_categories (user_id, name, is_starred)
           VALUES (%s, %s, 1)
           ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), is_starred=1""",
        (user_id, STARRED_NAME)
    )
    return cursor.lastrowid, STARRED_NAME


def _get_user_categories(user_id, include_counts=True, arxiv_id=None):
    """Return user categories and optional membership state for one paper."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if include_counts:
            cursor.execute(
                """SELECT uc.id, uc.name, uc.is_starred,
                          COUNT(ul.id) AS paper_count,
                          EXISTS(
                              SELECT 1
                              FROM user_lists selected
                              JOIN papers selected_paper
                                ON selected_paper.id = selected.paper_id
                              WHERE selected.category_id = uc.id
                                AND selected_paper.arxiv_id = %s
                          ) AS contains_paper
                   FROM user_categories uc
                   LEFT JOIN user_lists ul
                          ON ul.category_id = uc.id
                   WHERE uc.user_id = %s
                   GROUP BY uc.id, uc.name, uc.is_starred, uc.created_at
                   ORDER BY uc.is_starred DESC, uc.created_at ASC""",
                (arxiv_id, user_id)
            )
        else:
            cursor.execute(
                """SELECT uc.id, uc.name, uc.is_starred,
                          CASE WHEN selected.id IS NULL THEN 0 ELSE 1 END
                               AS contains_paper
                   FROM user_categories uc
                   LEFT JOIN papers selected_paper
                          ON selected_paper.arxiv_id = %s
                   LEFT JOIN user_lists selected
                          ON selected.category_id = uc.id
                         AND selected.paper_id = selected_paper.id
                   WHERE uc.user_id = %s
                   ORDER BY uc.is_starred DESC, uc.created_at ASC""",
                (arxiv_id, user_id)
            )
        return cursor.fetchall()
    finally:
        cursor.close()


def _get_papers_in_category(user_id, cat_id, page=None, per_page=50):
    """Return ``(category, papers, total)`` with optional pagination."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, name, is_starred FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        cat = cursor.fetchone()
        if not cat:
            return None, None, 0

        cursor.execute(
            "SELECT COUNT(*) AS n FROM user_lists WHERE category_id = %s",
            (cat_id,),
        )
        total = cursor.fetchone()['n']

        limit_sql = ''
        params = [cat_id]
        if page is not None:
            offset = (page - 1) * per_page
            limit_sql = ' LIMIT %s OFFSET %s'
            params.extend((per_page, offset))

        cursor.execute(
            """SELECT p.id, p.arxiv_id, p.title, p.abstract, p.published_date,
                      p.updated_date, p.comment, p.primary_category,
                      p.journal_ref, p.doi, p.publication_url,
                      p.publication_venue_key, p.publication_status,
                      ul.added_at AS saved_at
               FROM user_lists ul
               JOIN papers p ON p.id = ul.paper_id
               WHERE ul.category_id = %s
               ORDER BY ul.added_at DESC""" + limit_sql,
            params,
        )
        rows = list(cursor.fetchall())
        attach_authors(cursor, rows)
        attach_keywords(cursor, rows)
        return cat, rows, total
    finally:
        cursor.close()


def _paper_membership_state(cursor, user_id, paper_id):
    """Return aggregate saved/starred state for one user's paper."""
    cursor.execute(
        """SELECT COUNT(*) > 0 AS saved,
                  COALESCE(MAX(uc.is_starred), 0) AS starred
           FROM user_lists ul
           JOIN user_categories uc ON uc.id = ul.category_id
           WHERE uc.user_id = %s AND ul.paper_id = %s""",
        (user_id, paper_id),
    )
    row = cursor.fetchone() or {}
    return bool(row.get('saved')), bool(row.get('starred'))


# ── Page routes ────────────────────────────────────────────────────────────────

@lists_bp.route('/lists')
def my_lists():
    user_id = session.get('user_id')
    if not user_id:
        session['login_next'] = url_for('lists.my_lists')
        return redirect(url_for('auth.login'))
    categories = _get_user_categories(user_id)

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
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    cat, papers, total = _get_papers_in_category(
        user_id, cat_id, page=page, per_page=per_page
    )
    if cat is None:
        abort(404)
    if total and not papers:
        abort(404)
    return render_template('list_detail.html',
                           category=cat,
                           cat_id=cat_id,
                           papers=papers,
                           page=page,
                           total=total,
                           has_prev=page > 1,
                           has_next=page * per_page < total)


# ── API routes ─────────────────────────────────────────────────────────────────

@lists_bp.route('/api/lists/star/<path:arxiv_id>', methods=['POST'])
def toggle_star(arxiv_id):
    user_id = _require_user()
    desired_raw = request.form.get('starred', '').strip().lower()
    if desired_raw not in {'true', 'false', '1', '0'}:
        return jsonify({'error': 'starred must be true or false'}), 400
    desired = desired_raw in {'true', '1'}
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM papers WHERE arxiv_id=%s",
            (arxiv_id,)
        )
        paper = cursor.fetchone()
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404

        if desired:
            cat_id, _ = _ensure_starred(cursor, user_id)
            cursor.execute(
                """INSERT INTO user_lists (category_id, paper_id)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE added_at = added_at""",
                (cat_id, paper['id'])
            )
        else:
            cursor.execute(
                "SELECT id FROM user_categories WHERE user_id=%s AND is_starred=1 LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                saved, _ = _paper_membership_state(cursor, user_id, paper['id'])
                return jsonify({'starred': False, 'saved': saved})
            cursor.execute(
                "DELETE FROM user_lists WHERE category_id=%s AND paper_id=%s",
                (row['id'], paper['id'])
            )
        saved, starred = _paper_membership_state(cursor, user_id, paper['id'])
        conn.commit()
        return jsonify({'starred': starred, 'saved': saved})
    except Exception:
        conn.rollback()
        raise
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
    if new_name.casefold() == STARRED_NAME.casefold():
        return jsonify({'error': 'The Starred name is reserved'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM papers WHERE arxiv_id=%s", (arxiv_id,))
        paper = cursor.fetchone()
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404

        if new_name:
            cursor.execute(
                "INSERT INTO user_categories (user_id, name) VALUES (%s, %s)",
                (user_id, new_name)
            )
            cat_name = new_name
            cat_id = cursor.lastrowid
        elif cat_id:
            cursor.execute(
                "SELECT name FROM user_categories WHERE id=%s AND user_id=%s FOR UPDATE",
                (cat_id, user_id)
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Category not found'}), 404
            cat_name = row['name']
        else:
            return jsonify({'error': 'category_id or new_name required'}), 400

        cursor.execute(
            """INSERT INTO user_lists (category_id, paper_id)
               VALUES (%s, %s)
               ON DUPLICATE KEY UPDATE added_at = added_at""",
            (cat_id, paper['id'])
        )
        already_present = cursor.rowcount == 0
        saved, starred = _paper_membership_state(cursor, user_id, paper['id'])
        conn.commit()
        return jsonify({
            'saved': saved,
            'starred': starred,
            'already_present': already_present,
            'category_id': cat_id,
            'category_name': cat_name,
        })
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'List name already exists'}), 409
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


@lists_bp.route('/api/lists/remove', methods=['POST'])
def remove_paper():
    user_id  = _require_user()
    arxiv_id = request.form.get('arxiv_id',    '').strip()
    cat_id   = request.form.get('category_id', type=int)

    if not arxiv_id or not cat_id:
        return jsonify({'error': 'arxiv_id and category_id required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Category not found'}), 404

        cursor.execute("SELECT id FROM papers WHERE arxiv_id=%s", (arxiv_id,))
        paper = cursor.fetchone()
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404

        cursor.execute(
            "DELETE FROM user_lists WHERE category_id=%s AND paper_id=%s",
            (cat_id, paper['id'])
        )
        removed = cursor.rowcount > 0
        saved, starred = _paper_membership_state(cursor, user_id, paper['id'])
        conn.commit()
        return jsonify({
            'removed': removed,
            'saved': saved,
            'starred': starred,
        })
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories')
def get_categories():
    user_id = _require_user()
    include_counts = request.args.get('counts', '1') != '0'
    arxiv_id = request.args.get('arxiv_id', '').strip() or None
    cats = _get_user_categories(
        user_id, include_counts=include_counts, arxiv_id=arxiv_id
    )
    payload = []
    for cat in cats:
        item = dict(cat)
        item['contains_paper'] = bool(item.get('contains_paper'))
        payload.append(item)
    return jsonify(payload)


@lists_bp.route('/api/lists/categories/new', methods=['POST'])
def new_category():
    user_id = _require_user()
    name = request.form.get('name', '').strip()[:100]
    if not name:
        return jsonify({'error': 'name required'}), 400
    if name.casefold() == STARRED_NAME.casefold():
        return jsonify({'error': 'The Starred name is reserved'}), 400

    conn = get_db_connection()
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
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories/<int:cat_id>/rename', methods=['POST'])
def rename_category(cat_id):
    user_id  = _require_user()
    new_name = request.form.get('name', '').strip()[:100]
    if not new_name:
        return jsonify({'error': 'name required'}), 400
    if new_name.casefold() == STARRED_NAME.casefold():
        return jsonify({'error': 'The Starred name is reserved'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name, is_starred FROM user_categories WHERE id=%s AND user_id=%s FOR UPDATE",
            (cat_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Category not found'}), 404
        if row['is_starred']:
            return jsonify({'error': 'Cannot rename the Starred list'}), 403

        cursor.execute(
            "UPDATE user_categories SET name=%s WHERE id=%s AND user_id=%s",
            (new_name, cat_id, user_id)
        )
        conn.commit()
        return jsonify({'renamed': True, 'name': new_name})
    except pymysql.err.IntegrityError:
        conn.rollback()
        return jsonify({'error': 'A list with that name already exists'}), 409
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


@lists_bp.route('/api/lists/categories/<int:cat_id>/delete', methods=['POST'])
def delete_category(cat_id):
    user_id = _require_user()

    conn = get_db_connection()
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
            "DELETE FROM user_categories WHERE id=%s AND user_id=%s",
            (cat_id, user_id)
        )
        conn.commit()
        return jsonify({'deleted': True})
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


@lists_bp.route('/api/lists/<int:cat_id>/bibtex')
def list_bibtex(cat_id):
    """Return all BibTeX entries for a list as plain text."""
    user_id = _require_user()
    cat, papers, _ = _get_papers_in_category(user_id, cat_id)
    if cat is None:
        abort(404)
    entries = [arxiv2bib(p) for p in papers]
    text = '\n\n'.join(entries)
    return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
