-- Migration: add users and user_lists tables
-- Safe to run on an existing database (uses IF NOT EXISTS)
-- Run: mysql -u arxiv_user -p arxiv_frontend < database/migrate_users.sql

CREATE TABLE IF NOT EXISTS users (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    provider     ENUM('orcid', 'google') NOT NULL,
    provider_id  VARCHAR(100) NOT NULL,        -- ORCID iD or Google sub
    display_name VARCHAR(255),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_provider (provider, provider_id)
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
