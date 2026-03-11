#!/usr/bin/env python3
"""
app.py - Flask web application for arXiv combinatorics frontend

Main web interface for browsing arXiv papers.
"""

from flask import Flask, render_template, request, jsonify, abort, redirect, url_for, session, g
from urllib.parse import unquote
import io
import contextlib
import calendar
import logging
import re
import pymysql
import requests
from config import DB_CONFIG, FLASK_CONFIG, FETCH_SECRET, validate_config
from datetime import datetime, date, timedelta
from utils import strip_accents, slugify, protect_capitals_for_bibtex, generate_bibtex_key, arxiv2bib

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Validate configuration on startup
validate_config()

app = Flask(__name__)
app.config.update(FLASK_CONFIG)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

from admin import admin as admin_blueprint
app.register_blueprint(admin_blueprint)

from auth import auth as auth_blueprint, init_oauth
app.register_blueprint(auth_blueprint)
init_oauth(app)

from lists import lists_bp
app.register_blueprint(lists_bp)


@app.context_processor
def inject_current_user():
    user_id = session.get('user_id')
    ctx = {'is_admin': bool(session.get('admin_logged_in'))}
    if user_id:
        ctx['current_user'] = {
            'id':       user_id,
            'name':     session.get('user_name', ''),
            'orcid_id': session.get('orcid_id', ''),
        }
    else:
        ctx['current_user'] = None
    return ctx


# Register slugify as a Jinja filter
app.jinja_env.filters['slugify'] = lambda name: slugify(name) if name else ''


def doi2bib(doi, paper_data=None):
    """
    Generate BibTeX entry from DOI using content negotiation,
    or create a custom entry if paper_data is provided.

    Args:
        doi: DOI string
        paper_data: Optional dict with paper metadata for custom formatting

    Returns:
        BibTeX string or None on error
    """
    if paper_data:
        # Generate custom BibTeX with user's preferred format
        year = paper_data['published_date'].year if hasattr(paper_data['published_date'], 'year') else paper_data['published_date']
        bibtex_key = generate_bibtex_key(paper_data.get('authors', []), year, published=True)

        author_str = ' and '.join(paper_data.get('authors', [])) if paper_data.get('authors') else 'Unknown'
        protected_title = protect_capitals_for_bibtex(paper_data['title'])

        bibtex = f"""@article{{{bibtex_key},
Author = {{{author_str}}},
Title = {{{protected_title}}},
Year = {{{year}}},
journal = {{{paper_data.get('journal_ref', '')}}},
doi = {{{doi}}},
  url = {{https://doi.org/{doi}}}
}}"""
        return bibtex
    else:
        # Fetch from DOI.org
        try:
            doi_url = f"https://doi.org/{doi}"
            headers = {'Accept': 'application/x-bibtex'}
            response = requests.get(doi_url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None


def get_db_connection():
    """Return a per-request DB connection (cached on Flask g, closed on teardown)."""
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    return g.db


@app.teardown_appcontext
def close_db_connection(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def ensure_author_slugs():
    """Add slug column if missing and populate any NULL slugs. Uses its own connection (runs at startup)."""
    conn = pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    cursor = conn.cursor()
    try:
        # Add slug column if it doesn't exist
        cursor.execute("SHOW COLUMNS FROM authors LIKE 'slug'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE authors ADD COLUMN slug VARCHAR(255)")
            cursor.execute("CREATE INDEX idx_author_slug ON authors(slug)")
            conn.commit()

        # Populate missing slugs
        cursor.execute("SELECT id, name FROM authors WHERE slug IS NULL")
        authors = cursor.fetchall()
        if authors:
            for author in authors:
                cursor.execute("UPDATE authors SET slug = %s WHERE id = %s",
                               (slugify(author['name']), author['id']))
            conn.commit()
    finally:
        cursor.close()
        conn.close()


# Populate slugs on startup
try:
    ensure_author_slugs()
except pymysql.Error as e:
    logger.warning("ensure_author_slugs skipped (DB unavailable): %s", e)


def get_paper_authors(cursor, paper_id):
    """Get ordered list of authors for a paper."""
    cursor.execute("""
        SELECT a.name
        FROM authors a
        JOIN paper_authors pa ON a.id = pa.author_id
        WHERE pa.paper_id = %s
        ORDER BY pa.author_order
    """, (paper_id,))
    return [row['name'] for row in cursor.fetchall()]


def attach_keywords(cursor, papers):
    """Attach keywords to a list of papers in a single query (avoids N+1)."""
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
    kw_by_paper = {}
    for row in cursor.fetchall():
        kw_by_paper.setdefault(row['paper_id'], []).append({'phrase': row['phrase'], 'url': row['url']})
    for paper in papers:
        paper['keywords'] = kw_by_paper.get(paper['id'], [])


def attach_authors(cursor, papers):
    """Attach authors to a list of papers in a single query (avoids N+1)."""
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
    authors_by_paper = {}
    for row in cursor.fetchall():
        authors_by_paper.setdefault(row['paper_id'], []).append(row['name'])
    for paper in papers:
        paper['authors'] = authors_by_paper.get(paper['id'], [])


@app.route('/')
def index():
    """Homepage - list recent papers."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get total count and author count
    cursor.execute("SELECT COUNT(*) as count FROM papers")
    total = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM authors")
    total_authors = cursor.fetchone()['count']

    # Get latest published date
    cursor.execute("SELECT MAX(published_date) as latest FROM papers")
    latest_date = cursor.fetchone()['latest']

    # Get papers for current page
    cursor.execute("""
        SELECT id, arxiv_id, title, abstract, published_date, updated_date,
               journal_ref, doi, comment, primary_category
        FROM papers
        ORDER BY published_date DESC, id DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))

    papers = cursor.fetchall()

    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)

    cursor.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('index.html',
                         papers=papers,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         total_authors=total_authors,
                         latest_date=latest_date)


