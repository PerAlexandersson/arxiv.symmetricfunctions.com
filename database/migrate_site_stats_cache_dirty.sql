-- migrate_site_stats_cache_dirty.sql
-- Persist homepage cache-debounce state outside the Passenger process.

CREATE TABLE IF NOT EXISTS site_stats (
    id                  TINYINT NOT NULL DEFAULT 1,
    paper_count         INT     NOT NULL DEFAULT 0,
    author_count        INT     NOT NULL DEFAULT 0,
    latest_date         DATE,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    cache_dirty_at      DATETIME NULL DEFAULT NULL,
    cache_rebuild_after DATETIME NULL DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE site_stats
  ADD COLUMN IF NOT EXISTS cache_dirty_at DATETIME NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS cache_rebuild_after DATETIME NULL DEFAULT NULL;

INSERT IGNORE INTO site_stats (id, paper_count, author_count, latest_date)
SELECT 1, COUNT(*), (SELECT COUNT(*) FROM authors), MAX(published_date)
FROM papers;
