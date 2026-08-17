# Handoff

## Current scope

Public read-only REST access and a repository-local MCP adapter for agent
review of recent combinatorics papers, plus a small authenticated-header layout
fix requested after deployment.

## Status

- The database migration and REST application are live.
- The REST API lives under `/api/v1` with OpenAPI documentation.
- The optional MCP server lives under `mcp_server/` and calls the REST API.
- arXiv base IDs and revisions are now modeled separately by the fetcher.
- The complete unit suite passes (63 tests on 2026-08-16).
- New API/MCP Python files pass Ruff, the OpenAPI 3.1 document validates, and
  the MCP 2.x client discovers all five tools plus the review prompt.
- GitHub commit `5818238` contains the implementation and was deployed on
  2026-08-16.
- The authenticated logout control has been moved out of the wrapping icon row
  and placed beside the displayed user name. The authenticated-header regression
  test and complete unit suite pass. Commits `f37af87` and `ce65aa0` are pushed
  and deployed; the latter bumps the shared stylesheet URL to avoid stale browser
  caches.

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
- After the header deployment, the homepage and `/api/v1/status` still return
  200, production serves `shared.css?v=3`, and the deployed authenticated
  template contains the new `site-session`/`site-logout-form` structure.

## Next step

Register or publish the repository-local MCP server in the desired agent hosts.

No assessment/write-back API exists yet; adding that requires an explicit
authentication and editorial-queue design.

## Live database resync, 2026-08-17

A fresh transactional production dump was downloaded and validated at
`/home/dev/.cache/arxiv.symmetricfunctions.com/backups/live-sync-20260817.sql.gz`.
It contains 18 tables, passes `gzip -t`, and has SHA-256 checksum
`0cf9925106095ef6b9e7a43fb5145aadcc9955edeb3035d4193fafbf629ac32c`.
The production preflight counts were 80,447 papers, 3 users, 180 user-list
rows, and 965 keywords.

The local import completed successfully on 2026-08-17 through the shared
MariaDB service.  Before the import, the previous local database was backed up
to
`/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-live-sync-20260817T122147Z.sql.gz`.
The backup passes `gzip -t` and has SHA-256 checksum
`0cda733d0ae6ff66659071f1a079cd7b4581da429ad88b9e3811342b81bd5ddb`.

Post-import validation found all 18 tables and matched the production counts
exactly: 80,447 papers, 3 users, 180 user-list rows, and 965 keywords.  The
local `arxiv_frontend` database is synchronized with the verified live dump.

## Local DOI queue triage, 2026-08-17

The author matcher now compares complete normalized name tokens as well as
surnames.  It handles reordered names, multiword surnames, initials, and one
added or omitted name part without treating a shared surname alone as an
identity match.  Regression tests cover examples taken from the pending queue.

The new `src/doi_triage.py` command is read-only by default.  It caches and
reports Semantic Scholar arXiv-to-DOI evidence, detects both assigned and
pending DOI conflicts, and can require a current Crossref metadata and
chronology check.  Its write modes recheck all conflicts inside the database
transaction and retain rejected candidates as an audit trail.

Three guarded passes were applied to the local database:

- 160 exact Semantic Scholar DOI agreements with strong metadata;
- 74 alternative DOIs independently linked by Semantic Scholar and confirmed
  against current Crossref metadata;
- 18 exact title-and-author matches confirmed directly against current
  Crossref metadata after the author-matcher fix.

In total, 252 papers received an automatically sourced DOI.  The pending queue
fell from 2,491 to 2,239.  Postflight validation found all 252 assignments,
zero duplicate assignments among the changed DOIs, zero remaining pending
candidates for the changed papers, and zero candidate orphans.  The complete
unit suite passes (76 tests).  Production was not changed.

The recovery checkpoints are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-triage-20260817T124907Z.sql.gz
sha256 846c84e8d032131838d35a0eac1f47d4642d9215051734cf5e745888584cb34a

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-replacements-20260817T125204Z.sql.gz
sha256 9b18ef96482dc651e4b729b4347b4da16d4317ab172e4493eb5863eb17ddb7ff

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-metadata-20260817T125523Z.sql.gz
sha256 a0471b4a08ff9db9a496e74137f6b1d8115d83b9059713eb6fb528349c32f3ac
```

The final read-only report is
`/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/final-pending-20260817.json`.
The remaining queue consists of 2,015 records without an independent DOI,
72 exact DOI links with weak metadata, 26 exact-link conflicts, 21 source
disagreements, 103 replacement records lacking sufficient Crossref support,
one replacement conflict, and one exact metadata mismatch.  These records were
left unchanged for slower review or stronger evidence.
