-- Migration: remove tag_name column from keywords table
-- tag_name was always written as a copy of phrase and never used for display
ALTER TABLE keywords DROP COLUMN tag_name;
