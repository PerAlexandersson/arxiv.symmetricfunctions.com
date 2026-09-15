-- Normalize saved-list memberships onto stable category and paper identifiers.
--
-- Back up the database before running this migration. It verifies that every
-- legacy row maps to exactly one category and paper before replacing the table.
-- Re-running it after a successful migration is a no-op.

DELIMITER //
DROP PROCEDURE IF EXISTS normalize_user_lists//
CREATE PROCEDURE normalize_user_lists()
BEGIN
    DECLARE normalized_columns INT DEFAULT 0;
    DECLARE legacy_columns INT DEFAULT 0;
    DECLARE backup_tables INT DEFAULT 0;
    DECLARE legacy_rows BIGINT DEFAULT 0;
    DECLARE normalized_rows BIGINT DEFAULT 0;

    SELECT COUNT(*) INTO normalized_columns
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'user_lists'
      AND COLUMN_NAME IN ('category_id', 'paper_id');

    IF normalized_columns = 2 THEN
        -- Already migrated: leave the current and rollback tables untouched.
        SELECT 'user_lists already normalized' AS migration_status;
    ELSE
        SELECT COUNT(*) INTO legacy_columns
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'user_lists'
          AND COLUMN_NAME IN ('user_id', 'list_name', 'arxiv_id');
        IF legacy_columns <> 3 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'user_lists has neither legacy nor normalized schema';
        END IF;

        SELECT COUNT(*) INTO backup_tables
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'user_lists_legacy_20260915';
        IF backup_tables <> 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'user_lists rollback table already exists';
        END IF;

        DROP TABLE IF EXISTS user_lists_v2;
        CREATE TABLE user_lists_v2 (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            category_id INT NOT NULL,
            paper_id    INT NOT NULL,
            added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE KEY idx_user_list_paper (category_id, paper_id),
            INDEX idx_user_list_paper_lookup (paper_id, category_id),
            FOREIGN KEY (category_id) REFERENCES user_categories(id) ON DELETE CASCADE,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

        INSERT INTO user_lists_v2 (category_id, paper_id, added_at)
        SELECT uc.id, p.id, ul.added_at
        FROM user_lists ul
        JOIN user_categories uc
          ON uc.user_id = ul.user_id AND uc.name = ul.list_name
        JOIN papers p ON p.arxiv_id = ul.arxiv_id;

        SELECT COUNT(*) INTO legacy_rows FROM user_lists;
        SELECT COUNT(*) INTO normalized_rows FROM user_lists_v2;
        IF legacy_rows <> normalized_rows THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'user_lists normalization lost or duplicated rows';
        END IF;

        RENAME TABLE user_lists TO user_lists_legacy_20260915,
                     user_lists_v2 TO user_lists;
        SELECT 'user_lists normalized successfully' AS migration_status;
    END IF;
END//
DELIMITER ;

CALL normalize_user_lists();
DROP PROCEDURE normalize_user_lists;

-- The verified backup table is retained for explicit rollback until the new
-- application version has been deployed and checked. It is an immediate
-- rollback snapshot: new memberships written after deployment are not copied
-- back to it. To roll back before accepting new writes:
--
-- RENAME TABLE user_lists TO user_lists_failed_20260915,
--              user_lists_legacy_20260915 TO user_lists;
--
-- Drop the legacy table separately only after the production checkpoint:
-- DROP TABLE user_lists_legacy_20260915;
