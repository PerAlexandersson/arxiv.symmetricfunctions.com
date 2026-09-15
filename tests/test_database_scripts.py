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


if __name__ == '__main__':
    unittest.main()
