"""MCP tools for discovering and reviewing recent combinatorics papers.

Run over stdio (the default for local agent hosts):

    python -m mcp_server.server

Or expose a stateless Streamable HTTP endpoint:

    python -m mcp_server.server --transport streamable-http --port 8000
"""

import argparse
from datetime import datetime, timedelta, timezone
from typing import Literal

from mcp.server import MCPServer

from .api_client import ArxivApiClient

mcp = MCPServer(
    'arxiv-symmetricfunctions',
    version='1.0.0',
    instructions=(
        'Use these read-only tools to inspect recent combinatorics papers. '
        'Judge mathematical relevance yourself; symcat_targets are hints from '
        'the site keyword catalogue, not editorial decisions.'
    ),
)


def _client():
    return ArxivApiClient()


@mcp.tool()
def get_status() -> dict:
    """Report API freshness and the most recently available paper dates."""
    return _client().status()


@mcp.tool()
def list_recent_papers(
    days: int = 7,
    limit: int = 25,
    date_kind: Literal['published', 'ingested', 'changed'] = 'published',
    category: str = '',
    keyword: str = '',
) -> dict:
    """List recent papers using a publication, ingestion, or change window."""
    if not 1 <= days <= 3660:
        raise ValueError('days must be between 1 and 3660')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    params = {
        'limit': limit,
        'order': date_kind,
        'category': category,
        'keyword': keyword,
    }
    params[f'{date_kind}_after'] = since.isoformat()
    return _client().papers(**params)


@mcp.tool()
def search_papers(
    query: str,
    limit: int = 25,
    category: str = '',
    keyword: str = '',
    published_after: str = '',
) -> dict:
    """Search titles, abstracts, authors, and curated keywords."""
    if not query.strip():
        raise ValueError('query must not be empty')
    return _client().papers(
        q=query,
        limit=limit,
        order='published',
        category=category,
        keyword=keyword,
        published_after=published_after,
    )


@mcp.tool()
def get_paper(arxiv_id: str) -> dict:
    """Get complete metadata and SymCat topic hints for one arXiv paper."""
    return _client().paper(arxiv_id)


@mcp.tool()
def list_keywords(limit: int = 100) -> dict:
    """List the site's active curated keywords and their paper counts."""
    return _client().keywords(limit=limit)


@mcp.prompt()
def review_recent_papers(days: int = 7) -> str:
    """Create a careful editorial-review workflow for recent papers."""
    return f"""Review combinatorics papers from the last {days} days.

1. Call list_recent_papers with date_kind='published'.
2. Read titles and abstracts; use get_paper where more metadata is useful.
3. Identify papers genuinely relevant to symmetric functions or existing
   symmetricfunctions.com topics. Treat symcat_targets only as hints.
4. Return a short ranked list with relevance, mathematical reason, confidence,
   and suggested SymCat target pages. Put uncertain items in a separate watch
   list. Do not edit symmetricfunctions.com or claim a paper was added.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--transport', choices=('stdio', 'streamable-http'), default='stdio'
    )
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args(argv)
    if args.transport == 'stdio':
        mcp.run()
    else:
        mcp.run(
            transport='streamable-http',
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )


if __name__ == '__main__':
    main()
