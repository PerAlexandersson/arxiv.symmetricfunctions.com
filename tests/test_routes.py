import importlib
import os
import sys
import tempfile
import unittest
from datetime import date
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
    if not os.environ.get(_key):
        os.environ[_key] = _value

import config

config.DB_CONFIG['password'] = os.environ['DB_PASSWORD']
config.FLASK_CONFIG['SECRET_KEY'] = os.environ['FLASK_SECRET_KEY']
config.ADMIN_PASSWORD = os.environ['ADMIN_PASSWORD']
config.FETCH_SECRET = os.environ['FETCH_SECRET']

with mock.patch('requests.get') as _mock_get, \
        mock.patch('pymysql.connect',
                   side_effect=pymysql.err.OperationalError('DB disabled in tests')):
    _mock_get.return_value.ok = True
    _mock_get.return_value.json.return_value = {}
    app_module = importlib.import_module('app')


class FakeCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None, lastrowid=1):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.lastrowid = lastrowid
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return self.fetchall_values.pop(0) if self.fetchall_values else []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.commit_count = 0
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True
        self.commit_count += 1

    def rollback(self):
        self.rolled_back = True


class RouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app_module.app.test_client()

    def test_search_arxiv_url_redirects_to_paper(self):
        cursor = FakeCursor()
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value='2607.01572v1'):
            resp = self.client.get('/search?q=https://arxiv.org/abs/2607.01572v1')

        self.assertEqual(302, resp.status_code)
        self.assertTrue(resp.headers['Location'].endswith('/paper/2607.01572v1'))

    def test_search_bibtex_key_renders_matching_paper(self):
        cursor = FakeCursor(fetchone_values=[None, None])
        paper = {
            'id': 7,
            'arxiv_id': '2401.00001',
            'title': 'Eulerian Polynomials in Disguise',
            'abstract': 'A test abstract.',
            'published_date': date(2024, 1, 2),
            'updated_date': date(2024, 1, 3),
            'journal_ref': None,
            'doi': None,
            'publication_url': None,
            'publication_venue_key': None,
            'publication_status': None,
            'comment': None,
            'primary_category': 'math.CO',
            'authors': ['Christos A. Athanasiadis', 'Tanja K. Wagner'],
            'keywords': [],
        }

        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None), \
                mock.patch.object(app_module, '_papers_matching_bibtex_key',
                                  return_value=[paper]), \
                mock.patch.object(app_module, '_latest_search_date',
                                  return_value=date(2024, 1, 2)), \
                mock.patch.object(app_module, 'attach_keywords'):
            resp = self.client.get('/search?q=AthanasiadisWagner2024')

        html = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('Eulerian Polynomials in Disguise', html)
        self.assertIn('data-action="copy-bibtex"', html)
        self.assertIn('href="/paper/2401.00001" data-action="copy-share-link"', html)
        self.assertIn('href="/paper/2401.00001"', html)

    def test_search_exact_author_redirects_to_author_page(self):
        cursor = FakeCursor(fetchone_values=[{'slug': 'ada-lovelace'}])
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None):
            resp = self.client.get('/search?q=Ada%20Lovelace')

        self.assertEqual(302, resp.status_code)
        self.assertTrue(resp.headers['Location'].endswith('/author/ada-lovelace'))

    def test_search_exact_keyword_redirects_to_keyword_page(self):
        cursor = FakeCursor(fetchone_values=[None, {'phrase': 'schur functions'}])
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None):
            resp = self.client.get('/search?q=schur%20functions')

        self.assertEqual(302, resp.status_code)
        self.assertTrue(resp.headers['Location'].endswith('/keyword/schur%20functions'))

    def test_search_relevance_uses_author_text_keyword_ordering(self):
        cursor = FakeCursor(
            fetchone_values=[None, None, {'count': 2}],
            fetchall_values=[[
                {
                    'id': 3,
                    'arxiv_id': '2401.00003',
                    'title': 'Schur Graphs from Authors',
                    'abstract': 'A test abstract.',
                    'published_date': date(2024, 1, 4),
                    'updated_date': date(2024, 1, 4),
                    'journal_ref': None,
                    'doi': None,
                    'publication_url': None,
                    'publication_venue_key': None,
                    'publication_status': None,
                    'comment': None,
                    'primary_category': 'math.CO',
                    'authors': ['Ada Lovelace'],
                    'keywords': [],
                },
            ]],
        )
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None), \
                mock.patch.object(app_module, '_papers_matching_bibtex_key',
                                  return_value=None), \
                mock.patch.object(app_module, '_latest_search_date',
                                  return_value=date(2024, 1, 4)), \
                mock.patch.object(app_module, 'attach_authors'), \
                mock.patch.object(app_module, 'attach_keywords'):
            resp = self.client.get('/search?q=schur%20graph')

        html = resp.get_data(as_text=True)
        final_query = cursor.queries[-1][0]
        self.assertEqual(200, resp.status_code)
        self.assertIn('<mark class="search-hit">Schur</mark>', html)
        self.assertIn('<mark class="search-hit">Graph</mark>s from Authors', html)
        self.assertIn(
            'ORDER BY author_match DESC, keyword_match DESC, text_score DESC, '
            'kw_score DESC, '
            'p.published_date DESC, p.id DESC',
            final_query,
        )
        self.assertIn('LEFT JOIN keyword_aliases ka', final_query)

    def test_highlight_terms_filter_escapes_input(self):
        rendered = str(app_module.highlight_terms_filter(
            '<script>Schur</script>',
            ['schur'],
        ))

        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('<mark class="search-hit">Schur</mark>', rendered)
        self.assertNotIn('<script>', rendered)

    def test_search_date_sort_uses_date_ordering(self):
        cursor = FakeCursor(
            fetchone_values=[None, None, {'count': 0}],
            fetchall_values=[[]],
        )
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None), \
                mock.patch.object(app_module, '_papers_matching_bibtex_key',
                                  return_value=None), \
                mock.patch.object(app_module, '_latest_search_date',
                                  return_value=date(2024, 1, 4)), \
                mock.patch.object(app_module, 'attach_authors'), \
                mock.patch.object(app_module, 'attach_keywords'):
            resp = self.client.get('/search?q=schur%20graph&sort=date')

        final_query = cursor.queries[-1][0]
        self.assertEqual(200, resp.status_code)
        self.assertIn('ORDER BY p.published_date DESC, p.id DESC', final_query)

    def test_paper_detail_renders_uniform_action_row(self):
        paper = {
            'id': 11,
            'arxiv_id': '2607.01572v1',
            'title': 'A Test Paper',
            'abstract': 'An abstract.',
            'published_date': date(2026, 7, 1),
            'updated_date': date(2026, 7, 2),
            'comment': None,
            'journal_ref': None,
            'doi': None,
            'doi_status': None,
            'primary_category': 'math.CO',
            'publication_url': None,
            'publication_venue_key': None,
            'publication_status': None,
            'editor_note': None,
        }
        cursor = FakeCursor(
            fetchone_values=[paper],
            fetchall_values=[[], [{'category': 'math.CO'}]],
        )

        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, 'get_paper_authors',
                                  return_value=['Ada Lovelace']):
            resp = self.client.get('/paper/2607.01572v1')

        html = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('data-action="copy-share-link"', html)
        self.assertIn('href="/paper/2607.01572v1" data-action="copy-share-link"', html)
        self.assertIn('data-action="copy-bibtex"', html)
        self.assertIn('https://arxiv.org/pdf/2607.01572v1', html)
        self.assertIn('https://arxiv.org/abs/2607.01572v1', html)
        self.assertIn('Sign in to star papers', html)

    def test_bibtex_api_uses_canonical_versioned_arxiv_id(self):
        paper = {
            'id': 12,
            'arxiv_id': '2607.01572v1',
            'title': 'A Test Paper',
            'published_date': date(2026, 7, 1),
            'journal_ref': None,
            'doi': None,
        }
        cursor = FakeCursor(fetchone_values=[paper])

        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value='2607.01572v1'), \
                mock.patch.object(app_module, 'get_paper_authors',
                                  return_value=['Ada Lovelace']):
            resp = self.client.get('/api/bibtex/2607.01572')

        bib = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('eprint = {2607.01572v1}', bib)
        self.assertIn('url = {https://arxiv.org/abs/2607.01572v1}', bib)

    def test_legacy_arxiv_id_can_be_starred_idempotently(self):
        import lists as lists_module

        cursor = FakeCursor(fetchone_values=[{'exists': 1}, {'id': 4, 'name': 'Starred'}])
        conn = FakeConnection(cursor)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7

        with mock.patch.object(lists_module, 'get_db_connection', return_value=conn):
            resp = self.client.post(
                '/api/lists/star/math/0601001',
                data={'starred': 'true'},
            )

        self.assertEqual(200, resp.status_code)
        self.assertEqual({'starred': True, 'saved': True}, resp.get_json())
        self.assertEqual(1, conn.commit_count)
        self.assertTrue(any('INSERT IGNORE INTO user_lists' in query
                            for query, _ in cursor.queries))

    def test_star_requires_explicit_desired_state(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7
        resp = self.client.post('/api/lists/star/2401.00001')
        self.assertEqual(400, resp.status_code)
        self.assertIn('starred must be true or false', resp.get_json()['error'])

    def test_unstar_without_starred_list_does_not_create_one(self):
        import lists as lists_module

        cursor = FakeCursor(fetchone_values=[{'exists': 1}, None])
        conn = FakeConnection(cursor)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7

        with mock.patch.object(lists_module, 'get_db_connection', return_value=conn):
            resp = self.client.post(
                '/api/lists/star/2401.00001',
                data={'starred': 'false'},
            )

        self.assertEqual(200, resp.status_code)
        self.assertEqual({'starred': False, 'saved': False}, resp.get_json())
        self.assertEqual(0, conn.commit_count)
        self.assertFalse(any('INSERT INTO user_categories' in query
                             for query, _ in cursor.queries))

    def test_save_to_new_list_commits_category_and_paper_together(self):
        import lists as lists_module

        cursor = FakeCursor(fetchone_values=[{'exists': 1}], lastrowid=12)
        conn = FakeConnection(cursor)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7

        with mock.patch.object(lists_module, 'get_db_connection', return_value=conn):
            resp = self.client.post(
                '/api/lists/save',
                data={'arxiv_id': '2401.00001', 'new_name': 'Read later'},
            )

        self.assertEqual(200, resp.status_code)
        self.assertEqual(1, conn.commit_count)
        self.assertEqual('Read later', resp.get_json()['category_name'])
        self.assertTrue(any('INSERT INTO user_categories' in query
                            for query, _ in cursor.queries))
        self.assertTrue(any('INSERT IGNORE INTO user_lists' in query
                            for query, _ in cursor.queries))

    def test_paper_detail_renders_existing_star_state(self):
        paper = {
            'id': 13,
            'arxiv_id': '2607.01572v1',
            'title': 'A Starred Paper',
            'abstract': 'An abstract.',
            'published_date': date(2026, 7, 1),
            'updated_date': date(2026, 7, 2),
            'comment': None,
            'journal_ref': None,
            'doi': None,
            'doi_status': None,
            'primary_category': 'math.CO',
            'publication_url': None,
            'publication_venue_key': None,
            'publication_status': None,
            'editor_note': None,
        }
        cursor = FakeCursor(
            fetchone_values=[paper],
            fetchall_values=[
                [],
                [{'category': 'math.CO'}],
                [],
                [],
                [{'arxiv_id': '2607.01572v1', 'is_starred': 1}],
            ],
        )
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7
            sess['user_name'] = 'Ada Lovelace'

        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, 'get_paper_authors',
                                  return_value=['Ada Lovelace']):
            resp = self.client.get('/paper/2607.01572v1')

        html = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('star-btn starred', html)
        self.assertIn('aria-pressed="true"', html)

    def test_fetch_rejects_query_string_secret(self):
        resp = self.client.post('/fetch?key=test-fetch-secret', data={'days': '1'})
        self.assertEqual(403, resp.status_code)

    def test_logout_requires_post(self):
        self.assertEqual(405, self.client.get('/logout').status_code)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7
        self.assertEqual(302, self.client.post('/logout').status_code)

    def test_authenticated_header_places_logout_beside_username(self):
        cursor = FakeCursor(fetchall_values=[[], [], []])
        with self.client.session_transaction() as sess:
            sess['user_id'] = 7
            sess['user_name'] = 'Ada Lovelace'

        with self.client.session_transaction() as sess, \
                app_module.app.test_request_context('/'):
            app_module.session.update(sess)
            with mock.patch.object(app_module, 'get_db_connection',
                                   return_value=FakeConnection(cursor)):
                html = app_module.render_template('base.html')

        session_start = html.index('<div class="site-session">')
        session_end = html.index('</div>', session_start)
        session_html = html[session_start:session_end]
        nav_start = html.index('<span class="nav-icons">')

        self.assertIn('Ada Lovelace', session_html)
        self.assertIn('site-logout-form', session_html)
        self.assertIn('aria-label="Sign out"', session_html)
        self.assertEqual(1, html.count('aria-label="Sign out"'))
        self.assertLess(html.index('site-logout-form'), nav_start)

    def test_bibtex_json_fallback_uses_arxiv_entry_version(self):
        class FakeResponse:
            text = """<?xml version="1.0" encoding="UTF-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom"
                  xmlns:arxiv="http://arxiv.org/schemas/atom">
              <entry>
                <id>http://arxiv.org/abs/2607.04999v1</id>
                <title>Cluster parking functions II</title>
                <published>2026-07-07T00:00:00Z</published>
                <author><name>Matthieu Josuat-Vergès</name></author>
              </entry>
            </feed>"""

            def raise_for_status(self):
                pass

        cursor = FakeCursor()
        with mock.patch.object(app_module, 'get_db_connection',
                               return_value=FakeConnection(cursor)), \
                mock.patch.object(app_module, '_resolve_paper_arxiv_id',
                                  return_value=None), \
                mock.patch.object(app_module.requests, 'get',
                                  return_value=FakeResponse()):
            resp = self.client.get('/api/bibtex.json?id=2607.04999')

        data = resp.get_json()
        self.assertEqual(200, resp.status_code)
        self.assertIn('eprint = {2607.04999v1}', data['arxiv'])
        self.assertIn('url = {https://arxiv.org/abs/2607.04999v1}', data['arxiv'])

    def test_admin_cron_status_reads_configured_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / 'arxiv-update.log'
            log_path.write_text(
                '[2026-07-04T01:00:00+00:00] Starting scheduled arXiv update\n'
                '[2026-07-04T01:01:00+00:00] Scheduled arXiv update complete\n'
            )
            with self.client.session_transaction() as sess:
                sess['admin_logged_in'] = True
            with mock.patch.dict(os.environ, {'ARXIV_CRON_LOG': str(log_path)}):
                resp = self.client.get('/admin/cron')

        html = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('Last run completed', html)
        self.assertIn('Scheduled arXiv update complete', html)

    def test_admin_cron_status_falls_back_to_legacy_fetch_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / 'fetch.log'
            log_path.write_text('legacy fetch output\n')
            with self.client.session_transaction() as sess:
                sess['admin_logged_in'] = True
            with mock.patch.dict(os.environ, {
                'ARXIV_CRON_LOG_DIR': tmp,
                'ARXIV_CRON_LOG': '',
            }):
                resp = self.client.get('/admin/cron')

        html = resp.get_data(as_text=True)
        self.assertEqual(200, resp.status_code)
        self.assertIn('fetch.log', html)
        self.assertIn('legacy fetch output', html)

    def test_admin_doi_reassign_clears_conflicts_and_approves_candidate(self):
        import admin as admin_module

        cursor = FakeCursor(
            fetchone_values=[{
                'paper_id': 10,
                'doi': '10.1000/example',
                'confidence': 0.91,
            }],
            fetchall_values=[
                [{
                    'paper_id': 20,
                    'arxiv_id': '2401.00020',
                    'title': 'Old DOI Assignment',
                    'doi_status': 'auto',
                }],
                [{'status': 'approved', 'cnt': 1}],
            ],
        )
        conn = FakeConnection(cursor)
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        with mock.patch.object(admin_module, 'get_db_connection',
                               return_value=conn), \
                mock.patch.object(admin_module, '_mark_index_cache_dirty'):
            resp = self.client.post('/admin/dois/99/reassign')

        data = resp.get_json()
        queries = [q for q, _ in cursor.queries]
        self.assertEqual(200, resp.status_code)
        self.assertTrue(data['ok'])
        self.assertTrue(conn.committed)
        self.assertEqual('2401.00020', data['reassigned_from'][0]['arxiv_id'])
        self.assertTrue(any('SET doi = NULL' in q for q in queries))
        self.assertTrue(any("SET status = 'rejected'" in q for q in queries))
        self.assertTrue(any("doi_status = 'verified'" in q for q in queries))
        self.assertTrue(any("SET status = 'approved'" in q for q in queries))


if __name__ == '__main__':
    unittest.main()
