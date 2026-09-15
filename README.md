# arXiv++ Combinatorics

A web interface for browsing arXiv papers in combinatorics (math.CO category), with DOI discovery, keyword tagging, and more.

Live at **https://arxiv.symmetricfunctions.com**. Built with [Claude Code](https://claude.ai/claude-code).

**Tech stack:** Python 3 / Flask, MariaDB, plain HTML/CSS/JS, arXiv API, Crossref API, ORCID OAuth.

**Features:** Browse papers, search by author/title/keyword, one-click BibTeX export, KaTeX math rendering, keyword tagging with admin UI, DOI discovery via Crossref, ORCID login with personal paper lists and personalized feeds.

The repository also provides a public read-only REST API and an optional MCP
server for agent-assisted literature review.

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

# Resume from the newest publication date already stored (inclusive)
python3 fetch_arxiv.py --recent

# Optional explicit rolling-window override
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

### Public

- **Browse papers** — Paginated list sorted by publication date (homepage cached for anonymous visitors)
- **Search** — Full-text search by title, author, or abstract with keyword scoring
- **Author pages** — `/author/<slug>` lists all papers by a specific author; `/authors` shows prolific authors
- **Keyword pages** — `/keyword/<phrase>` lists all papers tagged with a keyword
- **Keyword cloud** — `/keywords` page with all active keywords sized by paper count
- **Category browsing** — `/category/<cat>` lists papers by arXiv subject category (e.g. math.CO, cs.DM)
- **Calendar browse** — `/browse` shows a month calendar; click a date to see that day's papers
- **Random paper** — `/random` redirects to a random paper
- **BibTeX export** — One-click copy/download for arXiv and published (DOI) citations
- **BibTeX tools** — `/tools` generates BibTeX from arbitrary arXiv IDs or DOIs
- **Math rendering** — KaTeX support for LaTeX in titles and abstracts
- **DOI and journal info** — Papers show DOI links and journal references when available

### Authenticated (ORCID login)

- **My Feed** — `/my-feed` shows recent papers matching watched keywords and authors
- **Watch keywords / authors** — Follow topics or researchers to build a personalized feed
- **My Lists** — `/lists` lets users organize papers into custom named lists
  (plus a special "Starred" list); the paper menu shows and toggles existing
  memberships

---

## Daily Updates (Cron Job)

To fetch after each Tuesday-Saturday arXiv announcement:

```bash
crontab -e
```

Add this line (adjust the path to match your setup):
```
30 6 * * 2-6 ARXIV_VENV=/path/to/venv /path/to/arxiv.symmetricfunctions.com/cron_update.sh
```

Routine fetches derive an inclusive checkpoint from the newest publication
date in the database, so interrupted or rate-limited runs catch up without a
manually chosen lookback. They use arXiv OAI-PMH first, retain the Atom API as a
fallback, and compare the result with the current math.CO RSS announcement.

Alternatively, trigger a fetch via HTTP (useful on shared hosting without cron access):

```
curl -X POST -H "X-Fetch-Secret: <FETCH_SECRET>" -F days=2 \
  https://arxiv.symmetricfunctions.com/fetch
```

Set `FETCH_SECRET` in `.env`. The endpoint returns plain-text fetch output.

---

## REST API

The versioned API is rooted at:

```text
https://arxiv.symmetricfunctions.com/api/v1/
```

Useful endpoints include:

```text
GET /api/v1/status
GET /api/v1/papers?published_after=2026-08-01&published_before=2026-08-07&order=published
GET /api/v1/papers?category=math.CO&category=math.AG&order=published
GET /api/v1/papers?keyword=schur%20functions
GET /api/v1/papers?q=chromatic%20symmetric
GET /api/v1/papers/2608.12345
GET /api/v1/keywords
GET /api/v1/openapi.yaml
```

