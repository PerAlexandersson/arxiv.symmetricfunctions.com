import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from doi_review_client import call_api, create_token, main


class ReviewClientTests(unittest.TestCase):
    def test_credentials_are_private_and_never_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'token'
            result = create_token(file, 'test-agent')
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(file.read_text().strip(), str(result))
            self.assertNotIn(file.read_text().strip(), Path(result['server_config_file']).read_text())
            with self.assertRaises(ValueError):
                create_token(file, 'test-agent')

    def test_decisions_are_dry_run_unless_explicitly_applied(self):
        with mock.patch('doi_review_client.call_api') as call, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['decide', '3', 'approve', '--review-token', 'a' * 64,
                                   '--reason', 'Title and authors agree.']), 0)
        call.assert_not_called()

    def test_client_requires_https_private_token_and_disallows_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'token'
            create_token(file, 'test-agent')
            with self.assertRaises(ValueError):
                call_api('http://example.com/api', file, 'GET', '/candidates')
            file.chmod(0o644)
            with self.assertRaises(ValueError):
                call_api('https://example.com/api', file, 'GET', '/candidates')
            file.chmod(0o600)
            with mock.patch('doi_review_client.requests.request') as request:
                request.return_value.status_code = 200
                request.return_value.json.return_value = {'data': []}
                self.assertEqual(call_api('https://example.com/api', file, 'GET', '/candidates'), {'data': []})
                self.assertFalse(request.call_args.kwargs['allow_redirects'])
                self.assertNotIn(file.read_text().strip(), request.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
