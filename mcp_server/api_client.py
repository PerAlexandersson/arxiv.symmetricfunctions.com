"""Small standard-library client for the arXiv++ REST API."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = 'https://arxiv.symmetricfunctions.com/api/v1'


class ApiClientError(RuntimeError):
    """Raised when the remote REST API cannot satisfy an MCP tool call."""


class ArxivApiClient:
    def __init__(self, base_url=None, timeout=20):
        self.base_url = (
            base_url or os.getenv('ARXIV_API_BASE_URL') or DEFAULT_BASE_URL
        ).rstrip('/')
        self.timeout = timeout

    def _get(self, path, params=None):
        query = urlencode({
            key: value for key, value in (params or {}).items()
            if value not in (None, '')
        })
        url = f'{self.base_url}/{path.lstrip("/")}'
        if query:
            url += '?' + query
        request = Request(
            url,
            headers={
                'Accept': 'application/json',
                'User-Agent': 'arxiv-symmetricfunctions-mcp/1.0',
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode('utf-8'))
                message = payload.get('error', {}).get('message')
            except (
                AttributeError,
                OSError,
                TypeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                message = None
            raise ApiClientError(message or f'API returned HTTP {error.code}')
        except (URLError, TimeoutError) as error:
            raise ApiClientError(f'Could not reach the paper API: {error}')
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiClientError(f'Paper API returned invalid JSON: {error}')

    def status(self):
        return self._get('status')

    def papers(self, **params):
        return self._get('papers', params)

    def paper(self, arxiv_id):
        return self._get(f'papers/{quote(arxiv_id, safe="/")}')

    def keywords(self, limit=100):
        return self._get('keywords', {'limit': limit})
