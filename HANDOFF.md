# Handoff

## Current scope

Public read-only REST access and a repository-local MCP adapter for agent
review of recent combinatorics papers.

## Status

- The database migration is live; application code has not yet been deployed.
- The REST API lives under `/api/v1` with OpenAPI documentation.
- The optional MCP server lives under `mcp_server/` and calls the REST API.
- arXiv base IDs and revisions are now modeled separately by the fetcher.
- The complete unit suite passes (62 tests on 2026-08-16).
- New API/MCP Python files pass Ruff, the OpenAPI 3.1 document validates, and
  the MCP 2.x client discovers all five tools plus the review prompt.

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

## Next checks

1. Deploy the application code.
2. Smoke-test `/api/v1/status`, cursor pagination, a legacy arXiv ID, and one
   SymCat keyword target.
3. Publish or register the MCP server after the REST endpoint is live.

No assessment/write-back API exists yet; adding that requires an explicit
authentication and editorial-queue design.
