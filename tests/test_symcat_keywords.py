import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import symcat_keywords as importer


def catalogue(*rows):
    return {'schema_version': 1, 'keywords': [
        {'phrase': phrase, 'href': href} for phrase, href in rows
    ]}


class KeywordTests(unittest.TestCase):
    def test_normalizes_like_tagger_and_preserves_multiple_targets(self):
        result = importer.parse_catalogue(catalogue(
            ('Young tableaux', 'tableaux.htm#youngTableau'),
            ('Young tableau', 'schur.htm'),
            ('Young tableaux', 'tableaux.htm#youngTableau'),
            ('Möbius functions', 'posets.htm'),
        ))
        self.assertEqual(set(result), {'young tableau', 'mobius function'})
        self.assertEqual(len(result['young tableau']), 2)

    def test_rejects_entire_bad_feed(self):
        good = catalogue(('Schur functions', 'schur.htm'))
        for payload in [None, {}, {'schema_version': True, 'keywords': []},
                        catalogue(), catalogue(('', 'schur.htm')),
                        catalogue(('Schur functions', 'https://example.com/')),
                        catalogue(('Schur functions', '../private.htm')),
                        catalogue(('Schur functions', 'schur.htm?query=x')),
                        catalogue(('Schur functions', 'schur.htm#<script>')),
                        {**good, 'keywords': good['keywords'] + [None]}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                importer.parse_catalogue(payload)

    def test_fetch_checks_status_json_and_size(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.iter_content.return_value = [json.dumps(
            catalogue(('Schur functions', 'schur.htm'))).encode()]
        with mock.patch.object(importer.requests, 'get', return_value=response) as get:
            self.assertIn('schur function', importer.fetch_keywords())
            self.assertEqual(get.call_args.args, (importer.KEYWORD_URL,))
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            response.status_code = 404
            with self.assertRaises(ValueError):
                importer.fetch_keywords()
            response.status_code = 200
            response.iter_content.return_value = [b'not json']
            with self.assertRaises(ValueError):
                importer.fetch_keywords()
            response.iter_content.return_value = [b'12345']
            with mock.patch.object(importer, 'MAX_BYTES', 4), self.assertRaises(ValueError):
                importer.fetch_keywords()

    def test_preserves_curated_terms_aliases_exclusions_and_tags(self):
        conn = mock.Mock()
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [{'phrase': 'Young tableaux'}, {'phrase': 'Schur function'}],
            [{'phrase': 'ground sets'}],
        ]
        cursor.rowcount = 1
        keywords = importer.parse_catalogue(catalogue(
            ('Young tableau', 'tableaux.htm'), ('Schur functions', 'schur.htm'),
            ('Ground set', 'matroids.htm'), ('Laminar matroids', 'matroids.htm#laminarMatroid'),
            ('New term', 'a.htm'), ('New term', 'b.htm'),
        ))
        self.assertEqual(importer.import_keywords(conn, keywords),
                         dict(total=5, added=2, existing=2, excluded=1))
        writes = [call.args for call in cursor.execute.call_args_list
                  if call.args[0].startswith('INSERT')]
        self.assertEqual([args[1] for args in writes], [
            ('laminar matroid', importer.SYMCAT_BASE + 'matroids.htm#laminarMatroid'),
            ('new term', None),
        ])
        self.assertFalse(any('paper_keywords' in call.args[0]
                             for call in cursor.execute.call_args_list))
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_database_failure_rolls_back(self):
        conn = mock.Mock()
        cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[], []]
        cursor.execute.side_effect = [None, None, None, pymysql.OperationalError('failure')]
        with self.assertRaises(pymysql.Error):
            importer.import_keywords(conn, {'a term': {'a'}, 'b term': {'b'}})
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        cursor.close.assert_called_once()


@unittest.skipUnless(os.getenv('SYMCAT_TEST_DB_HOST'), 'opt-in temporary-table MariaDB test')
class KeywordDatabaseTests(unittest.TestCase):
    def test_repeat_import_and_rollback_preserve_curated_rows(self):
        from config import DB_CONFIG
        conn = pymysql.connect(**dict(DB_CONFIG, host=os.environ['SYMCAT_TEST_DB_HOST']),
                               cursorclass=pymysql.cursors.DictCursor)
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('''CREATE TEMPORARY TABLE keywords (
                id INT AUTO_INCREMENT PRIMARY KEY, phrase VARCHAR(255) UNIQUE,
                score INT, url TEXT, active BOOLEAN DEFAULT 1
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
            cur.execute('CREATE TEMPORARY TABLE keyword_aliases (alias VARCHAR(255)) ENGINE=InnoDB')
            cur.execute('CREATE TEMPORARY TABLE math_words (phrase VARCHAR(255)) ENGINE=InnoDB')
            cur.execute('CREATE TEMPORARY TABLE ignored_candidates (phrase VARCHAR(255)) ENGINE=InnoDB')
            cur.execute("INSERT INTO keywords (phrase,score,url,active) VALUES ('schur function',8,'curated',0)")
            cur.execute("INSERT INTO keyword_aliases VALUES ('young tableau')")
            cur.execute("INSERT INTO math_words VALUES ('ground set')")
        conn.commit()
        keywords = importer.parse_catalogue(catalogue(
            ('Schur functions', 'schur.htm'), ('Young tableaux', 'tableaux.htm'),
            ('Ground sets', 'matroids.htm'), ('Laminar matroids', 'matroids.htm#laminarMatroid'),
        ))
        self.assertEqual(importer.import_keywords(conn, keywords),
                         dict(total=4, added=1, existing=2, excluded=1))
        self.assertEqual(importer.import_keywords(conn, keywords),
                         dict(total=4, added=0, existing=3, excluded=1))
        with conn.cursor() as cur:
            cur.execute('SELECT phrase,score,url,active FROM keywords ORDER BY id')
            rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], dict(phrase='schur function', score=8, url='curated', active=0))
        # A connection error at commit must roll back the preceding insert.
        with mock.patch.object(conn, 'commit', side_effect=pymysql.OperationalError('failure')):
            with self.assertRaises(pymysql.Error):
                importer.import_keywords(conn, {'temporary term': {importer.SYMCAT_BASE + 'a.htm'}})
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM keywords')
            self.assertEqual(cur.fetchone()['n'], 2)
