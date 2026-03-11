-- migrate_lists.sql — Add user_categories table for "My Lists" feature.
-- Safe to re-run (IF NOT EXISTS).
--
-- user_lists already exists (from migrate_users.sql) and stores
-- (user_id, list_name, arxiv_id).  This migration adds a metadata table
-- for those lists so we can track is_starred, creation order, etc.
-- The two tables are joined on (user_id, list_name = name).
--
-- Usage (local):
--   mysql -u arxiv_user -p arxiv_frontend < database/migrate_lists.sql
-- Applied automatically by sync_to_prod.sh.

CREATE TABLE IF NOT EXISTS user_categories (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    name       VARCHAR(100) NOT NULL,
    is_starred TINYINT(1)   NOT NULL DEFAULT 0,
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY idx_user_cat_name (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
