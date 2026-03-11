-- arXiv Combinatorics Frontend Database Schema
-- MariaDB/MySQL compatible
--
-- !! WARNING: FOR FRESH INSTALLS ONLY — DROPS ALL TABLES !!
-- !! Never run this on a live database. Use migrate_*.sql for changes. !!
-- !! sync_to_prod.sh intentionally skips this file. !!

-- Disable foreign key checks temporarily to allow dropping tables
SET FOREIGN_KEY_CHECKS = 0;

-- Drop tables if they exist (for clean reinstall)
DROP TABLE IF EXISTS user_lists;
DROP TABLE IF EXISTS user_categories;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS paper_keywords;
DROP TABLE IF EXISTS keyword_aliases;
DROP TABLE IF EXISTS paper_authors;
DROP TABLE IF EXISTS paper_tags;
DROP TABLE IF EXISTS paper_categories;
DROP TABLE IF EXISTS authors;
DROP TABLE IF EXISTS papers;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS keywords;
DROP TABLE IF EXISTS ignored_candidates;
DROP TABLE IF EXISTS math_words;

-- Re-enable foreign key checks
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- Papers Table
-- Stores main metadata for each arXiv paper
-- ============================================================================
CREATE TABLE papers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- arXiv identifiers
    arxiv_id VARCHAR(20) UNIQUE NOT NULL,           -- e.g., "2401.12345" or "math/0601001"
    primary_category VARCHAR(20) DEFAULT 'math.CO', -- Always math.CO for this project
    
    -- Paper metadata
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    
    -- Dates
    published_date DATE NOT NULL,                   -- First submission date
    updated_date DATE,                              -- Last update/revision (NULL if never updated)
    
    -- Publication info (optional)
    comment TEXT,                                   -- e.g., "23 pages, 5 figures, to appear in Combinatorica"
    journal_ref TEXT,                               -- e.g., "J. Combin. Theory Ser. A 156 (2018), 1-23"
    doi VARCHAR(100),                               -- Digital Object Identifier
    
    -- Internal tracking
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes for common queries
    INDEX idx_arxiv_id (arxiv_id),
    INDEX idx_published_date (published_date),
    INDEX idx_updated_date (updated_date)
    
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Authors Table
-- Stores unique author names to avoid duplication
-- ============================================================================
CREATE TABLE authors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255),                    -- URL-friendly version of name

    -- Ensure uniqueness (same author name stored only once)
    UNIQUE KEY idx_unique_name (name),
    INDEX idx_name (name),
    INDEX idx_author_slug (slug)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Paper-Authors Junction Table
