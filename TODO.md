# arXiv Combinatorics Browser — Feature TODO

---

## User Authentication

To enable cross-device list syncing (and any future personalisation), users need a
persistent identity. Two options suit an academic audience:

### Option A: ORCID login (recommended)

[ORCID](https://orcid.org) is the standard researcher identifier. Most active
combinatorialists already have one. The public API is free.

**Flow:**
1. User clicks "Sign in with ORCID"
2. Redirected to `orcid.org/oauth/authorize` with client_id + scope `openid`
3. After consent, redirected back with an auth code
4. Server exchanges code for tokens → receives the ORCID iD (`0000-0002-xxxx-xxxx`)
5. Store `orcid_id` in Flask session; use as user key in DB

**What you need:**
- Register app at <https://orcid.org/developer-tools> (free, instant)
- `ORCID_CLIENT_ID` + `ORCID_CLIENT_SECRET` in `.env`
- `Authlib` pip package (`pip install Authlib`)
- New DB table (see below)

---

### DB schema for auth + lists

```sql
CREATE TABLE users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    provider    ENUM('orcid', 'google') NOT NULL,
    provider_id VARCHAR(100) NOT NULL,        -- ORCID iD or Google sub
    display_name VARCHAR(255),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_provider (provider, provider_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE user_lists (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    list_name  VARCHAR(100) NOT NULL DEFAULT 'Favorites',
    arxiv_id   VARCHAR(20) NOT NULL,
    added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_user_list_paper (user_id, list_name, arxiv_id),
    INDEX idx_user_list (user_id, list_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### New routes

```
GET  /login                → show login options (ORCID / Google buttons)
GET  /login/orcid          → start ORCID OAuth flow
GET  /login/orcid/callback → handle redirect, create/update user, set session
GET  /logout               → clear session
GET  /lists                → show current user's lists (requires login)
POST /api/lists/toggle     → add/remove a paper from a list (JSON API)
POST /api/lists/rename     → rename a list
POST /api/lists/create     → create a new list
POST /api/lists/delete     → delete a list (and all its entries)
```

### Implementation notes

- Use `Authlib`'s Flask integration (`authlib.integrations.flask_client`)
- Store `user_id` in Flask session after login
- If not logged in: lists fall back to localStorage (same UX as unauthenticated)
- When user logs in: offer to merge localStorage lists into their account

---

## Paper Bookmarks / Personal Lists

Allow visitors to save papers into personal, named lists.

### Proposed UX

- Small bookmark button (☆) on each paper card, next to the existing #/INFO/BIB/PDF links
- Clicking opens a small dropdown to pick which list to add/remove from
- Default lists: **Favorites**, **To read**, **Relevant** — user can rename or add more
- A `/lists` page shows all saved papers grouped by list, with BibTeX export
- Lists are exportable as plain text (one arXiv ID per line) or JSON

### Storage strategy

**Without login:** `localStorage` (single device, no account needed)

```json
{
  "Favorites":  ["2401.12345", "2312.00001"],
  "To read":    ["2403.99999"]
}
```

**With login:** server-side in `user_lists` table (cross-device, persistent)

Both modes use the same JS API; the backend call either hits the server or
falls through to localStorage depending on session state.

### Integration points

- `_macros.html` `render_paper()` — add bookmark button to paper card
- `paper.html` — add bookmark button to detail page
- `base.html` nav — add "Lists" link (shows count badge if any saved)
- `utils.js` — `toggleBookmark(arxivId, listName)`, `getBookmarks()`, `initBookmarks()`

---

## Other Ideas

- **Abstract keyword linking** — wrap matched keyword phrases in abstracts with
  `<a href="keyword.url">` links at render time (for keywords that have a URL set).
  Would make abstracts navigable to the symmetricfunctions.com reference pages.

- **"Similar papers" section** — on the paper detail page, list papers sharing the
  most keyword tags (easy to query from `paper_keywords`).

- **Keyword cloud** — a `/keywords` page listing all active keywords sized by paper
  count, linking to their `/keyword/<phrase>` pages.
