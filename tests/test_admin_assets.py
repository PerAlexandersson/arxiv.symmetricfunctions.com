import unittest
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminAssetTests(unittest.TestCase):
    def test_doi_queue_mutations_refresh_attention_banner(self):
        attention_source = (
            ROOT / 'src' / 'static' / 'admin-attention.js'
        ).read_text()
        dois_source = (
            ROOT / 'src' / 'static' / 'admin-dois.js'
        ).read_text()

        self.assertIn('container.replaceChildren()', attention_source)
        self.assertIn('container.hidden = true', attention_source)
        self.assertIn(
            "document.addEventListener('admin-attention:refresh', refreshAttention)",
            attention_source,
        )
        self.assertIn(
            "document.dispatchEvent(new Event('admin-attention:refresh'))",
            dois_source,
        )
        self.assertEqual(2, dois_source.count('refreshAdminAttention();'))

    def test_changed_admin_assets_have_new_cache_versions(self):
        nav_source = (
            ROOT / 'src' / 'templates' / 'admin' / '_nav.html'
        ).read_text()
        dois_template = (
            ROOT / 'src' / 'templates' / 'admin' / 'dois.html'
        ).read_text()

        self.assertIn("filename='admin-attention.js') }}?v=2", nav_source)
        self.assertIn("filename='admin-dois.js') }}?v=4", dois_template)
        self.assertNotIn('doi-show-conflicts', dois_template)
        self.assertNotIn('doi-hidden-notice', dois_template)
        self.assertNotIn('data-doi-show-hidden', dois_template)
        self.assertIn('DOI already assigned to another paper', dois_template)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for DOM behavior tests')
    def test_doi_filter_behavior(self):
        result = subprocess.run(
            ['node', '--test', str(ROOT / 'tests' / 'admin_doi_filter.test.cjs')],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
