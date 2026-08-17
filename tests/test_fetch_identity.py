import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('DB_PASSWORD', 'test-password')
os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('ADMIN_PASSWORD', 'test-admin-password')
os.environ.setdefault('FETCH_SECRET', 'test-fetch-secret')

from fetch_arxiv import insert_or_update_paper


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.queries = []
        self.lastrowid = 31

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def fake_paper(version, doi=None):
    timestamp = datetime(2026, 8, version, tzinfo=timezone.utc)
    return SimpleNamespace(
        entry_id=f'https://arxiv.org/abs/2608.12345v{version}',
        title='A versioned paper',
        summary='An abstract.',
        published=timestamp,
        updated=timestamp,
        comment=None,
        journal_ref=None,
        doi=doi,
        primary_category='math.CO',
        authors=[],
        categories=['math.CO'],
    )


class FetchIdentityTests(unittest.TestCase):
    def test_new_revision_updates_existing_logical_paper_and_saved_lists(self):
        cursor = FakeCursor([
            (17, '2608.12345v1', 1, None, None, None),
        ])
        paper_id = insert_or_update_paper(cursor, fake_paper(2))
        self.assertEqual(17, paper_id)
        self.assertTrue(any(
            'INSERT IGNORE INTO user_lists' in query
            for query, _ in cursor.queries
        ))
        update = next(
            (query, params) for query, params in cursor.queries
            if 'UPDATE papers SET' in query
        )
        self.assertIn('arxiv_version = %s', update[0])
        self.assertEqual(('2608.12345v2', 2, 17), update[1][-3:])

    def test_explicit_old_revision_cannot_overwrite_newer_metadata(self):
        cursor = FakeCursor([
            (17, '2608.12345v3', 3, None, None, None),
        ])
        paper_id = insert_or_update_paper(cursor, fake_paper(2))
        self.assertEqual(17, paper_id)
        self.assertEqual(1, len(cursor.queries))

    def test_arxiv_doi_cannot_overwrite_verified_publisher_doi(self):
        cursor = FakeCursor([(
            17,
            '2608.12345v1',
            1,
            '10.1017/correct',
            'verified',
            'published',
        )])
        insert_or_update_paper(
            cursor,
            fake_paper(2, doi='10.1007/unrelated'),
        )
        update = next(
            (query, params) for query, params in cursor.queries
            if 'UPDATE papers SET' in query
        )
        self.assertEqual('10.1017/correct', update[1][6])
        self.assertEqual('verified', update[1][7])

    def test_rejected_arxiv_doi_is_not_restored(self):
        cursor = FakeCursor([
            (
                17,
                '2608.12345v1',
                1,
                None,
                None,
                None,
            ),
            (1,),
        ])
        insert_or_update_paper(
            cursor,
            fake_paper(2, doi='10.1007/unrelated'),
        )
        update = next(
            (query, params) for query, params in cursor.queries
            if 'UPDATE papers SET' in query
        )
        self.assertIsNone(update[1][6])
        self.assertIsNone(update[1][7])
        self.assertIsNone(update[1][8])

    def test_rejected_arxiv_doi_does_not_replace_an_existing_doi(self):
        cursor = FakeCursor([
            (
                17,
                '2608.12345v1',
                1,
                '10.1017/correct',
                'auto',
                'published',
            ),
            (1,),
        ])
        insert_or_update_paper(
            cursor,
            fake_paper(2, doi='10.1007/unrelated'),
        )
        update = next(
            (query, params) for query, params in cursor.queries
            if 'UPDATE papers SET' in query
        )
        self.assertEqual('10.1017/correct', update[1][6])
        self.assertEqual('auto', update[1][7])
        self.assertEqual('published', update[1][8])


if __name__ == '__main__':
    unittest.main()
