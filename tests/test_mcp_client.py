import io
import json
import unittest
from unittest import mock

from mcp_server.api_client import ApiClientError, ArxivApiClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode('utf-8'))

    def __exit__(self, exc_type, exc, traceback):
        return False


class ApiClientTests(unittest.TestCase):
    def test_encodes_filters_and_legacy_arxiv_ids(self):
        client = ArxivApiClient('https://example.test/api/v1')
        with mock.patch('mcp_server.api_client.urlopen', return_value=FakeResponse({'ok': True})) \
                as urlopen:
            client.papers(keyword='schur functions', limit=10)
            client.paper('math/0601001')
        first_url = urlopen.call_args_list[0].args[0].full_url
        second_url = urlopen.call_args_list[1].args[0].full_url
        self.assertIn('keyword=schur+functions', first_url)
        self.assertTrue(second_url.endswith('/papers/math/0601001'))

    def test_wraps_connection_errors(self):
        client = ArxivApiClient('https://example.test/api/v1')
        with mock.patch(
                'mcp_server.api_client.urlopen',
                side_effect=TimeoutError('slow')), self.assertRaises(ApiClientError):
            client.status()


if __name__ == '__main__':
    unittest.main()
