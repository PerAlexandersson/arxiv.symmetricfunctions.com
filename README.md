# arXiv Combinatorics Frontend

A web interface for browsing arXiv papers in combinatorics (math.CO category).

Built with [Claude Code](https://claude.ai/claude-code).

**Tech stack:** Python 3 / Flask, MariaDB, plain HTML/CSS/JS, arXiv API.

**Features:** Browse papers, search by author/title, one-click BibTeX export, KaTeX math rendering, keyword tagging with admin UI.

---

## Quick Setup

### 1. Install Python Dependencies

```bash
./setup_venv.sh
```

This script will:
- Create a machine-local virtual environment
- Install all required Python dependencies
- Skip setup if already configured and working

**Manual setup (alternative):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create Environment File

**IMPORTANT:** Never commit passwords to git!

```bash
# Copy the example file
cp .env.example .env

# Edit .env and set your actual password
nano .env  # or use your preferred editor
```

Your `.env` file should contain:
```
DB_HOST=localhost
DB_USER=arxiv_user
DB_PASSWORD=your_actual_password_here
DB_NAME=arxiv_frontend
DB_CHARSET=utf8mb4
```

The `.env` file is in `.gitignore` and will NOT be committed to git.

### 3. Setup Database

```bash
cd database
chmod +x setup_database.sh
./setup_database.sh
```

This will:
- Install MariaDB (if needed)
- Create database `arxiv_frontend`
- Create user `arxiv_user` with password from `.env`
- Import schema from `schema.sql`

### 4. Fetch Papers

```bash
cd ../src
source ../venv/bin/activate

# Test with a single paper
python3 fetch_arxiv.py --arxiv-id 2401.12345

# Fetch recent papers (last 7 days)
python3 fetch_arxiv.py --recent --days 7

# Backfill historical data (optional)
python3 fetch_arxiv.py --backfill --start-date 2024-01-01 --end-date 2024-12-31
```

### 5. Run the Web Interface

```bash
cd ../src
source ../venv/bin/activate
python3 app.py
```

Then visit **http://localhost:5000** in your browser.

---

## Web Interface Features

- **Browse papers** - Paginated list sorted by publication date
- **Search** - Search by title, author, or abstract
- **Author pages** - View all papers by a specific author
- **Keyword pages** - `/keyword/<phrase>` lists all papers tagged with a keyword
- **BibTeX export** - One-click copy/download for citations
- **Math rendering** - KaTeX support for LaTeX in titles and abstracts

---

## Daily Updates (Cron Job)

To automatically fetch new papers daily:

```bash
crontab -e
```

Add this line (adjust the path to match your setup):
```
0 2 * * * cd /path/to/arxiv.symmetricfunctions.com/src && source ../venv/bin/activate && python3 fetch_arxiv.py --recent --days 2 >> ~/arxiv_fetch.log 2>&1
```

Alternatively, trigger a fetch via HTTP (useful on shared hosting without cron access):

```
GET /fetch?key=<FETCH_SECRET>&days=2
```

Set `FETCH_SECRET` in `.env`. Returns plain-text fetch output.

---

## Database Access

Connect to the database:

```bash
mysql -u arxiv_user -p arxiv_frontend
```

Useful queries:

```sql
-- Count total papers
SELECT COUNT(*) FROM papers;

-- Recent papers
SELECT arxiv_id, title, published_date
FROM papers
ORDER BY published_date DESC
LIMIT 10;

-- Papers by year
SELECT YEAR(published_date) as year, COUNT(*) as count
FROM papers
GROUP BY YEAR(published_date)
ORDER BY year DESC;

-- Most prolific authors
SELECT a.name, COUNT(*) as paper_count
FROM authors a
JOIN paper_authors pa ON a.id = pa.author_id
GROUP BY a.name
ORDER BY paper_count DESC
LIMIT 10;
```

---

## Project Structure

```
arxiv.symmetricfunctions.com/
├── .env.example              # Template for environment variables
├── requirements.txt          # Python dependencies
├── setup_venv.sh             # Virtual environment setup
├── activate_venv.sh          # Source to activate venv
├── run_app.sh                # Start the Flask dev server
├── fetch_papers.sh           # Fetch papers from arXiv
├── passenger_wsgi.py         # WSGI entry point (shared hosting)
├── database/
│   ├── schema.sql            # Database schema
│   ├── setup_database.sh     # Database setup script
│   ├── pull_prod_db.sh       # Pull production DB to local
│   ├── migrate.sql           # Migrations (run in order)
│   └── drop_tag_name.sql     # Migration: remove tag_name column
└── src/
    ├── app.py                # Flask web application
    ├── admin.py              # Admin blueprint (keyword management)
    ├── config.py             # Configuration loader
    ├── fetch_arxiv.py        # arXiv fetching script
    ├── auto_tag.py           # Tag papers with curated keywords
    ├── extract_keywords.py   # Extract keyword candidates from corpus
    ├── utils.py              # Shared utilities (slugify, etc.)
    ├── static/
    │   ├── style.css         # Stylesheet
    │   └── utils.js          # Client-side utilities
    └── templates/
        ├── base.html         # Base template with KaTeX + Ko-fi donate widget
        ├── _macros.html      # Reusable template macros
        ├── index.html        # Homepage
        ├── paper.html        # Paper details (with keyword tags)
        ├── author.html       # Author page
        ├── keyword.html      # Papers by keyword
        ├── authors.html      # Author list
        ├── search.html       # Search results
        ├── browse.html       # Calendar browse
        ├── date.html         # Papers by date
        ├── tools.html        # BibTeX tools
        └── admin/
            ├── login.html        # Admin login
            ├── candidates.html   # Keyword candidate triage
            ├── keywords.html     # Curated keyword list (inline-edit, merge, aliases)
            └── retag.html        # Retag papers by date range
```

**Note:** The `venv/` directory is machine-local and not included in the repository.

---

## Troubleshooting

**"DB_PASSWORD not set in environment variables"**
- Create `.env` file: `cp .env.example .env`
- Edit `.env` and set your password
- Test: `cd src && python3 config.py`

**"Access denied for user"**
- Verify password in `.env` matches database setup
- Test connection: `mysql -u arxiv_user -p arxiv_frontend`

**"No module named 'arxiv'"**
- Activate virtual environment: `source venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

**"Connection refused"**
- Check MariaDB is running: `systemctl status mariadb`
- Start if needed: `sudo systemctl start mariadb`

**"Port 5000 already in use"**
- Stop other Flask apps or change port in `src/app.py`

**Different paper counts / keyword changes not visible on other machine**
- Pull the production database locally: `cd database && ./pull_prod_db.sh`
- Then apply any pending migrations (e.g. `drop_tag_name.sql`)

---

## Keyword Tagging System

Papers are auto-tagged with curated keywords managed via the admin UI at `/admin`.

### Admin UI

Password-protected (set `ADMIN_PASSWORD` in `.env`).

- `/admin/candidates` — triage keyword candidates from `keywords.csv` (mark as *useful*, *math*, or *ignore*)
- `/admin/keywords` — list/edit/delete curated keywords; inline-edit phrase, URL, score; manage aliases (synonyms); merge two keywords; paper count per keyword
- `/admin/retag` — re-tag papers by date range directly from the browser

### Keyword pipeline

```
extract_keywords.py → keywords.csv → /admin/candidates → DB keywords table → auto_tag.py
```

1. Run `extract_keywords.py` locally to scan all abstracts and produce `keywords.csv`
2. Triage candidates in `/admin/candidates`; *useful* phrases go into the `keywords` DB table
3. `auto_tag.py` (or `/admin/retag`) applies active keywords + aliases to papers
4. `fetch_arxiv.py` auto-tags new papers on every fetch

**Run auto-tagger manually:**

```bash
cd src && source ../venv/bin/activate
python3 auto_tag.py               # last 180 days (default)
python3 auto_tag.py --days 30
python3 auto_tag.py --since 2025-01-01
python3 auto_tag.py --all         # all papers (slow)
```

**Refresh keyword candidates** (after many new papers):

```bash
python3 extract_keywords.py       # outputs keywords.csv
# then redeploy to update /admin/candidates
```

---

## Database Design

See `database/schema.sql` for the complete schema.

- **`papers`** — Main paper metadata (arxiv_id, title, abstract, dates)
- **`authors`** — Author names (normalized, no duplicates)
- **`paper_authors`** — Many-to-many junction table
- **`keywords`** — Curated keyword phrases with relevance scores and optional URLs
- **`keyword_aliases`** — Alternative phrasings mapping to a keyword
- **`paper_keywords`** — Auto-generated by `auto_tag.py`; links papers to matched keywords
- **`ignored_candidates`** — Phrases marked as non-math/typos (excluded from candidate view)
- **`math_words`** — Valid math terms too broad to tag on their own
- **`tags`** / **`paper_tags`** — legacy MSC-code tag system (unused)

---

## Future Ideas

See `TODO.md` for the full roadmap. Short list:

- **Abstract keyword linking** — hyperlink matched phrases in abstracts to their `keyword.url` at render time
- **`import_keyword_urls.py`** — import a `phrase → url` JSON map from the symmetricfunctions.com build
- **User authentication** (ORCID or Google) + personal paper lists
- **RSS/Atom feed** for recent papers
- **"Similar papers"** section on paper detail (papers sharing the most keyword tags)
- **Keyword cloud** — `/keywords` page with all active keywords sized by paper count