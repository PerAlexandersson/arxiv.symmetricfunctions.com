# Handoff

## Current scope

Public read-only REST access and a repository-local MCP adapter for agent
review of recent combinatorics papers.

## Status

- The database migration and REST application are live.
- The REST API lives under `/api/v1` with OpenAPI documentation.
- The optional MCP server lives under `mcp_server/` and calls the REST API.
- arXiv base IDs and revisions are now modeled separately by the fetcher.
- The complete unit suite passes (62 tests on 2026-08-16).
- New API/MCP Python files pass Ruff, the OpenAPI 3.1 document validates, and
  the MCP 2.x client discovers all five tools plus the review prompt.
- GitHub commit `5818238` contains the implementation and was deployed on
  2026-08-16.

## Production migration

Applied `database/migrate_arxiv_identity.sql` on 2026-08-16 after a read-only
audit. The verified server-side backup is:

```text
backups/pre-rest-api-20260816T161157Z.sql.gz
sha256 ca01e59a7a6bd68bc4a2d772667d2649a3d07e52f92eb9c1fecf9132f786feea
```

The audit found 80,542 physical rows representing 80,421 logical papers. The
migration retained the newest revision's arXiv metadata, authors, and
categories; carried editorial metadata forward; and removed 121 redundant
revision rows. Postflight checks show:

- 80,421 paper rows and 80,421 distinct non-null base IDs;
- zero saved-list orphans;
- the unique base-ID and three cursor indexes are present;
- the existing homepage still returns HTTP 200.

## Live verification

- `/api/v1/`, `/status`, `/papers`, `/keywords`, and `/openapi.yaml` return 200.
- Cursor continuation returned a disjoint second page.
- Modern and actual legacy IDs (`math/0001175`) resolve through paper detail.
- REST search returned results in roughly 0.1 seconds in smoke tests.
- The MCP 2.x client called `get_status` and `list_recent_papers` successfully
  against the live REST API.
- The homepage and HTML search return 200, and the recent Passenger log has no
  traceback or error.

## Next step

Register or publish the repository-local MCP server in the desired agent hosts.

No assessment/write-back API exists yet; adding that requires an explicit
authentication and editorial-queue design.
