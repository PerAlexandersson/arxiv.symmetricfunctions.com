import importlib
import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

for _key, _value in {
    'DB_PASSWORD': 'test-password',
    'FLASK_SECRET_KEY': 'test-secret-key',
    'ADMIN_PASSWORD': 'test-admin-password',
    'FETCH_SECRET': 'test-fetch-secret',
    'FLASK_DEBUG': 'True',
}.items():
    os.environ.setdefault(_key, _value)

with mock.patch('requests.get') as _mock_get, \
        mock.patch('pymysql.connect',
                   side_effect=pymysql.err.OperationalError('DB disabled in tests')):
    _mock_get.return_value.ok = True
    _mock_get.return_value.json.return_value = {}
    app_module = importlib.import_module('app')

import api_v1
from paper_repository import CursorError, list_papers, serialize_paper
from utils import split_arxiv_id_version


class FakeCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return self.fetchall_values.pop(0) if self.fetchall_values else []

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def paper_row(paper_id=7):
    return {
        'id': paper_id,
        'arxiv_id': '2608.12345v2',
        'arxiv_base_id': '2608.12345',
        'arxiv_version': 2,
        'title': 'Schur Functions and Posets',
        'abstract': 'We study symmetric functions.',
        'primary_category': 'math.CO',
        'published_date': date(2026, 8, 1),
        'updated_date': date(2026, 8, 4),
        'created_at': datetime(2026, 8, 2, 3, 4, 5, tzinfo=timezone.utc),
        'updated_at': datetime(2026, 8, 4, 6, 7, 8, tzinfo=timezone.utc),
        'comment': None,
        'journal_ref': None,
        'doi': None,
        'doi_status': None,
        'publication_url': None,
        'publication_venue_key': None,
        'publication_status': None,
        'editor_note': None,
    }


class RepositoryTests(unittest.TestCase):
    def test_splits_modern_and_legacy_versions(self):
        self.assertEqual(('2608.12345', 3), split_arxiv_id_version('2608.12345v3'))
        self.assertEqual(('math/0601001', 2), split_arxiv_id_version('math/0601001v2'))
        self.assertEqual((None, None), split_arxiv_id_version('not-an-arxiv-id'))

    def test_serialization_uses_stable_identity_and_symcat_targets(self):
        row = paper_row()
        row.update({
            'authors': ['Ada Lovelace'],
            'categories': ['math.CO', 'math.RT'],
            'keywords': [{
                'phrase': 'schur functions',
                'score': 10,
                'source': 'manual',
                'url': 'schur',
            }],
        })
        payload = serialize_paper(row, {
            'schur': {'href': 'schur.htm', 'title': 'Schur functions'}
        })
        self.assertEqual('2608.12345', payload['arxiv_id'])
        self.assertEqual('2608.12345v2', payload['versioned_arxiv_id'])
        self.assertEqual(2, payload['arxiv_version'])
        self.assertEqual('schur', payload['symcat_targets'][0]['label'])
        self.assertEqual(
            'https://www.symmetricfunctions.com/schur.htm',
            payload['symcat_targets'][0]['url'],
        )

    def test_list_papers_uses_keyset_cursor(self):
        first = paper_row(8)
        second = paper_row(7)
        second['created_at'] = datetime(2026, 8, 1, 3, 4, 5, tzinfo=timezone.utc)
        cursor = FakeCursor(fetchall_values=[
            [first, second],
            [], [], [],
        ])
        page = list_papers(cursor, limit=1, order='ingested')
        self.assertTrue(page['has_more'])
        self.assertIsNotNone(page['next_cursor'])

        next_cursor = FakeCursor(fetchall_values=[[], [], [], []])
        list_papers(
            next_cursor,
            limit=1,
            order='ingested',
            cursor_token=page['next_cursor'],
        )
        query, params = next_cursor.queries[0]
        self.assertIn('p.created_at < %s', query)
        self.assertEqual(8, params[-2])

    def test_cursor_cannot_be_reused_with_another_order(self):
        cursor = FakeCursor(fetchall_values=[[paper_row(), paper_row(6)], [], [], []])
        page = list_papers(cursor, limit=1, order='ingested')
        with self.assertRaises(CursorError):
            list_papers(
                FakeCursor(), limit=1, order='published',
                cursor_token=page['next_cursor'],
            )


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app_module.app.test_client()

    def test_api_index_is_cacheable_and_discoverable(self):
        response = self.client.get('/api/v1/')
        self.assertEqual(200, response.status_code)
        self.assertEqual('v1', response.get_json()['version'])
        self.assertEqual('*', response.headers['Access-Control-Allow-Origin'])
        self.assertIn('ETag', response.headers)

    def test_status_has_freshness_metadata(self):
        cursor = FakeCursor(fetchone_values=[{
            'paper_count': 42,
            'latest_ingested_at': datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
            'latest_changed_at': datetime(2026, 8, 15, 13, tzinfo=timezone.utc),
            'latest_published_at': date(2026, 8, 14),
        }])
        with mock.patch.object(
                api_v1, 'get_db_connection',
                return_value=FakeConnection(cursor)):
            response = self.client.get('/api/v1/status')
        self.assertEqual(200, response.status_code)
        self.assertEqual(42, response.get_json()['paper_count'])
        self.assertTrue(cursor.closed)

    def test_paper_list_rejects_bad_limit(self):
        response = self.client.get('/api/v1/papers?limit=0')
        self.assertEqual(400, response.status_code)
        self.assertEqual('invalid_request', response.get_json()['error']['code'])

    def test_openapi_document_is_served(self):
        response = self.client.get('/api/v1/openapi.yaml')
        self.assertEqual(200, response.status_code)
        self.assertIn(b'openapi: 3.1.0', response.data)
        response.close()

    def test_existing_json_endpoint_rejects_empty_json_body(self):
        response = self.client.post(
            '/api/generate-bibtex',
            data='',
            content_type='application/json',
        )
        self.assertEqual(400, response.status_code)
        self.assertIn('JSON object', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
