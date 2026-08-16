-- Normalize arXiv paper identity while preserving the latest stored revision.
--
-- Safe to re-run on MariaDB.  Back up the database before applying migrations.
-- This migration merges relationships from duplicate vN rows into the newest
-- row for each base arXiv ID, then enforces one row per logical paper.

ALTER TABLE papers
  ADD COLUMN IF NOT EXISTS arxiv_base_id VARCHAR(20) NULL AFTER arxiv_id,
  ADD COLUMN IF NOT EXISTS arxiv_version SMALLINT UNSIGNED NOT NULL DEFAULT 1
    AFTER arxiv_base_id;

UPDATE papers
SET arxiv_base_id = REGEXP_REPLACE(arxiv_id, 'v[0-9]+$', ''),
    arxiv_version = CASE
      WHEN arxiv_id REGEXP 'v[0-9]+$'
      THEN CAST(REGEXP_REPLACE(arxiv_id, '^.*v([0-9]+)$', '\\1') AS UNSIGNED)
      ELSE 1
    END
WHERE arxiv_base_id IS NULL OR arxiv_base_id = '';

-- This lookup index keeps the one-time identity merge linear. It is removed
-- after the final unique base-ID index has been created.
ALTER TABLE papers
  ADD INDEX IF NOT EXISTS idx_arxiv_base_migration (arxiv_base_id);

DROP TEMPORARY TABLE IF EXISTS paper_identity_map;
DROP TEMPORARY TABLE IF EXISTS paper_identity_keep;
CREATE TEMPORARY TABLE paper_identity_keep (
    base_id VARCHAR(20) NOT NULL PRIMARY KEY,
    keep_id INT NOT NULL UNIQUE
);
INSERT INTO paper_identity_keep (base_id, keep_id)
SELECT arxiv_base_id,
       CAST(SUBSTRING_INDEX(
         GROUP_CONCAT(
           id ORDER BY COALESCE(updated_date, published_date) DESC, id DESC
         ),
         ',', 1
       ) AS UNSIGNED)
FROM papers
GROUP BY arxiv_base_id;

CREATE TEMPORARY TABLE paper_identity_map (
    old_id INT NOT NULL PRIMARY KEY,
    keep_id INT NOT NULL,
    base_id VARCHAR(20) NOT NULL,
    INDEX idx_keep_id (keep_id)
);
INSERT INTO paper_identity_map (old_id, keep_id, base_id)
SELECT p.id, identity.keep_id, p.arxiv_base_id
FROM papers p
JOIN paper_identity_keep identity ON identity.base_id = p.arxiv_base_id;

-- Preserve paper-level enrichment that may have been attached to an older
-- revision row (for example, a manually verified DOI or editor note).
DROP TEMPORARY TABLE IF EXISTS paper_metadata_merge;
CREATE TEMPORARY TABLE paper_metadata_merge AS
SELECT m.keep_id,
       MIN(p.created_at) AS first_created_at,
       MAX(p.updated_at) AS last_changed_at,
       MAX(NULLIF(p.doi, '')) AS doi,
       CASE MAX(CASE p.doi_status
           WHEN 'verified' THEN 4
           WHEN 'arxiv' THEN 3
           WHEN 'auto' THEN 2
           WHEN 'skipped' THEN 1
           ELSE 0
       END)
         WHEN 4 THEN 'verified'
         WHEN 3 THEN 'arxiv'
         WHEN 2 THEN 'auto'
         WHEN 1 THEN 'skipped'
         ELSE NULL
       END AS doi_status,
       MAX(p.doi_confidence) AS doi_confidence,
       MAX(p.doi_checked_at) AS doi_checked_at,
       MAX(NULLIF(p.publication_url, '')) AS publication_url,
       MAX(NULLIF(p.publication_venue_key, '')) AS publication_venue_key,
       CASE MAX(CASE p.publication_status
           WHEN 'published' THEN 3
           WHEN 'known_no_doi' THEN 2
           WHEN 'arxiv_only' THEN 1
           ELSE 0
       END)
         WHEN 3 THEN 'published'
         WHEN 2 THEN 'known_no_doi'
         WHEN 1 THEN 'arxiv_only'
         ELSE NULL
       END AS publication_status,
       MAX(NULLIF(p.editor_note, '')) AS editor_note
FROM papers p
JOIN paper_identity_map m ON m.old_id = p.id
GROUP BY m.keep_id;

UPDATE papers keep_paper
JOIN paper_metadata_merge merged ON merged.keep_id = keep_paper.id
SET keep_paper.created_at = merged.first_created_at,
    keep_paper.updated_at = merged.last_changed_at,
    keep_paper.doi_status = CASE
      WHEN keep_paper.doi IS NOT NULL
        THEN COALESCE(keep_paper.doi_status, merged.doi_status)
      WHEN merged.doi IS NOT NULL THEN merged.doi_status
      ELSE COALESCE(keep_paper.doi_status, merged.doi_status)
    END,
    keep_paper.doi = COALESCE(keep_paper.doi, merged.doi),
    keep_paper.doi_confidence = COALESCE(
      keep_paper.doi_confidence, merged.doi_confidence
    ),
    keep_paper.doi_checked_at = COALESCE(
      keep_paper.doi_checked_at, merged.doi_checked_at
    ),
    keep_paper.publication_url = COALESCE(
      keep_paper.publication_url, merged.publication_url
    ),
    keep_paper.publication_venue_key = COALESCE(
      keep_paper.publication_venue_key, merged.publication_venue_key
    ),
    keep_paper.publication_status = COALESCE(
      keep_paper.publication_status, merged.publication_status
    ),
    keep_paper.editor_note = COALESCE(keep_paper.editor_note, merged.editor_note);

