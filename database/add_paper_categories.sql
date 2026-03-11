-- Migration: add paper_categories table for secondary arXiv subject classifications
-- Run once on local and production databases.

CREATE TABLE IF NOT EXISTS paper_categories (
    paper_id INT NOT NULL,
    category VARCHAR(20) NOT NULL,
    PRIMARY KEY (paper_id, category),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
