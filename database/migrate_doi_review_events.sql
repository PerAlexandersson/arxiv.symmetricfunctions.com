-- Additive, idempotent migration. Apply before enabling the DOI review token.
-- Retain audit snapshots even if a candidate or paper is later removed.
CREATE TABLE IF NOT EXISTS doi_review_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id INT NOT NULL,
    paper_id INT NOT NULL,
    doi VARCHAR(100) NOT NULL,
    decision ENUM('approve', 'reject') NOT NULL,
    reviewer VARCHAR(100) NOT NULL,
    reason TEXT NOT NULL,
    review_token CHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_doi_review_candidate (candidate_id),
    INDEX idx_doi_review_paper (paper_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