Paper lists use opaque keyset cursors. Pass `next_cursor` back as the `cursor`
parameter rather than constructing it yourself. Page size is capped at 100.
Publication-date bounds are inclusive. Repeat `category` to match any of
several categories; cursor requests must repeat the same filters.
The response distinguishes the stable base `arxiv_id` from the current
`versioned_arxiv_id`, so revisions do not appear as new logical papers.

Before deploying the API code to an existing database, back up the database.
If the installation still has the legacy `user_lists(user_id, list_name,
arxiv_id)` schema, apply the saved-list migration first:

```bash
mysql -u arxiv_user -p arxiv_frontend \
  < database/migrate_normalize_user_lists.sql
```

Then apply the identity migration:

```bash
mysql -u arxiv_user -p arxiv_frontend \
  < database/migrate_arxiv_identity.sql
```

The list migration replaces name-based saved-list references with foreign keys to
`user_categories.id` and `papers.id`. It aborts if any legacy row cannot be
mapped and retains the verified old table as `user_lists_legacy_20260915` for
the deployment checkpoint. Drop that backup table only after the new code and
saved-list counts have been verified. The identity migration then retains the
newest revision's arXiv metadata and author/category sets, carries forward
editorial metadata and manual/system keywords, and preserves saved-list
entries. `sync_to_prod.sh` does not run database migrations automatically and
will refuse this application version until it detects the normalized list
schema.

---

## MCP Server

The optional MCP adapter lives in this repository but runs separately from the
Python 3.9 Passenger application. It requires Python 3.10 or newer:

```bash
python3 -m venv ~/.cache/arxiv-mcp-venv
source ~/.cache/arxiv-mcp-venv/bin/activate
pip install -r requirements-mcp.txt
python -m mcp_server.server
```

The default stdio server exposes these read-only tools:

- `get_status`
- `list_recent_papers`
- `search_papers`
- `get_paper`
- `list_keywords`

It also provides a `review_recent_papers` prompt. Point it at another API
deployment by setting `ARXIV_API_BASE_URL`, for example:

```bash
ARXIV_API_BASE_URL=http://127.0.0.1:5000/api/v1 \
  python -m mcp_server.server
```

For a remotely reachable MCP endpoint, use Streamable HTTP:

```bash
python -m mcp_server.server --transport streamable-http \
  --host 127.0.0.1 --port 8000
```

