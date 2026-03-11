-- migrate_watched.sql — Add watched keywords and authors tables.
-- Safe to re-run (IF NOT EXISTS).
--
-- Usage (local):
--   mysql -u arxiv_user -p arxiv_frontend < database/migrate_watched.sql
-- Applied automatically by sync_to_prod.sh.

CREATE TABLE IF NOT EXISTS user_watched_keywords (
    user_id    INT NOT NULL,
    keyword_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, keyword_id),
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_watched_authors (
    user_id   INT NOT NULL,
    author_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, author_id),
    FOREIGN KEY (user_id)   REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors(id)  ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
