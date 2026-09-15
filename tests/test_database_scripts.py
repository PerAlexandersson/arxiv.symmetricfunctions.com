import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DatabaseScriptSafetyTests(unittest.TestCase):
    def test_doi_merge_failure_cannot_echo_database_password(self):
        script = (ROOT / 'database' / 'merge_prod_doi_state.sh').read_text()

        self.assertNotIn('.env.production', script)
        self.assertNotIn('prod_env', script)
        self.assertNotIn("prod_env['DB_PASSWORD']", script)
        self.assertIn('MYSQL_PWD=\\"$DB_PASSWORD\\"', script)
        self.assertIn('check=False', script)
        self.assertIn('production DOI query failed', script)

    def test_saved_lists_use_stable_foreign_keys(self):
        schema = (ROOT / 'database' / 'schema.sql').read_text()
        migration = (
            ROOT / 'database' / 'migrate_normalize_user_lists.sql'
        ).read_text()

        list_schema = schema.split('CREATE TABLE user_lists (', 1)[1].split(
            ') ENGINE=InnoDB', 1
        )[0]
        self.assertIn('category_id INT NOT NULL', list_schema)
        self.assertIn('paper_id    INT NOT NULL', list_schema)
        self.assertNotIn('list_name', list_schema)
        self.assertNotIn('arxiv_id', list_schema)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)
        self.assertIn('RENAME TABLE user_lists TO user_lists_legacy_', migration)
        self.assertIn("IF normalized_columns = 2 THEN", migration)
        self.assertIn('user_lists already normalized', migration)

    def test_deploy_requires_normalized_list_schema(self):
        script = (ROOT / 'sync_to_prod.sh').read_text()

        self.assertIn('information_schema.COLUMNS', script)
        self.assertIn('LIST_SCHEMA_COLUMNS', script)
        self.assertIn('migrate_normalize_user_lists.sql before deploying', script)
        self.assertIn('refresh_sf_labels', script)
        self.assertNotIn('deployment/htaccess_template', script)

    def test_web_import_has_no_schema_ddl(self):
        schema = (ROOT / 'database' / 'schema.sql').read_text()
        app_source = (ROOT / 'src' / 'app.py').read_text()
        stats_source = (ROOT / 'src' / 'site_stats.py').read_text()

        self.assertIn('CREATE TABLE site_stats', schema)
        self.assertIn('DROP TABLE IF EXISTS site_stats', schema)
        self.assertIn('DROP TABLE IF EXISTS doi_candidates', schema)
        self.assertNotIn('ensure_author_slugs()', app_source)
        self.assertNotIn('CREATE TABLE', stats_source)
        self.assertNotIn('ALTER TABLE', stats_source)


if __name__ == '__main__':
    unittest.main()