-- Many-to-many relationship: papers can have multiple authors,
-- authors can have multiple papers
-- ============================================================================
CREATE TABLE paper_authors (
    paper_id INT NOT NULL,
    author_id INT NOT NULL,
    author_order INT NOT NULL,    -- Position in author list (1, 2, 3, ...)

    PRIMARY KEY (paper_id, author_id),

    -- Foreign key constraints
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,

    -- Indexes for common queries
    INDEX idx_author_id (author_id),
    INDEX idx_paper_id (paper_id),
    INDEX idx_author_order (paper_id, author_order)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Paper Categories Table
-- All arXiv subject categories for each paper (primary + cross-listings)
-- Populated automatically during fetch; powers /category/<cat> browsing
-- ============================================================================
CREATE TABLE paper_categories (
    paper_id INT NOT NULL,
    category VARCHAR(20) NOT NULL,
    PRIMARY KEY (paper_id, category),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Tags Table
-- Stores all tags (MSC codes, personal tags, arXiv categories, etc.)
-- ============================================================================
CREATE TABLE tags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,

    -- Tag type: 'msc' for MSC 2020 codes, 'personal' for custom tags,
    -- 'arxiv' for arXiv categories, 'other' for miscellaneous
    tag_type ENUM('msc', 'personal', 'arxiv', 'other') DEFAULT 'personal',

    -- Optional description
    description TEXT,

    -- For hierarchical tags (e.g., MSC 05A is parent of 05A15)
    parent_tag_id INT,

    -- Ensure unique name per type
    UNIQUE KEY idx_unique_tag (name, tag_type),
    INDEX idx_tag_name (name),
    INDEX idx_tag_type (tag_type),

    FOREIGN KEY (parent_tag_id) REFERENCES tags(id) ON DELETE SET NULL

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Paper-Tags Junction Table
-- Many-to-many relationship: papers can have multiple tags,
-- tags can be applied to multiple papers
-- ============================================================================
CREATE TABLE paper_tags (
    paper_id INT NOT NULL,
    tag_id INT NOT NULL,

    -- Track when tag was added (useful for personal tags)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (paper_id, tag_id),

    -- Foreign key constraints
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,

    -- Indexes for common queries
    INDEX idx_paper_id (paper_id),
    INDEX idx_tag_id (tag_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Full-Text Search Index
-- Enable fast searching in title and abstract
-- ============================================================================
ALTER TABLE papers ADD FULLTEXT INDEX idx_fulltext_search (title, abstract);

-- ============================================================================
-- Pre-populate Common MSC 2020 Codes for Combinatorics
-- ============================================================================
INSERT INTO tags (name, tag_type, description) VALUES
    ('05A05', 'msc', 'Permutations, words, matrices'),
    ('05A10', 'msc', 'Factorials, binomial coefficients, combinatorial functions'),
    ('05A15', 'msc', 'Exact enumeration problems, generating functions'),
    ('05A16', 'msc', 'Asymptotic enumeration'),
    ('05A17', 'msc', 'Combinatorial aspects of partitions of integers'),
    ('05A18', 'msc', 'Partitions of sets'),
    ('05A19', 'msc', 'Combinatorial identities, bijective combinatorics'),
    ('05A20', 'msc', 'Combinatorial inequalities'),
    ('05A30', 'msc', 'q-calculus and related topics'),
    ('05A40', 'msc', 'Umbral calculus'),
    ('05E05', 'msc', 'Symmetric functions and generalizations'),
    ('05E10', 'msc', 'Combinatorial aspects of representation theory'),
    ('05E14', 'msc', 'Combinatorial aspects of algebraic geometry'),
    ('05E16', 'msc', 'Combinatorial structures in finite geometry'),
    ('05E18', 'msc', 'Group actions on combinatorial structures');

-- ============================================================================
-- Keywords Table
-- Curated keyword phrases for auto-tagging papers (managed via admin UI)
-- ============================================================================
CREATE TABLE keywords (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    phrase    VARCHAR(255) NOT NULL,
    score     INT NOT NULL DEFAULT 5,          -- Relevance weight 1-10
    url       TEXT,                            -- Reference URL (e.g. symmetricfunctions.com page)
    active    BOOLEAN NOT NULL DEFAULT 1,      -- Set to 0 to disable without deleting

    UNIQUE KEY idx_unique_phrase (phrase),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Keyword Aliases Table
-- Alternative phrasings that map to the same keyword
-- ============================================================================
CREATE TABLE keyword_aliases (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    keyword_id INT NOT NULL,
    alias      VARCHAR(255) NOT NULL,

    UNIQUE KEY idx_unique_alias (alias),
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Ignored Candidates Table
-- Phrases confirmed as non-math or typos (excluded from keyword candidates)
-- ============================================================================
CREATE TABLE ignored_candidates (
    id     INT AUTO_INCREMENT PRIMARY KEY,
    phrase VARCHAR(255) NOT NULL,
    UNIQUE KEY idx_unique_phrase (phrase)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Math Words Table
-- Words that are valid math terms but too broad to be useful tags alone
-- ============================================================================
CREATE TABLE math_words (
    id     INT AUTO_INCREMENT PRIMARY KEY,
    phrase VARCHAR(255) NOT NULL,
    UNIQUE KEY idx_unique_phrase (phrase)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- Paper-Keywords Junction Table
-- Auto-generated by auto_tag.py; links papers to matched keywords
-- ============================================================================
CREATE TABLE paper_keywords (
    paper_id   INT NOT NULL,
    keyword_id INT NOT NULL,

    PRIMARY KEY (paper_id, keyword_id),
    KEY idx_keyword_id (keyword_id),

    FOREIGN KEY (paper_id)   REFERENCES papers(id)   ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- ============================================================================
-- Users Table
-- Authenticated users (ORCID login; provider field is future-proof for Google)
-- ============================================================================
CREATE TABLE users (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    provider     ENUM('orcid', 'google') NOT NULL,
    provider_id  VARCHAR(100) NOT NULL,        -- ORCID iD (0000-0002-xxxx-xxxx) or Google sub
    display_name VARCHAR(255),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_provider (provider, provider_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- User Categories Table
-- Named list buckets per user (Starred list + custom lists)
-- ============================================================================
CREATE TABLE user_categories (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    name       VARCHAR(100) NOT NULL,
    is_starred TINYINT(1)   NOT NULL DEFAULT 0,
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY idx_user_cat_name (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- User Lists Table
-- Personal paper lists (Favorites, To read, etc.) linked to a user
-- ============================================================================
CREATE TABLE user_lists (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    list_name  VARCHAR(100) NOT NULL DEFAULT 'Favorites',
    arxiv_id   VARCHAR(20) NOT NULL,
    added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY idx_user_list_paper (user_id, list_name, arxiv_id),
    INDEX idx_user_list (user_id, list_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
