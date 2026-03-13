# arXiv Combinatorics Browser — TODO

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