The MCP process only calls the REST API; it does not need database or website
credentials. Recommendations remain editorial suggestions and do not modify
`symmetricfunctions.com`.

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
├── tag_papers.sh             # Run auto-tagger
├── find_dois.sh              # Run DOI lookup
├── batch_doi_lookup.sh       # Batch DOI lookup (date range, configurable)
├── sync_to_prod.sh           # Deploy code/config to production (no DB changes)
├── backfill_production.sh    # Backfill papers on production
├── use_local.sh              # Switch .env to local development
├── passenger_wsgi.py         # WSGI entry point (shared hosting)
├── CRONJOBS.md               # Production cron job schedule
├── database/
│   ├── schema.sql            # Database schema (fresh install only)
│   ├── setup_database.sh     # Database setup script
│   ├── reset_database.sh     # Nuke and recreate database
│   ├── pull_prod_db.sh       # Pull production DB to local
│   ├── migrate_doi_status.sql    # Migration: add DOI status tracking
│   ├── migrate_doi_checked.sql   # Migration: add DOI lookup timestamp
│   ├── migrate_doi_skipped.sql   # Migration: add 'skipped' DOI status
│   └── migrate_normalize_user_lists.sql # Stable list/category relationships
├── deployment/
│   ├── QUICKSTART.md         # Quick deployment guide
│   ├── SETUP_STEPS.md        # Detailed setup instructions
│   ├── SHARED_HOSTING.md     # Passenger/cPanel deployment docs
│   ├── CHECKLIST.md          # Pre-deployment checklist
│   ├── deploy_shared.sh      # Deployment script for shared hosting
│   ├── htaccess_template     # Deploy-time template for .htaccess
│   └── static_htaccess       # Static files .htaccess
└── src/
    ├── app.py                # Flask web application (main routes)
    ├── admin.py              # Admin blueprint (keyword/DOI management)
    ├── auth.py               # ORCID OAuth authentication
    ├── lists.py              # User saved-paper lists blueprint
    ├── watch.py              # Watched keywords/authors feed blueprint
    ├── config.py             # Configuration loader
    ├── db.py                 # Shared database helpers
    ├── fetch_arxiv.py        # arXiv paper fetching script
    ├── auto_tag.py           # Tag papers with curated keywords
    ├── extract_keywords.py   # Extract keyword candidates from corpus
    ├── doi_lookup.py         # Find DOIs via Crossref API
    ├── bib_doi_backfill.py   # Backfill missing DOIs in bulk
    ├── utils.py              # Shared utilities (slugify, BibTeX, etc.)
    ├── static/
    │   ├── style.css         # Stylesheet
    │   └── utils.js          # Client-side utilities
    └── templates/
        ├── base.html         # Base template with KaTeX + Ko-fi donate widget
        ├── _macros.html      # Reusable template macros
        ├── index.html        # Homepage (recent papers)
        ├── paper.html        # Paper details (keywords, DOI, BibTeX)
        ├── author.html       # Author page
        ├── authors.html      # Prolific authors list
        ├── keyword.html      # Papers by keyword
        ├── keywords.html     # Keyword cloud
        ├── category.html     # Papers by arXiv category
        ├── search.html       # Search results
        ├── browse.html       # Calendar browse
        ├── date.html         # Papers by date
        ├── tools.html        # BibTeX tools
        ├── login.html        # ORCID login page
        ├── feed.html         # Personalized feed (My Feed)
        ├── lists.html        # User saved lists overview
        ├── list_detail.html  # Papers in a specific list
        └── admin/
            ├── _nav.html         # Admin navigation
            ├── login.html        # Admin login
            ├── candidates.html   # Keyword candidate triage
            ├── keywords.html     # Curated keyword list (inline-edit, merge, aliases)
            ├── retag.html        # Retag papers by date range
            ├── dois.html         # DOI candidate review
            ├── fetch.html        # Trigger paper fetch
            ├── users.html        # User management
            └── symcat.html       # Category management
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
- Then apply any pending migrations (see `database/migrate_*.sql`)

**Changing the production Python runtime**

- The interpreter is selected by cPanel's application configuration and the
  generated `PassengerPython` directive.
- Create/select a supported Python virtualenv in cPanel first, then deploy with
  `ARXIV_PYTHON_VERSION=<major.minor>`.
- `passenger_wsgi.py` intentionally does not inject a version-specific
  `site-packages` directory; Passenger's selected interpreter owns that path.

---

## Keyword Tagging System

Papers are auto-tagged with curated keywords managed via the admin UI at `/admin`.

### Admin UI

Password-protected (set `ADMIN_PASSWORD` in `.env`) or auto-granted via `ADMIN_ORCID`.

- `/admin/candidates` — triage keyword candidates from `keywords.csv` (mark as *useful*, *math*, or *ignore*)
- `/admin/keywords` — list/edit/delete curated keywords; inline-edit phrase, URL, score; manage aliases (synonyms); merge two keywords; paper count per keyword
- `/admin/retag` — re-tag papers by date range directly from the browser
- `/admin/dois` — review DOI candidates found by Crossref lookup (approve/reject)
- `/admin/fetch` — trigger paper fetch from the browser
- `/admin/users` — view registered users

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

## DOI Discovery

Papers that arrive without a DOI can have one found automatically via the Crossref API.