INSERT IGNORE INTO paper_tags (paper_id, tag_id, created_at)
SELECT m.keep_id, pt.tag_id, pt.created_at
FROM paper_tags pt
JOIN paper_identity_map m ON m.old_id = pt.paper_id;

INSERT INTO paper_keywords (paper_id, keyword_id, source)
SELECT m.keep_id, pk.keyword_id, pk.source
FROM paper_keywords pk
JOIN paper_identity_map m ON m.old_id = pk.paper_id
WHERE pk.source IN ('manual', 'system')
ON DUPLICATE KEY UPDATE source = CASE
  WHEN VALUES(source) = 'manual' OR paper_keywords.source = 'manual' THEN 'manual'
  WHEN VALUES(source) = 'system' OR paper_keywords.source = 'system' THEN 'system'
  ELSE 'auto'
END;

INSERT INTO doi_candidates
    (paper_id, doi, confidence, crossref_title, crossref_authors,
     crossref_year, status, reviewed_at, created_at)
SELECT m.keep_id, dc.doi, dc.confidence, dc.crossref_title,
       dc.crossref_authors, dc.crossref_year, dc.status,
       dc.reviewed_at, dc.created_at
FROM doi_candidates dc
JOIN paper_identity_map m ON m.old_id = dc.paper_id
ON DUPLICATE KEY UPDATE
  confidence = GREATEST(doi_candidates.confidence, VALUES(confidence)),
  status = CASE
    WHEN doi_candidates.status = 'approved' OR VALUES(status) = 'approved'
      THEN 'approved'
    WHEN doi_candidates.status = 'pending' OR VALUES(status) = 'pending'
      THEN 'pending'
    ELSE 'rejected'
  END,
  reviewed_at = COALESCE(doi_candidates.reviewed_at, VALUES(reviewed_at));

-- Saved lists store the public versioned identifier rather than papers.id.
-- Move saves to the retained row first so no list becomes orphaned.
INSERT IGNORE INTO user_lists (user_id, list_name, arxiv_id, added_at)
SELECT ul.user_id, ul.list_name, keep_paper.arxiv_id, ul.added_at
FROM user_lists ul
JOIN papers old_paper ON old_paper.arxiv_id = ul.arxiv_id
JOIN paper_identity_map m ON m.old_id = old_paper.id
JOIN papers keep_paper ON keep_paper.id = m.keep_id
WHERE m.old_id <> m.keep_id;
DELETE ul FROM user_lists ul
JOIN papers old_paper ON old_paper.arxiv_id = ul.arxiv_id
JOIN paper_identity_map m ON m.old_id = old_paper.id
WHERE m.old_id <> m.keep_id;

DELETE pa FROM paper_authors pa
JOIN paper_identity_map m ON m.old_id = pa.paper_id
WHERE m.old_id <> m.keep_id;
DELETE pc FROM paper_categories pc
JOIN paper_identity_map m ON m.old_id = pc.paper_id
WHERE m.old_id <> m.keep_id;
DELETE pt FROM paper_tags pt
JOIN paper_identity_map m ON m.old_id = pt.paper_id
WHERE m.old_id <> m.keep_id;
DELETE pk FROM paper_keywords pk
JOIN paper_identity_map m ON m.old_id = pk.paper_id
WHERE m.old_id <> m.keep_id;
DELETE dc FROM doi_candidates dc
JOIN paper_identity_map m ON m.old_id = dc.paper_id
WHERE m.old_id <> m.keep_id;
DELETE p FROM papers p
JOIN paper_identity_map m ON m.old_id = p.id
WHERE m.old_id <> m.keep_id;

UPDATE site_stats
SET paper_count = (SELECT COUNT(*) FROM papers),
    author_count = (SELECT COUNT(*) FROM authors),
    latest_date = (SELECT MAX(published_date) FROM papers),
    cache_dirty_at = CURRENT_TIMESTAMP,
    cache_rebuild_after = CURRENT_TIMESTAMP
WHERE id = 1;

ALTER TABLE papers
  MODIFY arxiv_base_id VARCHAR(20) NOT NULL,
  ADD UNIQUE INDEX IF NOT EXISTS idx_arxiv_base_id (arxiv_base_id),
  ADD INDEX IF NOT EXISTS idx_created_cursor (created_at, id),
  ADD INDEX IF NOT EXISTS idx_updated_cursor (updated_at, id),
  ADD INDEX IF NOT EXISTS idx_published_cursor (published_date, id);

ALTER TABLE papers DROP INDEX IF EXISTS idx_arxiv_base_migration;

DROP TEMPORARY TABLE IF EXISTS paper_identity_map;
DROP TEMPORARY TABLE IF EXISTS paper_identity_keep;
DROP TEMPORARY TABLE IF EXISTS paper_metadata_merge;
