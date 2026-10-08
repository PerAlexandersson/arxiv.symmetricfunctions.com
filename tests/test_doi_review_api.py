import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from flask import Flask
from flask_wtf.csrf import CSRFProtect
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import doi_review_api as api

TOKEN = 'test-only-review-token-' + 'x' * 40
SNAPSHOT = 'a' * 64


def make_app():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-csrf-key',
                      DOI_REVIEW_TOKEN_SHA256=hashlib.sha256(TOKEN.encode()).hexdigest(),
                      DOI_REVIEW_ACTOR='test-agent')
    csrf = CSRFProtect(app)
    csrf.exempt(api.review_api)
    app.register_blueprint(api.review_api)
    return app


def candidate(**overrides):
    item = dict(id=3, paper_id=7, doi='10.1234/example', confidence=.94,
                current_doi=None, doi_status=None, status='pending',
                conflicts=[], review_token=SNAPSHOT)
    item.update(overrides)
    return item


class ReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + TOKEN}
        self.conn = mock.Mock()
        self.cursor = self.conn.cursor.return_value
        self.cursor.fetchone.return_value = None
        self.db_patch = mock.patch.object(api, 'get_db_connection', return_value=self.conn)
        self.db = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def post(self, decision='approve', **changes):
        payload = dict(decision=decision, reason='Title and authors agree.', review_token=SNAPSHOT)
        payload.update(changes)
        return self.client.post('/api/v1/doi-review/candidates/3/decision',
                                json=payload, headers=self.headers)

    def test_authentication_is_dedicated_disabled_by_default_and_never_cookie_based(self):
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'X-Fetch-Secret': TOKEN}):
            response = self.client.get('/api/v1/doi-review/candidates?token=' + TOKEN, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            self.assertNotIn('Access-Control-Allow-Origin', response.headers)
            self.assertNotIn(TOKEN, response.text)
        self.app.config['DOI_REVIEW_TOKEN_SHA256'] = ''
        self.assertEqual(self.client.get('/api/v1/doi-review/candidates', headers=self.headers).status_code, 503)
        self.db.assert_not_called()

    def test_no_csrf_exemption_can_bypass_bearer_auth(self):
        response = self.client.post('/api/v1/doi-review/candidates/3/decision', json={})
        self.assertEqual(response.status_code, 401)
        self.db.assert_not_called()

    def test_input_validation_precedes_any_database_operation(self):
        for payload in (None, [], {}, {'decision': 'approve'},
                        {'decision': 'approve', 'reason': '', 'review_token': SNAPSHOT},
                        {'decision': 'reassign', 'reason': 'x', 'review_token': SNAPSHOT},
                        {'decision': 'approve', 'reason': 'x', 'review_token': 'bad'}):
            response = self.client.post('/api/v1/doi-review/candidates/3/decision',
                                        data=json.dumps(payload), content_type='application/json',
                                        headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/v1/doi-review/candidates/3/decision',
                                         data='broken', headers=self.headers).status_code, 415)
        self.assertEqual(self.client.post('/api/v1/doi-review/candidates/3/decision',
                                         data='{', content_type='application/json',
                                         headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/doi-review/candidates/3/decision',
                                         data='x' * 17000, headers=self.headers).status_code, 413)
        self.db.assert_not_called()

    def test_queue_is_bounded_and_uses_stable_id_pagination(self):
        for query in ('limit=101', 'limit=0', 'after_id=-1', 'after_id=abc'):
            self.assertEqual(self.client.get('/api/v1/doi-review/candidates?' + query,
                                            headers=self.headers).status_code, 400)
        self.cursor.fetchall.return_value = [{'id': 3}, {'id': 9}, {'id': 10}]
        with mock.patch.object(api, '_enrich', side_effect=lambda cursor, rows: rows):
            response = self.client.get('/api/v1/doi-review/candidates?limit=2&after_id=2',
                                       headers=self.headers)
        self.assertEqual(response.json, {'data': [{'id': 3}, {'id': 9}], 'next_after_id': 9})
        self.assertEqual(self.cursor.execute.call_args.args[1], (2, 3))
        self.assertIn("dc.status = 'pending'", self.cursor.execute.call_args.args[0])

    def test_approval_is_atomic_with_audit_and_cache_invalidation(self):
        with mock.patch.object(api, '_candidate', return_value=candidate()):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.conn.begin.assert_called_once()
        self.conn.commit.assert_called_once()
        queries = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertTrue(any('UPDATE papers' in query for query in queries))
        self.assertTrue(any('UPDATE site_stats' in query for query in queries))
        self.assertTrue(any('INSERT INTO doi_review_events' in query for query in queries))
        self.assertIn('test-agent', self.cursor.execute.call_args.args[1])
        self.assertNotIn(TOKEN, repr(self.cursor.execute.call_args_list))

    def test_rejection_does_not_modify_paper_or_unrelated_candidates(self):
        with mock.patch.object(api, '_candidate', return_value=candidate()):
            response = self.post('reject')
        self.assertEqual(response.status_code, 200)
        queries = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertFalse(any('UPDATE papers' in query for query in queries))
        self.assertFalse(any('UPDATE site_stats' in query for query in queries))
        self.conn.commit.assert_called_once()

    def test_stale_review_and_conflicting_assignments_are_not_writes(self):
        for item in (candidate(review_token='b' * 64), candidate(status='rejected'),
                     candidate(current_doi='10.1234/other'), candidate(doi_status='skipped'),
                     candidate(conflicts=[{'paper_id': 99}])):
            self.cursor.execute.reset_mock()
            with mock.patch.object(api, '_candidate', return_value=item):
                self.assertEqual(self.post().status_code, 409)
            self.assertFalse(any('UPDATE ' in c.args[0] for c in self.cursor.execute.call_args_list))
        self.conn.commit.assert_not_called()
        self.assertEqual(self.conn.rollback.call_count, 5)

    def test_exact_retry_returns_success_without_second_write(self):
        self.cursor.fetchone.return_value = dict(decision='approve', reason='Title and authors agree.',
                                                 reviewer='test-agent', review_token=SNAPSHOT)
        with mock.patch.object(api, '_candidate', return_value=candidate(
                status='approved', current_doi='10.1234/example')):
            self.assertTrue(self.post().json['repeated'])
            self.assertEqual(self.post('reject').status_code, 409)
        self.conn.commit.assert_not_called()

    def test_audit_failure_rolls_back_assignment(self):
        def execute(sql, params=None):
            if 'INSERT INTO doi_review_events' in sql:
                raise pymysql.err.OperationalError('test failure')
        self.cursor.execute.side_effect = execute
        with mock.patch.object(api, '_candidate', return_value=candidate()):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()
        self.assertNotIn('test failure', response.text)

    def test_missing_candidate_and_assigned_rejection(self):
        with mock.patch.object(api, '_candidate', side_effect=api.ReviewError('not_found', 'Missing.', 404)):
            self.assertEqual(self.post().status_code, 404)
        with mock.patch.object(api, '_candidate', return_value=candidate(current_doi='10.1234/example')):
            self.assertEqual(self.post('reject').status_code, 409)

    def test_evidence_token_changes_when_paper_authors_or_conflicts_change(self):
        row = dict(id=3, paper_id=7, arxiv_id='2401.00001v2', doi='10.1234/example',
                   confidence=.94, paper_title='A title', current_doi=None)
        def enrich(authors, conflicts):
            cursor = mock.Mock()
            cursor.fetchall.side_effect = [authors, conflicts]
            return api._enrich(cursor, [row])[0]
        first = enrich([{'paper_id': 7, 'name': 'Jane Doe'}], [])
        second = enrich([{'paper_id': 7, 'name': 'John Doe'}], [])
        third = enrich([{'paper_id': 7, 'name': 'Jane Doe'}],
                       [{'paper_id': 8, 'doi': '10.1234/EXAMPLE', 'title': 'Other', 'arxiv_id': '2402.00001'}])
        self.assertNotEqual(first['review_token'], second['review_token'])
        self.assertNotEqual(first['review_token'], third['review_token'])
        self.assertEqual(third['conflicts'][0]['paper_id'], 8)
        row['paper_comment'] = 'Extended abstract submitted to FPSAC'
        fourth = enrich([{'paper_id': 7, 'name': 'Jane Doe'}], [])
        self.assertNotEqual(first['review_token'], fourth['review_token'])
        self.assertIn('FPSAC', fourth['paper_comment'])


