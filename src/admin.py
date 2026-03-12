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
    /admin/keywords      → list all useful keywords (inline-editable)
    /admin/keywords/<id>/inline  → AJAX: update phrase/url
    /admin/keywords/<id>/merge   → AJAX: merge keyword into another (becomes alias)
    /admin/keywords/<id>/score   → AJAX: update score
    /admin/keywords/<id>/aliases/add    → AJAX: add alias
    /admin/keywords/<id>/aliases/<aid>/delete → AJAX: remove alias
    /admin/keywords/<id>/delete  → delete a keyword
    /admin/retag                 → re-tag papers by date range
    /admin/paper/<arxiv_id>/refetch → AJAX: re-fetch a paper from arXiv
"""

import os
import csv
import hmac
import functools
from datetime import date as date_type
from urllib.parse import urlparse, urljoin

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, abort, jsonify, g)
import logging
import pymysql
from config import DB_CONFIG, ADMIN_PASSWORD

logger = logging.getLogger(__name__)

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
    """Return a per-request DB connection (cached on Flask g, closed on teardown)."""
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    return g.db


def login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return wrapped


def _get_reviewed(cursor):
    """Return (useful_set, aliases_map, math_set, ignored_set) from DB.

    aliases_map: alias phrase -> canonical keyword phrase
    """
    cursor.execute("SELECT phrase FROM keywords")
    useful = {row['phrase'] for row in cursor.fetchall()}
    cursor.execute("""
        SELECT ka.alias, k.phrase AS canonical
        FROM keyword_aliases ka
        JOIN keywords k ON k.id = ka.keyword_id
    """)
    aliases_map = {row['alias']: row['canonical'] for row in cursor.fetchall()}
    cursor.execute("SELECT phrase FROM math_words")
    math = {row['phrase'] for row in cursor.fetchall()}
    cursor.execute("SELECT phrase FROM ignored_candidates")
    ignored = {row['phrase'] for row in cursor.fetchall()}
    return useful, aliases_map, math, ignored


def _phrase_status(phrase, useful, aliases_map, math, ignored):
    if phrase in useful:
        return 'useful'
    if phrase in aliases_map:
        return 'alias'
    if phrase in math:
        return 'math'
    if phrase in ignored:
        return 'ignore'
    return 'unreviewed'


# ── Auth ─────────────────────────────────────────────────────────────────────

def _is_safe_redirect(target):
    """Return True only if target resolves to the same host (prevents open redirect)."""
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ('http', 'https') and test.netloc == ref.netloc


@admin.route('/')
@login_required
def index():
    return redirect(url_for('admin.candidates'))


@admin.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if ADMIN_PASSWORD and hmac.compare_digest(password, ADMIN_PASSWORD):
            session['admin_logged_in'] = True
            logger.info("Admin login successful from %s", request.remote_addr)
            next_url = request.args.get('next', '')
            # Only allow redirects to same-host paths (prevent open redirect)
            if next_url and _is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for('admin.candidates'))
        logger.warning("Failed admin login attempt from %s", request.remote_addr)
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
    useful, aliases_map, math, ignored = _get_reviewed(cursor)
    cursor.close()

    filtered = []
    for c in all_candidates:
        if not (min_words <= c['word_count'] <= max_words):
            continue
        if c['paper_count'] < min_count:
            continue
        if search and search not in c['phrase']:
            continue
        status = _phrase_status(c['phrase'], useful, aliases_map, math, ignored)
        if show != 'all' and status != show:
            continue
        extra = {'alias_of': aliases_map.get(c['phrase'])} if status == 'alias' else {}
        filtered.append({**c, 'status': status, **extra})

    total = len(filtered)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    page_candidates = filtered[(page - 1) * per_page: page * per_page]

    return render_template(
        'admin/candidates.html',
        candidates=page_candidates,
        keyword_phrases=sorted(useful),
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
    """Mark a candidate as useful / alias / math / ignore, or unmark it."""
    phrase = request.form.get('phrase', '').strip()
    status = request.form.get('status', '')   # useful | alias | math | ignore | unreviewed
    # keyword_phrase: corrected phrase (for useful) or the alias text (for alias)
    keyword_phrase = request.form.get('keyword_phrase', '').strip() or phrase
    # alias_of: canonical keyword phrase this candidate is an alias of
    alias_of = request.form.get('alias_of', '').strip()

    if not phrase:
        return redirect(request.referrer or url_for('admin.candidates'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # If phrase is currently a keyword, save its id so we can reassign paper_keywords
    # before deleting (avoids cascade-deleting paper associations).
    cursor.execute("SELECT id FROM keywords WHERE phrase = %s", (phrase,))
    existing_kw = cursor.fetchone()
    existing_kw_id = existing_kw['id'] if existing_kw else None

    # Remove from all three tables and any existing alias entry (clean slate)
    cursor.execute("DELETE FROM math_words         WHERE phrase = %s", (phrase,))
    cursor.execute("DELETE FROM ignored_candidates WHERE phrase = %s", (phrase,))
    cursor.execute("DELETE FROM keyword_aliases    WHERE alias  = %s", (phrase,))

    if status == 'useful':
        try:
            if existing_kw_id:
                cursor.execute("UPDATE keywords SET phrase = %s WHERE id = %s",
                               (keyword_phrase, existing_kw_id))
            else:
                cursor.execute(
                    "INSERT IGNORE INTO keywords (phrase, score) VALUES (%s, 5)",
                    (keyword_phrase,)
                )
        except pymysql.IntegrityError:
            flash(f'Could not save «{keyword_phrase}»: a keyword with that phrase already exists.')
            cursor.close()
            return redirect(request.referrer or url_for('admin.candidates'))
    elif status == 'alias' and alias_of:
        # Look up the canonical keyword
        cursor.execute("SELECT id FROM keywords WHERE phrase = %s", (alias_of,))
        row = cursor.fetchone()
        if row:
            canonical_id = row['id']
            if existing_kw_id:
                # Move paper_keywords and sub-aliases to canonical; avoid duplicate key errors
                cursor.execute("""
                    INSERT IGNORE INTO paper_keywords (paper_id, keyword_id)
                    SELECT paper_id, %s FROM paper_keywords WHERE keyword_id = %s
                """, (canonical_id, existing_kw_id))
                cursor.execute("DELETE FROM paper_keywords WHERE keyword_id = %s", (existing_kw_id,))
                cursor.execute("""
                    INSERT IGNORE INTO keyword_aliases (keyword_id, alias)
                    SELECT %s, alias FROM keyword_aliases WHERE keyword_id = %s
                """, (canonical_id, existing_kw_id))
                cursor.execute("DELETE FROM keyword_aliases WHERE keyword_id = %s", (existing_kw_id,))
                cursor.execute("DELETE FROM keywords WHERE id = %s", (existing_kw_id,))
            cursor.execute(
                "INSERT IGNORE INTO keyword_aliases (keyword_id, alias) VALUES (%s, %s)",
                (canonical_id, keyword_phrase)
            )
        else:
            # Canonical not found — fall back to creating a new keyword
            if existing_kw_id:
                cursor.execute("UPDATE keywords SET phrase = %s WHERE id = %s",
                               (keyword_phrase, existing_kw_id))
            else:
                cursor.execute(
                    "INSERT IGNORE INTO keywords (phrase, score) VALUES (%s, 5)",
                    (keyword_phrase,)
                )
    else:
        # math / ignore / unreviewed — delete the keyword if it existed
        if existing_kw_id:
            cursor.execute("DELETE FROM keywords WHERE id = %s", (existing_kw_id,))
        if status == 'math':
            cursor.execute("INSERT INTO math_words (phrase) VALUES (%s)", (phrase,))
        elif status == 'ignore':
            cursor.execute("INSERT INTO ignored_candidates (phrase) VALUES (%s)", (phrase,))
    # 'unreviewed' → already removed from all tables above

    conn.commit()
    cursor.close()
    return redirect(request.referrer or url_for('admin.candidates'))


# ── Keywords (useful) ─────────────────────────────────────────────────────────

@admin.route('/keywords')
@login_required
def keywords():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT k.*, COUNT(pk.paper_id) AS paper_count
        FROM keywords k
        LEFT JOIN paper_keywords pk ON k.id = pk.keyword_id
        GROUP BY k.id
        ORDER BY k.phrase ASC
    """)
    kws = cursor.fetchall()
    cursor.execute("SELECT * FROM keyword_aliases ORDER BY alias")
    aliases_by_kw = {}
    for a in cursor.fetchall():
        aliases_by_kw.setdefault(a['keyword_id'], []).append(a)
    all_phrases = sorted(row['phrase'] for row in kws)
    cursor.close()
    return render_template('admin/keywords.html', keywords=kws,
                           aliases_by_kw=aliases_by_kw,
                           keyword_phrases=all_phrases)


