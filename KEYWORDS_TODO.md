# Keywords & Auto-Tagging — Status

## Data Model — DONE

### DB tables

```sql
CREATE TABLE keywords (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    phrase        VARCHAR(255) NOT NULL UNIQUE,
    score         INT NOT NULL DEFAULT 5,          -- personal interest weight, 1–10
    url           TEXT,                            -- link to symmetricfunctions.com (if any)
    tag_name      VARCHAR(255),                    -- display name (defaults to phrase)
    active        BOOL NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE keyword_aliases (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    keyword_id    INT NOT NULL,
    alias         VARCHAR(255) NOT NULL UNIQUE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
);

-- Junction table written by auto_tag.py
CREATE TABLE paper_keywords (
    paper_id   INT NOT NULL,
    keyword_id INT NOT NULL,
    PRIMARY KEY (paper_id, keyword_id),
    FOREIGN KEY (paper_id)   REFERENCES papers(id)   ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
);

-- Triage tables for candidate workflow
CREATE TABLE ignored_candidates ( id INT AUTO_INCREMENT PRIMARY KEY, phrase VARCHAR(255) NOT NULL UNIQUE );
CREATE TABLE math_words          ( id INT AUTO_INCREMENT PRIMARY KEY, phrase VARCHAR(255) NOT NULL UNIQUE );
```

`relevance_score` on `papers` was considered but not added; `paper_keywords` serves the same purpose via a JOIN.

---

## Components — Status

### ✅ 1. DB schema
All tables exist in `database/schema.sql` (full reset) and `database/migrate.sql` (safe, additive).

### ✅ 2. Auto-tagger — `src/auto_tag.py`
- Reads active keywords from DB
- Tokenizes title + abstract (via `extract_keywords.tokenize`)
- Writes matches to `paper_keywords`
- Supports `--all`, `--days N`, `--since YYYY-MM-DD`
- Run via `./tag_papers.sh` locally or `./sync_to_prod.sh` for production

### ✅ 3. Admin UI — `src/admin.py`
Password-protected via `ADMIN_PASSWORD` in `.env`.

| Route | Status |
|-------|--------|
| `/admin/candidates` | ✅ — triage CSV candidates (mark useful / math / ignore) |
| `/admin/keywords` | ✅ — list all useful keywords with paper count |
| `/admin/keywords/<id>/edit` | ✅ — edit phrase, score, url, tag_name |
| `/admin/keywords/<id>/delete` | ✅ |
| `/admin/keywords/bulk_delete` | ✅ |
| `/admin/keywords/<id>/score` | ✅ — inline score update (JSON API) |
| `/admin/retag` | ❌ — not yet; run `./tag_papers.sh --all` from CLI instead |

### ✅ 4. Keyword pages — `src/app.py` + `src/templates/keyword.html`
`/keyword/<phrase>` lists all papers tagged with a keyword, with optional `keyword.url` reference link.

### ✅ 5. Keyword tags on paper pages
Tags displayed on paper detail (`paper.html`) and paper cards (`_macros.html`).

### ❌ 6. Abstract keyword linking
At render time, wrap matched keyword phrases in `<a href="keyword.url">` for keywords that have a URL set.
Not yet implemented; keywords appear as tags only.

### ❌ 7. `src/import_keyword_urls.py`
Import a JSON map `{"phrase": "/url"}` exported from the symmetricfunctions.com build.
Blocked by: unclear build toolchain for that site.

---

## Open Questions

- [ ] Build tool for symmetricfunctions.com? (determines how easy the JSON export is)
- [ ] Should `/admin` be accessible on production, or local-only via SSH tunnel?
- [ ] Re-tag: add `/admin/retag` web route, or keep CLI-only?
