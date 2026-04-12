-- Migration: add user/personalization tables used by auth, lists, and feed
-- Safe to run on an existing database (uses IF NOT EXISTS and additive backfills)
-- Run: mysql -u arxiv_user -p arxiv_frontend < database/migrate_users.sql

CREATE TABLE IF NOT EXISTS users (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    provider     ENUM('orcid', 'google') NOT NULL,
    provider_id  VARCHAR(100) NOT NULL,        -- ORCID iD or Google sub
    display_name VARCHAR(255),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_provider (provider, provider_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_categories (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    name       VARCHAR(100) NOT NULL,
    is_starred TINYINT(1)   NOT NULL DEFAULT 0,
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_user_cat_name (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_watched_keywords (
    user_id    INT NOT NULL,
    keyword_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, keyword_id),
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_watched_authors (
    user_id    INT NOT NULL,
    author_id  INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, author_id),
    FOREIGN KEY (user_id)   REFERENCES users(id)   ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_lists (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    list_name  VARCHAR(100) NOT NULL DEFAULT 'Favorites',
    arxiv_id   VARCHAR(20) NOT NULL,
    added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_user_list_paper (user_id, list_name, arxiv_id),
    INDEX idx_user_list (user_id, list_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Backfill list categories for installs that previously only had user_lists.
INSERT INTO user_categories (user_id, name, is_starred)
SELECT DISTINCT ul.user_id,
       ul.list_name,
       CASE WHEN ul.list_name = 'Starred' THEN 1 ELSE 0 END
FROM user_lists ul
LEFT JOIN user_categories uc
       ON uc.user_id = ul.user_id AND uc.name = ul.list_name
WHERE uc.id IS NULL;
