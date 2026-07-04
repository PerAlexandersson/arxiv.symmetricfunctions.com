import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from utils import (
    bibtex_keys_for_authors_year,
    extract_arxiv_id,
    parse_bibtex_search_key,
)


class SearchHelperTests(unittest.TestCase):
    def test_extracts_arxiv_ids_from_common_inputs(self):
        cases = {
            '2401.12345': '2401.12345',
            'arXiv:2401.12345v2': '2401.12345v2',
            'https://arxiv.org/abs/2401.12345': '2401.12345',
            'https://arxiv.org/pdf/2401.12345v1.pdf': '2401.12345v1',
            'https://arxiv.org/html/2401.12345v1': '2401.12345v1',
            'arxiv.org/abs/math/0601001': 'math/0601001',
            '<https://arxiv.org/abs/2401.12345>.': '2401.12345',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, extract_arxiv_id(raw))

    def test_ignores_non_arxiv_urls(self):
        self.assertIsNone(extract_arxiv_id('https://example.org/abs/2401.12345'))

    def test_parses_generated_bibtex_search_keys(self):
        parsed = parse_bibtex_search_key('AthanasiadisWagner2024')
        self.assertEqual('athanasiadiswagner2024', parsed['key_lower'])
        self.assertEqual(2024, parsed['year'])

        parsed = parse_bibtex_search_key('@article{AthanasiadisWagner2024x,')
        self.assertEqual('athanasiadiswagner2024x', parsed['key_lower'])
        self.assertEqual(2024, parsed['year'])

    def test_generated_keys_include_published_and_preprint_forms(self):
        keys = bibtex_keys_for_authors_year(
            ['Christos A. Athanasiadis', 'Tanja K. Wagner'],
            2024,
        )
        self.assertIn('athanasiadiswagner2024', keys)
        self.assertIn('athanasiadiswagner2024x', keys)


if __name__ == '__main__':
    unittest.main()