@app.route('/paper/<path:arxiv_id>')
def paper_detail(arxiv_id):
    """Paper detail page."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, arxiv_id, title, abstract, published_date, updated_date,
               comment, journal_ref, doi, primary_category
        FROM papers
        WHERE arxiv_id = %s
    """, (arxiv_id,))

    paper = cursor.fetchone()

    if not paper:
        abort(404)

    paper['authors'] = get_paper_authors(cursor, paper['id'])

    cursor.execute("""
        SELECT k.phrase, k.score, k.url
        FROM paper_keywords pk
        JOIN keywords k ON pk.keyword_id = k.id
        WHERE pk.paper_id = %s
        ORDER BY k.score DESC, k.phrase ASC
    """, (paper['id'],))
    paper['keywords'] = cursor.fetchall()

    cursor.close()

    return render_template('paper.html', paper=paper)


@app.route('/api/bibtex/<path:arxiv_id>')
def bibtex(arxiv_id):
    """Generate arXiv BibTeX entry for a paper."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, arxiv_id, title, published_date, journal_ref, doi
        FROM papers
        WHERE arxiv_id = %s
    """, (arxiv_id,))

    paper = cursor.fetchone()

    if not paper:
        abort(404)

    paper['authors'] = get_paper_authors(cursor, paper['id'])
    cursor.close()

    bibtex = arxiv2bib(paper)
    return bibtex, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/api/doi-bibtex/<path:arxiv_id>')
def doi_bibtex(arxiv_id):
    """Generate published BibTeX entry for a paper with DOI."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, arxiv_id, title, published_date, journal_ref, doi
        FROM papers
        WHERE arxiv_id = %s
    """, (arxiv_id,))

    paper = cursor.fetchone()

    if not paper or not paper['doi']:
        abort(404)

    paper['authors'] = get_paper_authors(cursor, paper['id'])
    cursor.close()

    # Generate custom BibTeX with user's preferred format
    bibtex = doi2bib(paper['doi'], paper)
    if bibtex:
        return bibtex, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    else:
        return "Error generating DOI BibTeX", 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/tools')
def tools():
    """Tools page for BibTeX generation."""
    return render_template('tools.html')


@app.route('/authors')
def prolific_authors():
    """List authors with 50 or more papers."""
    sort = request.args.get('sort', 'count')
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    if sort == 'name':
        order = "SUBSTRING_INDEX(a.name, ' ', -1) ASC, a.name ASC"
    else:
        order = "paper_count DESC, a.name ASC"
    cursor.execute(f"""
        SELECT a.name, a.slug, COUNT(*) AS paper_count
        FROM paper_authors pa
        JOIN authors a ON pa.author_id = a.id
        GROUP BY a.id, a.name, a.slug
        HAVING paper_count >= 50
        ORDER BY {order}
    """)
    authors = cursor.fetchall()
    cursor.close()
    # Split into 3 roughly equal columns
    n = len(authors)
    col_size = (n + 2) // 3
    columns = [authors[i:i + col_size] for i in range(0, n, col_size)]
    return render_template('authors.html', columns=columns, total=n, sort=sort)


