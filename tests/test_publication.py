import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from publication import (
    detect_known_no_doi_venue,
    normalize_doi,
    parse_publication_input,
)


class PublicationParsingTests(unittest.TestCase):
    def test_normalizes_raw_and_url_dois(self):
        self.assertEqual('10.1002/jgt.22704', normalize_doi('10.1002/jgt.22704'))
        self.assertEqual(
            '10.1002/jgt.22704',
            normalize_doi('https://doi.org/10.1002/jgt.22704'),
        )

    def test_detects_known_no_doi_venues(self):
        self.assertEqual(
            'jis',
            detect_known_no_doi_venue(
                'https://cs.uwaterloo.ca/journals/JIS/VOL1/example.html'
            ),
        )
        self.assertEqual(
            'slc',
            detect_known_no_doi_venue(
                'https://www.mat.univie.ac.at/~slc/wpapers/s80kratt.html'
            ),
        )

    def test_auto_parses_known_no_doi_url_as_skipped(self):
        parsed = parse_publication_input(
            'auto',
            'https://www.emis.de/journals/SLC/wpapers/s80kratt.html',
        )
        self.assertEqual('known_no_doi', parsed['kind'])
        self.assertEqual('slc', parsed['publication_venue_key'])
        self.assertEqual('skipped', parsed['doi_status'])

    def test_auto_parses_unknown_url_without_skipping_doi_lookup(self):
        parsed = parse_publication_input('auto', 'https://example.org/paper')
        self.assertEqual('publication_url', parsed['kind'])
        self.assertEqual('published', parsed['publication_status'])
        self.assertIsNone(parsed['doi_status'])

    def test_arxiv_only_is_publication_status(self):
        parsed = parse_publication_input('arxiv_only', '')
        self.assertEqual('arxiv_only', parsed['publication_status'])
        self.assertEqual('arxiv', parsed['publication_venue_key'])
        self.assertEqual('skipped', parsed['doi_status'])


if __name__ == '__main__':
    unittest.main()
