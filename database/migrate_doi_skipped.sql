-- Add 'skipped' to doi_status ENUM
-- Marks papers unlikely to ever receive a DOI (e.g. preprints never submitted to a journal)
-- Safe to re-run: ALTER on the same definition is a no-op or harmless.

ALTER TABLE papers
  MODIFY doi_status ENUM('arxiv','auto','verified','skipped') DEFAULT NULL;
