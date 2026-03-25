-- migrate_doi_status.sql
-- Add DOI provenance tracking and candidate staging table.

-- 1. Add doi_status and doi_confidence to papers
ALTER TABLE papers
  ADD COLUMN doi_status ENUM('arxiv','auto','verified') DEFAULT NULL AFTER doi,
  ADD COLUMN doi_confidence DECIMAL(4,3) DEFAULT NULL AFTER doi_status,
  ADD INDEX idx_doi_status (doi_status);

-- 2. Backfill existing DOIs as 'arxiv' (came from arXiv API)
UPDATE papers SET doi_status = 'arxiv' WHERE doi IS NOT NULL;

-- 3. Candidate staging table for Crossref matches
CREATE TABLE IF NOT EXISTS doi_candidates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    paper_id        INT NOT NULL,
    doi             VARCHAR(100) NOT NULL,
    confidence      DECIMAL(4,3) NOT NULL,
    crossref_title  TEXT,
    crossref_authors TEXT,
    crossref_year   SMALLINT,
    status          ENUM('pending','approved','rejected') DEFAULT 'pending',
    reviewed_at     TIMESTAMP NULL DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY idx_paper_doi (paper_id, doi),
    INDEX idx_status (status),
    INDEX idx_confidence (confidence),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