@app.route('/api/generate-bibtex', methods=['POST'])
def generate_bibtex_api():
    """API endpoint to generate BibTeX from arXiv ID or DOI."""
    data = request.get_json()
    input_text = data.get('input', '').strip()

    if not input_text:
        return jsonify({'error': 'Please provide an arXiv ID or DOI'}), 400

    # Try to parse as arXiv ID or URL
    arxiv_id = None
    doi = None

    # Check if it's an arXiv URL or ID
    if 'arxiv.org' in input_text.lower():
        # Extract ID from URL
        match = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]+\.[0-9]+(?:v[0-9]+)?)', input_text, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
    elif re.match(r'^[0-9]+\.[0-9]+(?:v[0-9]+)?$', input_text):
        # Direct arXiv ID
        arxiv_id = input_text

    # Check if it's a DOI or DOI URL
    if not arxiv_id:
        if 'doi.org/' in input_text.lower():
            # Extract DOI from URL
            doi = input_text.split('doi.org/')[-1]
        elif re.match(r'^10\.\d+/', input_text):
            # Direct DOI
            doi = input_text

    if arxiv_id:
        # Fetch from our database
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, arxiv_id, title, published_date, journal_ref, doi
            FROM papers
            WHERE arxiv_id LIKE %s
        """, (f"{arxiv_id}%",))

        paper = cursor.fetchone()

        if paper:
            paper['authors'] = get_paper_authors(cursor, paper['id'])
            cursor.close()

            arxiv_bib = arxiv2bib(paper)
            result = {'arxiv': arxiv_bib}

            if paper['doi']:
                published_bib = doi2bib(paper['doi'], paper)
                if published_bib:
                    result['published'] = published_bib

            return jsonify(result)
        else:
            cursor.close()
            return jsonify({'error': 'arXiv paper not found in database'}), 404

    elif doi:
        # Fetch directly from DOI
        bibtex = doi2bib(doi)
        if bibtex:
            return jsonify({'published': bibtex})
        else:
            return jsonify({'error': 'Failed to fetch BibTeX from DOI'}), 500

    return jsonify({'error': 'Could not parse input as arXiv ID or DOI'}), 400


@app.route('/search')
def search():
    """Search papers by title or author."""
    query = request.args.get('q', '').strip()[:500]  # cap at 500 chars
    sort  = request.args.get('sort', 'relevance')  # 'relevance' or 'date'
    page  = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    if not query:
        return render_template('search.html', papers=[], query='', total=0, sort=sort)

    conn = get_db_connection()
    cursor = conn.cursor()

    author_term = f"%{query}%"

    # Get latest published date
    cursor.execute("SELECT MAX(published_date) as latest FROM papers")
    latest_date = cursor.fetchone()['latest']

    # Keyword score subquery — aggregated per paper, independent of author join
    kw_subquery = """
        (SELECT pk.paper_id, COALESCE(SUM(k.score), 0) AS kw_score
         FROM paper_keywords pk
         JOIN keywords k ON pk.keyword_id = k.id
         GROUP BY pk.paper_id) kw
    """

    order_clause = ("kw_score DESC, p.published_date DESC, p.id DESC"
                    if sort == 'relevance'
                    else "p.published_date DESC, p.id DESC")

    # Use FULLTEXT for title/abstract when words are long enough (min 3 chars),
    # fall back to LIKE for very short queries
    words = query.split()
    use_fulltext = all(len(w) >= 3 for w in words) and len(words) > 0

    if use_fulltext:
        ft_query = '+' + ' +'.join(words)  # boolean mode: require all words

        cursor.execute("""
            SELECT COUNT(DISTINCT p.id) as count
            FROM papers p
            LEFT JOIN paper_authors pa ON p.id = pa.paper_id
            LEFT JOIN authors a ON pa.author_id = a.id
            WHERE MATCH(p.title, p.abstract) AGAINST(%s IN BOOLEAN MODE)
               OR a.name LIKE %s
        """, (ft_query, author_term))
        total = cursor.fetchone()['count']

        cursor.execute(f"""
            SELECT p.id, p.arxiv_id, p.title, p.abstract,
                   p.published_date, p.updated_date, p.journal_ref, p.doi,
                   p.comment, p.primary_category,
                   COALESCE(kw.kw_score, 0) AS kw_score
            FROM papers p
            LEFT JOIN paper_authors pa ON p.id = pa.paper_id
            LEFT JOIN authors a ON pa.author_id = a.id
            LEFT JOIN {kw_subquery} ON p.id = kw.paper_id
            WHERE MATCH(p.title, p.abstract) AGAINST(%s IN BOOLEAN MODE)
               OR a.name LIKE %s
            GROUP BY p.id, p.arxiv_id, p.title, p.abstract,
                     p.published_date, p.updated_date, p.journal_ref, p.doi,
                     p.comment, p.primary_category, kw.kw_score
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """, (ft_query, author_term, per_page, offset))
    else:
        like_term = f"%{query}%"

        cursor.execute("""
            SELECT COUNT(DISTINCT p.id) as count
            FROM papers p
            LEFT JOIN paper_authors pa ON p.id = pa.paper_id
            LEFT JOIN authors a ON pa.author_id = a.id
            WHERE p.title LIKE %s
               OR p.abstract LIKE %s
               OR a.name LIKE %s
        """, (like_term, like_term, like_term))
        total = cursor.fetchone()['count']

        cursor.execute(f"""
            SELECT p.id, p.arxiv_id, p.title, p.abstract,
                   p.published_date, p.updated_date, p.journal_ref, p.doi,
                   p.comment, p.primary_category,
                   COALESCE(kw.kw_score, 0) AS kw_score
            FROM papers p
            LEFT JOIN paper_authors pa ON p.id = pa.paper_id
            LEFT JOIN authors a ON pa.author_id = a.id
            LEFT JOIN {kw_subquery} ON p.id = kw.paper_id
            WHERE p.title LIKE %s
               OR p.abstract LIKE %s
               OR a.name LIKE %s
            GROUP BY p.id, p.arxiv_id, p.title, p.abstract,
                     p.published_date, p.updated_date, p.journal_ref, p.doi,
                     p.comment, p.primary_category, kw.kw_score
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """, (like_term, like_term, like_term, per_page, offset))

    papers = cursor.fetchall()
    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)

    cursor.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('search.html',
                           papers=papers,
                           query=query,
                           sort=sort,
                           page=page,
                           total_pages=total_pages,
                           total=total,
                           latest_date=latest_date)


@app.route('/keyword/<path:phrase>')
def keyword_papers(phrase):
    """List papers tagged with a specific keyword, ordered by date."""
    phrase = unquote(phrase).replace('+', ' ')  # handle both %20 and + encodings
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, phrase, score, url FROM keywords WHERE phrase = %s AND active = 1", (phrase,))
    keyword = cursor.fetchone()
    if not keyword:
        abort(404)

    cursor.execute("""
        SELECT COUNT(*) as count FROM paper_keywords WHERE keyword_id = %s
    """, (keyword['id'],))
    total = cursor.fetchone()['count']

    cursor.execute("""
        SELECT p.id, p.arxiv_id, p.title, p.abstract,
               p.published_date, p.updated_date, p.journal_ref, p.doi,
               p.comment, p.primary_category
        FROM paper_keywords pk
        JOIN papers p ON pk.paper_id = p.id
        WHERE pk.keyword_id = %s
        ORDER BY p.published_date DESC, p.id DESC
        LIMIT %s OFFSET %s
    """, (keyword['id'], per_page, offset))
    papers = cursor.fetchall()

    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)

    cursor.close()

    total_pages = (total + per_page - 1) // per_page
    return render_template('keyword.html',
                           keyword=keyword,
                           papers=papers,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@app.route('/author/<author_slug>')
def author_papers(author_slug):
    """List all papers by a specific author (looked up by slug)."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # Look up by slug first, fall back to name (for old-format URLs)
    cursor.execute("SELECT id, name, slug FROM authors WHERE slug = %s", (author_slug,))
    author = cursor.fetchone()
    if not author:
        # Fall back: try matching by exact name (old URLs with spaces)
        cursor.execute("SELECT id, name, slug FROM authors WHERE name = %s", (author_slug,))
        author = cursor.fetchone()
    if not author:
        abort(404)

    # Redirect old-format URLs to the slug URL
    if author.get('slug') and author_slug != author['slug']:
        return redirect(url_for('author_papers', author_slug=author['slug'], page=page), code=301)

    # Get latest published date
    cursor.execute("SELECT MAX(published_date) as latest FROM papers")
    latest_date = cursor.fetchone()['latest']

    # Get total count
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM papers p
        JOIN paper_authors pa ON p.id = pa.paper_id
        WHERE pa.author_id = %s
    """, (author['id'],))
    total = cursor.fetchone()['count']

    # Get papers
    cursor.execute("""
        SELECT p.id, p.arxiv_id, p.title, p.abstract,
               p.published_date, p.updated_date, p.journal_ref, p.doi,
               p.comment, p.primary_category
        FROM papers p
        JOIN paper_authors pa ON p.id = pa.paper_id
        WHERE pa.author_id = %s
        ORDER BY p.published_date DESC, p.id DESC
        LIMIT %s OFFSET %s
    """, (author['id'], per_page, offset))

    papers = cursor.fetchall()

    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)

    cursor.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('author.html',
                         author=author,
                         papers=papers,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         latest_date=latest_date)


@app.route('/browse')
def browse_by_date():
    """Browse papers by calendar date."""
    year = request.args.get('year', datetime.now().year, type=int)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get paper counts by date for the year
    cursor.execute("""
        SELECT DATE(published_date) as date, COUNT(*) as count
        FROM papers
        WHERE YEAR(published_date) = %s
        GROUP BY DATE(published_date)
    """, (year,))

    date_counts = {row['date']: row['count'] for row in cursor.fetchall()}

    # Get available years with paper counts
    cursor.execute("""
        SELECT YEAR(published_date) as year, COUNT(*) as count
        FROM papers
        GROUP BY YEAR(published_date)
        ORDER BY year DESC
    """)
    available_years = [(row['year'], row['count']) for row in cursor.fetchall()]

    cursor.close()

    # Build calendar data for each month
    month_data = []
    month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']

    for month in range(1, 13):
        cal = calendar.monthcalendar(year, month)
        days = []
        for week in cal:
            for day in week:
                if day == 0:
                    days.append({'day': 0, 'count': 0})
                else:
                    date_obj = date(year, month, day)
                    count = date_counts.get(date_obj, 0)
                    days.append({
                        'day': day,
                        'count': count,
                        'date_str': f"{year:04d}-{month:02d}-{day:02d}"
                    })

        month_data.append({
            'name': month_names[month],
            'days': days
        })

    return render_template('browse.html',
                         year=year,
                         month_data=month_data,
                         available_years=available_years)


@app.route('/date/<date_str>')
def papers_by_date(date_str):
    """Show papers from a specific date."""
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        abort(404)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, arxiv_id, title, abstract, published_date, updated_date,
               journal_ref, doi, comment, primary_category
        FROM papers
        WHERE DATE(published_date) = %s
        ORDER BY id DESC
    """, (date,))

    papers = cursor.fetchall()

    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)

    cursor.close()

    return render_template('date.html',
                         date=date,
                         papers=papers)


