-- migrate_doi_checked.sql
-- Track when each paper was last checked for a DOI via Crossref.

ALTER TABLE papers
  ADD COLUMN doi_checked_at TIMESTAMP NULL DEFAULT NULL AFTER doi_confidence;