@unittest.skipUnless(os.getenv('DOI_REVIEW_TEST_DB_HOST'), 'opt-in temporary-table MariaDB test')
class MariaDbReviewTests(unittest.TestCase):
    def test_real_transaction_review_retry_and_stale_rollback(self):
        from config import DB_CONFIG
        cfg = dict(DB_CONFIG, host=os.environ['DOI_REVIEW_TEST_DB_HOST'])
        conn = pymysql.connect(**cfg, cursorclass=pymysql.cursors.DictCursor)
        self.addCleanup(conn.close)
        # Connection-local temporary tables shadow application names. No real rows are changed.
        with conn.cursor() as cur:
            cur.execute('''CREATE TEMPORARY TABLE papers (id INT PRIMARY KEY, arxiv_id TEXT,
                title TEXT, abstract TEXT, comment TEXT, editor_note TEXT,
                published_date DATE, journal_ref TEXT, doi VARCHAR(100),
                doi_status VARCHAR(20), doi_confidence DECIMAL(4,3)) ENGINE=InnoDB''')
            cur.execute('''CREATE TEMPORARY TABLE doi_candidates (id INT PRIMARY KEY, paper_id INT,
                doi VARCHAR(100), confidence DECIMAL(4,3), crossref_title TEXT, crossref_authors TEXT,
                crossref_year INT, status VARCHAR(20), reviewed_at DATETIME) ENGINE=InnoDB''')
            cur.execute('CREATE TEMPORARY TABLE authors (id INT PRIMARY KEY, name TEXT) ENGINE=InnoDB')
            cur.execute('CREATE TEMPORARY TABLE paper_authors (paper_id INT, author_id INT, author_order INT) ENGINE=InnoDB')
            cur.execute('''CREATE TEMPORARY TABLE site_stats (id INT PRIMARY KEY, cache_dirty_at DATETIME,
                cache_rebuild_after DATETIME, updated_at DATETIME) ENGINE=InnoDB''')
            migration = (Path(__file__).resolve().parents[1] / 'database/migrate_doi_review_events.sql').read_text()
            cur.execute(migration.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE'))
            cur.execute("INSERT INTO papers (id,arxiv_id,title,published_date) VALUES (7,'2401.00001','A title','2024-01-01')")
            cur.execute("INSERT INTO doi_candidates (id,paper_id,doi,confidence,status) VALUES (3,7,'10.1234/example',.94,'pending')")
            cur.execute("INSERT INTO site_stats (id) VALUES (1)")
        conn.commit()
        client = make_app().test_client()
        headers = {'Authorization': 'Bearer ' + TOKEN}
        with mock.patch.object(api, 'get_db_connection', return_value=conn):
            row = client.get('/api/v1/doi-review/candidates', headers=headers).json['data'][0]
            payload = {'decision': 'approve', 'reason': 'Integration fixture.', 'review_token': row['review_token']}
            with conn.cursor() as cur:
                cur.execute("UPDATE papers SET title='Changed' WHERE id=7")
            conn.commit()
            self.assertEqual(client.post('/api/v1/doi-review/candidates/3/decision', json=payload, headers=headers).status_code, 409)
            row = client.get('/api/v1/doi-review/candidates/3', headers=headers).json['data']
            payload['review_token'] = row['review_token']
            self.assertEqual(client.post('/api/v1/doi-review/candidates/3/decision', json=payload, headers=headers).status_code, 200)
            self.assertTrue(client.post('/api/v1/doi-review/candidates/3/decision', json=payload, headers=headers).json['repeated'])
        with conn.cursor() as cur:
            cur.execute('SELECT doi,doi_status FROM papers WHERE id=7')
            self.assertEqual(cur.fetchone(), {'doi': '10.1234/example', 'doi_status': 'verified'})
            cur.execute('SELECT COUNT(*) AS n FROM doi_review_events')
            self.assertEqual(cur.fetchone()['n'], 1)
            cur.execute('SELECT cache_dirty_at FROM site_stats WHERE id=1')
            self.assertIsNotNone(cur.fetchone()['cache_dirty_at'])


if __name__ == '__main__':
    unittest.main()
