-- migrate_publication_metadata.sql
-- Add publication metadata separate from DOI plus durable manual keyword links.

ALTER TABLE papers
  ADD COLUMN IF NOT EXISTS publication_url VARCHAR(512) NULL AFTER doi_checked_at,
  ADD COLUMN IF NOT EXISTS publication_venue_key VARCHAR(64) NULL AFTER publication_url,
  ADD COLUMN IF NOT EXISTS publication_status
    ENUM('published','known_no_doi','arxiv_only') NULL AFTER publication_venue_key,
  ADD COLUMN IF NOT EXISTS editor_note TEXT NULL AFTER publication_status;

ALTER TABLE papers
  ADD INDEX IF NOT EXISTS idx_publication_status (publication_status),
  ADD INDEX IF NOT EXISTS idx_publication_venue_key (publication_venue_key);

UPDATE papers
SET publication_status = 'published'
WHERE doi IS NOT NULL
  AND publication_status IS NULL;

ALTER TABLE paper_keywords
  ADD COLUMN IF NOT EXISTS source
    ENUM('auto','manual','system') NOT NULL DEFAULT 'auto' AFTER keyword_id;