@app.route('/random')
def random_paper():
    """Redirect to a random paper."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT arxiv_id FROM papers ORDER BY RAND() LIMIT 1")
    paper = cursor.fetchone()
    cursor.close()
    if not paper:
        abort(404)
    return redirect(url_for('paper_detail', arxiv_id=paper['arxiv_id']))


@app.route('/api/author-bibtex/<author_slug>')
def author_bibtex(author_slug):
    """Generate BibTeX for all papers by an author."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM authors WHERE slug = %s", (author_slug,))
    author = cursor.fetchone()
    if not author:
        cursor.execute("SELECT id, name FROM authors WHERE name = %s", (author_slug,))
        author = cursor.fetchone()
    if not author:
        abort(404)

    cursor.execute("""
        SELECT p.id, p.arxiv_id, p.title, p.published_date, p.journal_ref, p.doi
        FROM papers p
        JOIN paper_authors pa ON p.id = pa.paper_id
        WHERE pa.author_id = %s
        ORDER BY p.published_date DESC
    """, (author['id'],))

    papers = cursor.fetchall()
    attach_authors(cursor, papers)
    attach_keywords(cursor, papers)
    entries = []
    for paper in papers:
        # Always include arXiv entry
        entries.append(arxiv2bib(paper))
        # If published, also include the published entry
        if paper.get('doi'):
            pub_bib = doi2bib(paper['doi'], paper)
            if pub_bib:
                entries.append(pub_bib)

    cursor.close()

    bibtex_all = '\n\n'.join(entries)
    return bibtex_all, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/fetch')
def fetch_papers():
    """Fetch recent papers from arXiv. Requires secret key."""
    key = request.args.get('key', '')
    days = request.args.get('days', 1, type=int)

    if not FETCH_SECRET or key != FETCH_SECRET:
        logger.warning("Unauthorized /fetch attempt from %s", request.remote_addr)
        abort(403)

    # Cap days to prevent abuse
    days = min(days, 30)
    logger.info("/fetch triggered: days=%d from %s", days, request.remote_addr)

    from fetch_arxiv import fetch_recent_papers
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        fetch_recent_papers(days=days)

    return output.getvalue(), 200, {'Content-Type': 'text/plain; charset=utf-8'}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
