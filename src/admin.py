"""
admin.py - Admin blueprint for keyword management

Candidate statuses:
    ignore  — not math / typo / boilerplate; excluded from everything
    math    — valid math word but too broad alone (e.g. "point", "space")
    useful  — actively tag papers and contribute to relevance score

Routes:
    /admin/              → redirect to candidates
    /admin/login         → password login
    /admin/logout        → clear session
    /admin/candidates    → browse keywords.csv and triage
    /admin/keywords      → list all useful keywords
    /admin/keywords/<id>/edit   → edit a keyword
    /admin/keywords/<id>/delete → delete a keyword
"""

import os
import csv
import functools

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort, jsonify)
import pymysql
from config import DB_CONFIG, ADMIN_PASSWORD

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Path to keywords.csv (one level up from src/)
CANDIDATES_CSV = os.path.join(os.path.dirname(__file__), '..', 'keywords.csv')

# Simple module-level cache for the CSV
_candidates_cache = None
_candidates_mtime = None


def load_candidates():
    """Load keywords.csv, refreshing cache if file has changed."""
    global _candidates_cache, _candidates_mtime
    try:
        mtime = os.path.getmtime(CANDIDATES_CSV)
        if _candidates_cache is None or mtime != _candidates_mtime:
            with open(CANDIDATES_CSV, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                _candidates_cache = [
                    {
                        'phrase': row['phrase'],
                        'paper_count': int(row['paper_count']),
                        'word_count': int(row['word_count']),
                    }
                    for row in reader
                ]
            _candidates_mtime = mtime
    except FileNotFoundError:
        _candidates_cache = []
    return _candidates_cache


def get_db_connection():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return wrapped


def _get_reviewed(cursor):
    """Return (useful_set, math_set, ignored_set) from DB."""
    cursor.execute("SELECT phrase FROM keywords")
    useful = {row['phrase'] for row in cursor.fetchall()}
    cursor.execute("SELECT phrase FROM math_words")
    math = {row['phrase'] for row in cursor.fetchall()}
    cursor.execute("SELECT phrase FROM ignored_candidates")
    ignored = {row['phrase'] for row in cursor.fetchall()}
    return useful, math, ignored


def _phrase_status(phrase, useful, math, ignored):
    if phrase in useful:
        return 'useful'
    if phrase in math:
        return 'math'
    if phrase in ignored:
        return 'ignore'
    return 'unreviewed'


# ── Auth ─────────────────────────────────────────────────────────────────────

@admin.route('/')
@login_required
def index():
    return redirect(url_for('admin.candidates'))


@admin.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if ADMIN_PASSWORD and request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            next_url = request.args.get('next', '')
            # Only allow redirects to local paths (prevent open redirect)
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('admin.candidates'))
        flash('Wrong password.')
    return render_template('admin/login.html')


@admin.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))


# ── Candidates ────────────────────────────────────────────────────────────────

@admin.route('/candidates')
@login_required
def candidates():
    min_words = request.args.get('min_words',  2,  type=int)
    max_words = request.args.get('max_words',  4,  type=int)
    min_count = request.args.get('min_count',  10, type=int)
    search    = request.args.get('search', '').strip().lower()
    show      = request.args.get('show', 'unreviewed')  # unreviewed|useful|math|ignore|all
    page      = request.args.get('page', 1, type=int)
    per_page  = 50

    all_candidates = load_candidates()

    conn = get_db_connection()
    cursor = conn.cursor()
    useful, math, ignored = _get_reviewed(cursor)
    cursor.close()
    conn.close()

    filtered = []
    for c in all_candidates:
        if not (min_words <= c['word_count'] <= max_words):
            continue
        if c['paper_count'] < min_count:
            continue
        if search and search not in c['phrase']:
            continue
        status = _phrase_status(c['phrase'], useful, math, ignored)
        if show != 'all' and status != show:
            continue
        filtered.append({**c, 'status': status})

    total = len(filtered)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_candidates = filtered[(page - 1) * per_page: page * per_page]

    return render_template(
        'admin/candidates.html',
        candidates=page_candidates,
        page=page,
        total_pages=total_pages,
        total=total,
        min_words=min_words,
        max_words=max_words,
        min_count=min_count,
        search=search,
        show=show,
        useful_count=len(useful),
        math_count=len(math),
        ignored_count=len(ignored),
    )


@admin.route('/candidates/mark', methods=['POST'])
@login_required
def mark_candidate():
    """Mark a candidate as useful / math / ignore, or unmark it."""
    phrase = request.form.get('phrase', '').strip()
    status = request.form.get('status', '')   # useful | math | ignore | unreviewed

    if not phrase:
        return redirect(request.referrer or url_for('admin.candidates'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Remove from all three tables first (clean slate)
    cursor.execute("DELETE FROM keywords           WHERE phrase = %s", (phrase,))
    cursor.execute("DELETE FROM math_words         WHERE phrase = %s", (phrase,))
    cursor.execute("DELETE FROM ignored_candidates WHERE phrase = %s", (phrase,))

    if status == 'useful':
        cursor.execute(
            "INSERT INTO keywords (phrase, score, tag_name) VALUES (%s, 5, %s)",
            (phrase, phrase)
        )
    elif status == 'math':
        cursor.execute(
            "INSERT INTO math_words (phrase) VALUES (%s)", (phrase,)
        )
    elif status == 'ignore':
        cursor.execute(
            "INSERT INTO ignored_candidates (phrase) VALUES (%s)", (phrase,)
        )
    # 'unreviewed' → already removed from all tables above

    conn.commit()
    cursor.close()
    conn.close()
    return redirect(request.referrer or url_for('admin.candidates'))


# ── Keywords (useful) ─────────────────────────────────────────────────────────

@admin.route('/keywords')
@login_required
def keywords():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords ORDER BY phrase ASC")
    kws = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('admin/keywords.html', keywords=kws)


@admin.route('/keywords/<int:kid>/score', methods=['POST'])
@login_required
def set_score(kid):
    score = max(1, min(10, request.form.get('score', 5, type=int)))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE keywords SET score=%s WHERE id=%s", (score, kid))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'ok': True, 'score': score})


@admin.route('/keywords/<int:kid>/edit', methods=['GET', 'POST'])
@login_required
def edit_keyword(kid):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        phrase   = request.form.get('phrase', '').strip()
        score    = max(1, min(10, request.form.get('score', 5, type=int)))
        url      = request.form.get('url', '').strip() or None
        tag_name = request.form.get('tag_name', '').strip() or phrase
        cursor.execute(
            "UPDATE keywords SET phrase=%s, score=%s, url=%s, tag_name=%s WHERE id=%s",
            (phrase, score, url, tag_name, kid)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('admin.keywords'))

    cursor.execute("SELECT * FROM keywords WHERE id = %s", (kid,))
    kw = cursor.fetchone()
    cursor.close()
    conn.close()
    if not kw:
        abort(404)
    return render_template('admin/keyword_edit.html', kw=kw)


@admin.route('/keywords/<int:kid>/delete', methods=['POST'])
@login_required
def delete_keyword(kid):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keywords WHERE id = %s", (kid,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('admin.keywords'))


@admin.route('/keywords/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    ids = request.form.getlist('ids', type=int)
    if ids:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ','.join(['%s'] * len(ids))
        cursor.execute(f"DELETE FROM keywords WHERE id IN ({placeholders})", ids)
        conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('admin.keywords'))