@admin.route('/keywords/add', methods=['POST'])
@login_required
def add_keyword():
    phrase = request.form.get('phrase', '').strip().lower()
    if not phrase:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT IGNORE INTO keywords (phrase, score) VALUES (%s, 5)",
        (phrase,)
    )
    conn.commit()
    kid = cursor.lastrowid
    cursor.close()
    if not kid:
        return jsonify({'ok': False, 'error': 'duplicate'}), 409
    return jsonify({'ok': True, 'id': kid, 'phrase': phrase})


@admin.route('/keywords/<int:kid>/inline', methods=['POST'])
@login_required
def inline_edit(kid):
    field = request.form.get('field')
    _COL_SQL = {
        'phrase': 'UPDATE keywords SET phrase=%s WHERE id=%s',
        'url':    'UPDATE keywords SET url=%s    WHERE id=%s',
    }
    sql = _COL_SQL.get(field)
    if not sql:
        abort(400)
    value = request.form.get('value', '').strip() or None
    if field == 'phrase' and not value:
        return jsonify({'ok': False, 'error': 'phrase cannot be empty'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, (value, kid))
        conn.commit()
    except pymysql.IntegrityError:
        cursor.close()
        return jsonify({'ok': False, 'error': 'duplicate'}), 409
    cursor.close()
    return jsonify({'ok': True, 'value': value})


@admin.route('/keywords/<int:kid>/aliases/add', methods=['POST'])
@login_required
def add_alias(kid):
    alias = request.form.get('alias', '').strip().lower()
    if not alias:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phrase FROM keywords WHERE id = %s", (kid,))
    kw = cursor.fetchone()
    if kw and kw['phrase'] == alias:
        cursor.close()
        return jsonify({'ok': False, 'error': 'self'}), 400
    try:
        # If the alias phrase already exists as a standalone keyword, absorb it:
        # reassign its paper_keywords and aliases to kid, then delete it.
        cursor.execute("SELECT id FROM keywords WHERE phrase = %s AND id != %s", (alias, kid))
        dup = cursor.fetchone()
        if dup:
            dup_id = dup['id']
            cursor.execute("""
                INSERT IGNORE INTO paper_keywords (paper_id, keyword_id)
                SELECT paper_id, %s FROM paper_keywords WHERE keyword_id = %s
            """, (kid, dup_id))
            cursor.execute("DELETE FROM paper_keywords WHERE keyword_id = %s", (dup_id,))
            cursor.execute("""
                INSERT IGNORE INTO keyword_aliases (keyword_id, alias)
                SELECT %s, alias FROM keyword_aliases WHERE keyword_id = %s
            """, (kid, dup_id))
            cursor.execute("DELETE FROM keyword_aliases WHERE keyword_id = %s", (dup_id,))
            cursor.execute("DELETE FROM keywords WHERE id = %s", (dup_id,))

        cursor.execute(
            "INSERT INTO keyword_aliases (keyword_id, alias) VALUES (%s, %s)",
            (kid, alias)
        )
        conn.commit()
        aid = cursor.lastrowid
        cursor.close()
        return jsonify({'ok': True, 'id': aid, 'alias': alias, 'absorbed': bool(dup)})
    except pymysql.IntegrityError:
        cursor.close()
        return jsonify({'ok': False, 'error': 'duplicate'}), 409


@admin.route('/keywords/<int:kid>/aliases/<int:aid>/delete', methods=['POST'])
@login_required
def delete_alias(kid, aid):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keyword_aliases WHERE id=%s AND keyword_id=%s", (aid, kid))
    conn.commit()
    cursor.close()
    return jsonify({'ok': True})


@admin.route('/keywords/<int:kid>/merge', methods=['POST'])
@login_required
def merge_keyword(kid):
    """Merge keyword kid into another keyword (by phrase). kid becomes an alias."""
    into_phrase = request.form.get('into_phrase', '').strip().lower()
    if not into_phrase:
        return jsonify({'ok': False, 'error': 'empty'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phrase FROM keywords WHERE id = %s", (kid,))
    src = cursor.fetchone()
    if not src:
        cursor.close(); return jsonify({'ok': False, 'error': 'not found'}), 404
    if into_phrase == src['phrase']:
        cursor.close(); return jsonify({'ok': False, 'error': 'cannot merge into itself'}), 400
    cursor.execute("SELECT id FROM keywords WHERE phrase = %s AND id != %s", (into_phrase, kid))
    dst = cursor.fetchone()
    if not dst:
        cursor.close();        return jsonify({'ok': False, 'error': 'target not found'}), 404
    dst_id = dst['id']
    # Merge paper_keywords: copy papers src has that dst doesn't, then drop src's rows
    cursor.execute("""
        INSERT IGNORE INTO paper_keywords (paper_id, keyword_id)
        SELECT paper_id, %s FROM paper_keywords WHERE keyword_id = %s
    """, (dst_id, kid))
    cursor.execute("DELETE FROM paper_keywords WHERE keyword_id = %s", (kid,))
    # Merge sub-aliases similarly
    cursor.execute("""
        INSERT IGNORE INTO keyword_aliases (keyword_id, alias)
        SELECT %s, alias FROM keyword_aliases WHERE keyword_id = %s
    """, (dst_id, kid))
    cursor.execute("DELETE FROM keyword_aliases WHERE keyword_id = %s", (kid,))
    cursor.execute("DELETE FROM keywords WHERE id = %s", (kid,))
    # Add src phrase as alias of dst (ignore if already exists)
    cursor.execute("INSERT IGNORE INTO keyword_aliases (keyword_id, alias) VALUES (%s, %s)",
                   (dst_id, src['phrase']))
    conn.commit()
    cursor.close();    return jsonify({'ok': True})


@admin.route('/keywords/<int:kid>/score', methods=['POST'])
@login_required
def set_score(kid):
    score = max(1, min(10, request.form.get('score', 5, type=int)))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE keywords SET score=%s WHERE id=%s", (score, kid))
    conn.commit()
    cursor.close()
    return jsonify({'ok': True, 'score': score})



@admin.route('/keywords/<int:kid>/delete', methods=['POST'])
@login_required
def delete_keyword(kid):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keywords WHERE id = %s", (kid,))
    conn.commit()
    cursor.close()
    return jsonify({'ok': True})


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
    return jsonify({'ok': True, 'deleted': ids})


@admin.route('/keywords/<int:kid>/retag', methods=['POST'])
@login_required
def retag_keyword(kid):
    """Re-tag all papers for a single keyword (phrase + all its aliases)."""
    from auto_tag import tokenize, extract_matching_keyword_ids
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT phrase FROM keywords WHERE id=%s AND active=1", (kid,))
    kw = cursor.fetchone()
    if not kw:
        cursor.close()
        return jsonify({'ok': False, 'error': 'not found'}), 404

    phrase_to_id = {kw['phrase']: kid}
    cursor.execute("SELECT alias FROM keyword_aliases WHERE keyword_id=%s", (kid,))
    for row in cursor.fetchall():
        phrase_to_id[row['alias']] = kid

    max_ngram = max(len(p.split()) for p in phrase_to_id)

    cursor.execute("SELECT id, title, abstract FROM papers")
    papers = cursor.fetchall()

    cursor.execute("DELETE FROM paper_keywords WHERE keyword_id=%s", (kid,))

    rows = []
    for paper in papers:
        text = (paper['title'] or '') + ' ' + (paper['abstract'] or '')
        if extract_matching_keyword_ids(text, phrase_to_id, max_ngram):
            rows.append((paper['id'], kid))

    if rows:
        cursor.executemany(
            "INSERT IGNORE INTO paper_keywords (paper_id, keyword_id) VALUES (%s, %s)", rows
        )
    conn.commit()
    cursor.close()
    return jsonify({'ok': True, 'count': len(rows)})


# ── Retag ─────────────────────────────────────────────────────────────────────

@admin.route('/paper/<path:arxiv_id>/refetch', methods=['POST'])
@login_required
def refetch_paper(arxiv_id):
    """Re-fetch a single paper from arXiv and update the DB."""
    try:
        from fetch_arxiv import fetch_by_arxiv_id
        import io, contextlib
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            fetch_by_arxiv_id(arxiv_id)
        return jsonify({'ok': True, 'log': output.getvalue()})
    except Exception as e:
        logger.exception("refetch_paper failed for %s", arxiv_id)
        return jsonify({'ok': False, 'error': str(e)}), 500


@admin.route('/users')
@login_required
def users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.provider, u.provider_id, u.display_name, u.created_at,
               COUNT(DISTINCT wk.keyword_id) AS watched_keywords,
               COUNT(DISTINCT wa.author_id)  AS watched_authors,
               COUNT(DISTINCT ul.id)         AS list_papers
        FROM users u
        LEFT JOIN user_watched_keywords wk ON wk.user_id = u.id
        LEFT JOIN user_watched_authors  wa ON wa.user_id = u.id
        LEFT JOIN user_lists            ul ON ul.user_id = u.id
        GROUP BY u.id, u.provider, u.provider_id, u.display_name, u.created_at
        ORDER BY u.created_at DESC
    """)
    all_users = cursor.fetchall()
    cursor.close()
    return render_template('admin/users.html', users=all_users)


@admin.route('/retag', methods=['GET', 'POST'])
@login_required
def retag():
    from auto_tag import load_keywords, tag_papers

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MIN(published_date) as earliest FROM papers")
    row = cursor.fetchone()
    earliest = str(row['earliest']) if row and row['earliest'] else '2000-01-01'
    today = str(date_type.today())

    result = None

    if request.method == 'POST':
        from_date = request.form.get('from_date', earliest)
        to_date   = request.form.get('to_date',   today)

        phrase_to_id = load_keywords(cursor)
        if not phrase_to_id:
            flash('No active keywords found.')
        else:
            max_ngram = max(len(p.split()) for p in phrase_to_id)
            cursor.execute(
                "SELECT id, title, abstract FROM papers"
                " WHERE published_date BETWEEN %s AND %s ORDER BY published_date",
                (from_date, to_date)
            )
            papers = [(r['id'], r['title'], r['abstract']) for r in cursor.fetchall()]
            n_tags = tag_papers(cursor, papers, phrase_to_id, max_ngram)
            conn.commit()
            result = {'papers': len(papers), 'tags': n_tags,
                      'from': from_date, 'to': to_date}

    cursor.close()
    return render_template('admin/retag.html',
                           earliest=earliest, today=today, result=result)
