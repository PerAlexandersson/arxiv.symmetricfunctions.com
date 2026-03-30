# arXiv++ Combinatorics — TODO

---



## Comments on Preprints

Logged-in users can leave short comments on individual papers (visible to all visitors).

### Data model

```sql
CREATE TABLE paper_comments (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    paper_id   INT NOT NULL,
    user_id    INT NOT NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### UX

- Comment section at the bottom of each paper detail page (`paper.html`)
- Shows commenter's display name + date; no threading
- Edit/delete own comments; no moderation UI needed initially
- Comment count shown as a small badge on paper cards in browse view

### Routes

```
POST /api/comments/<arxiv_id>   → add comment (login required)
POST /api/comments/<id>/delete  → delete own comment
POST /api/comments/<id>/edit    → edit own comment body
```

---

## Other Ideas

- **"Similar papers" section** — on the paper detail page, list papers sharing the
  most keyword tags (easy to query from `paper_keywords`).

- **Abstract keyword linking** — hyperlink matched keyword phrases in abstracts
  to their `keyword.url` at render time.

- **`import_keyword_urls.py`** — import a `phrase → url` JSON map from the
  symmetricfunctions.com build to populate keyword URLs in bulk.

- **RSS/Atom feed** — subscribe to recent papers or specific keywords.

- **Drop legacy `tags` / `paper_tags` tables** — unused anywhere in the codebase.
  `tags` has 15 pre-seeded MSC codes, `paper_tags` is empty. Remove from `schema.sql`
  and write a `migrate_drop_legacy_tags.sql`.

---

## Completed

- ~~User authentication (ORCID login) + personal paper lists~~ — `auth.py`, `lists.py`
- ~~Keyword cloud (`/keywords` page)~~ — `keywords.html`
- ~~DOI discovery via Crossref API~~ — `doi_lookup.py`, `bib_doi_backfill.py`, `/admin/dois`
- ~~Watched keywords/authors + personalized feed~~ — `watch.py`, `feed.html`
- ~~Category browsing (`/category/<cat>`)~~ — `category.html`