```bash
# Interactive batch lookup (recommended)
./batch_doi_lookup.sh                      # 500 papers before 2023
./batch_doi_lookup.sh 500 0.90 2020-01-01  # custom: batch, threshold, start date

# Merge production DOI review state into local without replacing
# local-only DOI lookup results
cd database && ./merge_prod_doi_state.sh          # dry run
cd database && ./merge_prod_doi_state.sh --apply  # apply

# Push a reviewed local DOI state to production without replacing newer papers.
# Plan generation is read-only and requires a fresh verified production backup.
python3 database/push_local_doi_state.py \
  --local-host db --plan /secure/path/doi-plan.json \
  --backup /secure/path/fresh-production.sql.gz
python3 database/push_local_doi_state.py \
  --local-host db --plan /secure/path/doi-plan.json --rollback-test
python3 database/push_local_doi_state.py \
  --local-host db --plan /secure/path/doi-plan.json --apply

# Or directly
cd src && source ../venv/bin/activate
python3 doi_lookup.py --batch 250 --auto-approve 0.95
python3 bib_doi_backfill.py /path/to/file.bib   # bulk backfill from .bib file
```

- Routine matches at least 95% are auto-approved; lower-confidence matches at
  least 60% are staged for review, while weaker results are not staged. The
  CLI threshold remains configurable.
- 61-89% go to `/admin/dois` for manual review
- Admin UI has date range controls; defaults to 1 year ago → today
- Admin can manually set DOIs on individual paper pages
- Papers that predate their Crossref match are automatically filtered out
- DOI provenance: `arxiv` (from arXiv metadata), `auto` (Crossref match), `verified` (admin-approved), `skipped` (unlikely to ever get a DOI)
- `doi_checked_at` tracks when each paper was last queried (skipped for 180 days)
- Routine discovery waits until a preprint is at least 180 days old and takes
  the top 250 due papers. Priority order is: journal reference present,
  never-checked papers aged 6--24 months, older never-checked papers, then due
  rechecks. Explicit CLI date filters can still narrow a recovery batch.
- Crossref request failures do not update `doi_checked_at`; the paper remains
  eligible for the next run, and the DOI command exits nonzero after preserving
  any successful results from the same batch.
- Admin pages show a compact action banner for failed/stale cron runs, skipped
  DOI scans, pending DOI matches, and a large automated-check backlog. The
  backlog warning defaults to 1,000 eligible papers and can be changed with
  `DOI_BACKLOG_WARNING` in the web process environment.

---

## Database Design

See `database/schema.sql` for the complete schema.

**Core tables:**

- **`papers`** — Paper metadata (arxiv_id, title, abstract, dates, DOI, journal_ref, doi_status/confidence/checked_at)
- **`authors`** — Author names with URL slugs (deduplicated)
- **`paper_authors`** — Many-to-many junction with author ordering
- **`paper_categories`** — arXiv subject categories per paper (primary + cross-listings)

**Keyword system:**

- **`keywords`** — Curated keyword phrases with relevance scores and optional URLs
- **`keyword_aliases`** — Alternative phrasings mapping to a keyword
- **`paper_keywords`** — Auto-generated by `auto_tag.py`; links papers to matched keywords
- **`ignored_candidates`** — Phrases marked as non-math/typos (excluded from candidate view)
- **`math_words`** — Valid math terms too broad to tag on their own

**DOI discovery:**

- **`doi_candidates`** — Crossref lookup staging table (pending/approved/rejected)

**User/personalization:**

- **`users`** — Authenticated users (ORCID login)
- **`user_categories`** — Named list buckets per user (includes special "Starred" list)
- **`user_lists`** — Memberships linking `user_categories.id` to stable
  `papers.id` values, with cascading cleanup
- **`user_watched_keywords`** — Keywords a user follows (powers "My Feed")
- **`user_watched_authors`** — Authors a user follows (powers "My Feed")

**Legacy:**

- **`tags`** / **`paper_tags`** — MSC-code tag system (unused, kept for compatibility)

---

## Future Ideas

See `TODO.md` for the full roadmap. Short list:

- **Comments on preprints** — logged-in users leave short comments on papers
- **Abstract keyword linking** — hyperlink matched phrases in abstracts to their `keyword.url` at render time
- **`import_keyword_urls.py`** — import a `phrase → url` JSON map from the symmetricfunctions.com build
- **RSS/Atom feed** for recent papers
- **"Similar papers"** section on paper detail (papers sharing the most keyword tags)
