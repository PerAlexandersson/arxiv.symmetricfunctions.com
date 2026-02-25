# Keywords & Auto-Tagging — Plan

## Goals

1. **Auto-tag papers** based on a curated keyword list
2. **Score papers** by personal interest (weighted keyword matches, stored in DB)
3. **Link keywords** in abstracts to pages on symmetricfunctions.com

---

## Data Model

### New DB tables

```sql
CREATE TABLE keywords (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    phrase        VARCHAR(255) NOT NULL UNIQUE,  -- canonical form, e.g. "schur function"
    score         INT NOT NULL DEFAULT 1,         -- personal interest weight, 1–10
    url           VARCHAR(500),                   -- link to symmetricfunctions.com (if any)
    tag_name      VARCHAR(255),                   -- tag to apply (defaults to phrase)
    active        BOOL NOT NULL DEFAULT TRUE,     -- disable without deleting
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE keyword_aliases (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    keyword_id    INT NOT NULL,
    alias         VARCHAR(255) NOT NULL,          -- e.g. "schur polynomial", "s-function"
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
);
```

### Modify papers table

```sql
ALTER TABLE papers ADD COLUMN relevance_score INT NOT NULL DEFAULT 0;
```

Score = sum of `keywords.score` for all keywords matched in title+abstract.
Cached in DB (depends on personal preferences, not recomputable from content alone).

---

## Components to Build

### 1. DB schema migration
Apply the above schema changes to both local and production databases.

### 2. Auto-tagger script (`src/auto_tag.py`)
- Reads all active keywords + aliases from DB
- Scans papers (title + abstract) using same tokenization as `extract_keywords.py`
  (strip LaTeX, lowercase, singularize, match n-grams)
- For each match: insert into `paper_tags`, accumulate score
- Writes final `relevance_score` to `papers` table
- Supports full re-scan or incremental (new/unscored papers only)

### 3. symmetricfunctions.com keyword map import (`src/import_keyword_urls.py`)
- symmetricfunctions.com build (from .tex files) exports a JSON file:
  ```json
  {"schur function": "/sf.htm#schur", "hall-littlewood": "/hl.htm", ...}
  ```
- Import script reads this JSON and updates `keywords.url` for matching phrases
- The two sites stay fully decoupled; run this script after rebuilding the wiki

### 4. Admin UI (Flask blueprint, `/admin`)
Password-protected via `ADMIN_PASSWORD` in `.env`.

Pages:
- `/admin/keywords` — list all keywords (phrase, score, url, alias count, paper count)
  - Add new keyword
  - Quick-edit score inline
  - Delete / deactivate
- `/admin/keywords/<id>` — edit single keyword: phrase, score, url, tag_name, aliases
- `/admin/retag` — trigger full auto-tagger run, show progress/summary
- (Future) `/admin/papers` — browse papers sorted by relevance score

### 5. Abstract keyword linking (template rendering)
- At display time in `paper.html` (and anywhere else abstracts are shown),
  post-process abstract text to wrap matched keywords in `<a href="...">` links
- Only link keywords that have a `url` set
- Should be done at render time (not stored in DB), so URL changes propagate automatically

---

## Notes on keyword curation

- The `keywords` table is hand-curated (~50–200 entries), not auto-populated
- Use `keywords.csv` and `keywords_multiword.csv` (from `extract_keywords.py`) as
  inspiration/discovery aids only
- Single-word keywords are fine (e.g. `matroid`, `quasisymmetric`, `tableau`)
- Multi-word phrases have more false positives in extraction, but are fine in the
  curated list (e.g. `hall-littlewood polynomial`, `symmetric group`)
- Score guidelines (suggested):
  - 10 — core topic (symmetric functions, Schur functions, etc.)
  - 7  — closely related (matroids, tableaux, RSK, etc.)
  - 5  — interesting but broader (polytopes, Coxeter groups, etc.)
  - 3  — tangentially relevant
  - 1  — general combinatorics (graph coloring, posets, etc.)

---

## Open Questions

- [ ] What is the exact build tool for symmetricfunctions.com? (custom Python/Perl, Sphinx, other?)
      → determines how easy the JSON export is to add
- [ ] Should `/admin` be accessible on production, or local-only?
- [ ] Re-tag trigger: manual (admin button) only for now, or also nightly cron?
