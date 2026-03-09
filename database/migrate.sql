-- migrate.sql — Safe migration: adds new tables without touching existing data.
-- Run this on production instead of schema.sql (which drops everything).
--
-- Usage (on prod via SSH):
--   mysql -u arxiv_user -p arxiv_frontend < database/migrate.sql

-- ============================================================================
-- Keywords Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS keywords (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    phrase    VARCHAR(255) NOT NULL,
    score     INT NOT NULL DEFAULT 5,
    url       TEXT,
    tag_name  VARCHAR(255),
    active    BOOLEAN NOT NULL DEFAULT 1,

    UNIQUE KEY idx_unique_phrase (phrase),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Keyword Aliases Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS keyword_aliases (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    keyword_id INT NOT NULL,
    alias      VARCHAR(255) NOT NULL,

    UNIQUE KEY idx_unique_alias (alias),
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Ignored Candidates Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS ignored_candidates (
    id     INT AUTO_INCREMENT PRIMARY KEY,
    phrase VARCHAR(255) NOT NULL,
    UNIQUE KEY idx_unique_phrase (phrase)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Math Words Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS math_words (
    id     INT AUTO_INCREMENT PRIMARY KEY,
    phrase VARCHAR(255) NOT NULL,
    UNIQUE KEY idx_unique_phrase (phrase)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Paper-Keywords Junction Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS paper_keywords (
    paper_id   INT NOT NULL,
    keyword_id INT NOT NULL,

    PRIMARY KEY (paper_id, keyword_id),
    KEY idx_keyword_id (keyword_id),

    FOREIGN KEY (paper_id)   REFERENCES papers(id)   ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
