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

### Continued DOI backlog reduction

The first matcher/triage batch is committed as `0f5426e`.  Subsequent guarded
local passes added registration-agency-neutral DOI metadata through DOI content
negotiation, ignored arXiv's own `10.48550/arXiv.*` preprint identifiers, used
stronger author-list coverage for independently linked records, and compared
stale DOI conflicts against the paper that already owns the DOI.  Those passes
assigned 100 more publication DOIs and rejected 585 stale conflicting
candidates without changing any existing DOI assignment.

Journal-reference validation now compares the arXiv reference with live DOI
year, volume, page/article number, and venue metadata.  It accepts changed
publication titles only when the bibliography and authors corroborate the DOI.
It also excludes repository-copy identifiers from publication DOI replacement
and recognizes the Journal of Integer Sequences as a DOI-less venue.  The
general matcher now handles extra middle initials and does not reject a valid
journal publication merely because it predates a later arXiv upload.

The final guarded local pass assigned another 42 DOIs: 35 corroborated by
journal references, four independently linked replacements, and three exact
external links exposed by the improved author matcher.  It also rejected one
additional stale conflict and marked three Journal of Integer Sequences papers
as `skipped` rather than forcing false DOIs.

Through the journal-reference pass, 394 papers received publication DOIs, 586
stale candidates were rejected, and three DOI-less papers were skipped.  The
pending queue fell from 2,491 to 1,508.  Postflight checks found all 42
assignments from the last pass, no duplicate assignments among their DOIs, no
pending candidates on processed papers, and the expected DOI-less statuses.
That round's read-only classification contains 1,375 unresolved records and
133 guarded review cases; it proposes no further automatic changes. Production
was not changed.

A final near-exact pass fixed Crossref date selection so that the publication
date closest to the arXiv year is used rather than always preferring print over
online publication.  It approved one additional live-confirmed DOI whose title
differed only by the article “the.”  The aggregate is therefore 395 DOI
assignments, 586 stale-candidate rejections, three DOI-less skips, and 1,507
pending candidates.  The final read-only classification has 1,374 unresolved
records and 133 guarded review cases and proposes no further automatic
changes.  The final complete suite passes (94 tests).

Additional recovery checkpoints are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-round2-20260817T131002Z.sql.gz
sha256 2641dbae09e4dcd46165eeaebf6bd53eff8275321002f2992a248ff15492c0bc

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-conflicts-20260817T131156Z.sql.gz
sha256 31c3e460323b39ac5f20fad9ae15cabf6e8b07fa1f6555f0d7c8238adcaeda37

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-exact-external-20260817T131617Z.sql.gz
sha256 6785a0028250ec71d445185f2ba2aa7b93d56278a760f68ac455f4ae4069c1cf

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-journal-20260817T134500Z.sql.gz
sha256 25f8b3b97ad0fd26bf113019f281b6dd6d5157f436d452dd1938d0c83d334eb2

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-doi-near-exact-20260817T133100Z.sql.gz
sha256 11378c6748b07eed572620e9987958d19aefd3e671078866f364a9dc986f1813
```

The applied reports are under
`/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/` as
`backlog-round2-applied.json`, `conflicts-applied.json`,
`exact-external-applied.json`, `journal-applied.json`, and
`near-exact-applied.json`.  The final read-only report is
`final-round4-pending.json`.  No paper/arXiv MCP server was configured
in this Docker Codex session, so the triage used the official HTTP APIs and
private local caches instead.

### Erroneous arXiv DOI correction

The arXiv metadata for `2607.14362v1`, “Measures and generalizations of dual
Littlewood identities,” supplies the unrelated DOI
`10.1007/s11401-026-0050-7`.  Live Crossref metadata identifies that DOI as a
Chinese Annals of Mathematics paper by Pengfa Xu, Naihuan Jing, and Honglian
Zhang.  The publisher record matching the title, all five authors, Forum of
Mathematics Sigma volume 14, and article e106 is
`10.1017/fms.2026.10256`.

The local paper now uses the publisher DOI with `doi_status='verified'`.  Its
candidate audit trail records the publisher DOI as approved and the erroneous
arXiv DOI as rejected.  `fetch_arxiv.py` now preserves a verified publisher
DOI when later arXiv metadata supplies a conflicting DOI.  A real local
`--arxiv-id 2607.14362` refresh confirmed that the correction survives while
the remaining metadata and tags update normally.  The complete suite passes
(95 tests).  Production was not changed.

Recovery checkpoint:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-arxiv-doi-correction-20260817T141106Z.sql.gz
sha256 a6c9708797b76a56b98958ddada0ab43cd4f0d0917d0652d36ede115ff2ea282
```

### Manual DOI backlog review, 2026-08-17

Three guarded manual-review batches were applied to the local database after
checking current Crossref/DOI-resolver metadata, arXiv comments and abstracts,
and publisher pages for ambiguous cases.  Together they resolved 170 pending
candidate rows and made 59 verified DOI assignments.  This is a net increase
of 58 DOI-bearing papers because one DOI supplied by arXiv was moved from the
wrong paper to its actual publication match.  The pending queue fell from
1,507 to 1,337, and the number of papers with a DOI rose from 40,708 to 40,766.
Production was not changed.

The review covered all previously guarded conflict, disagreement, replacement,
and live-metadata mismatch categories.  It selected full papers over extended
abstracts and withdrawn duplicates, final journal versions over conference
versions where appropriate, and actual articles over monograph-level DOIs.
It also rejected related sequels, corrigenda/errata offered for the original
paper, and DOIs belonging to supplements or appendices.  Where both records
were present locally, a publication DOI was moved from the supplement/appendix
candidate to the main arXiv paper.  The Novi Sad Journal of Mathematics article
`math/0609135` was confirmed as DOI-less rather than being forced to one of two
similarly titled articles.

One additional erroneous arXiv DOI was corrected: arXiv assigns
`10.1007/s11083-021-09585-0` to `2111.09588`, “Crowns as retracts,” but the
publisher record belongs to `2105.00711`, “A generalization of a theorem of
Erné.”  The DOI is now verified on the latter paper, and the former keeps a
rejected audit candidate.  `fetch_arxiv.py` now consults that rejected audit
trail so a later arXiv refresh cannot restore a known-bad DOI.  A real refresh
of `2111.09588` confirmed the safeguard.

The triage classifier now exposes strong-but-not-automatic matches as
`review_high_evidence`.  This intentionally remains a manual category because
corrigenda, appendices, and merged papers can score just as strongly as genuine
publication-title changes.  The final read-only report is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/final-manual-20260817.json
```

It contains 1,337 pending candidates: 85 `review_high_evidence` records and
1,252 ordinary unresolved records.  No other guarded review category remains.
Postflight checks found every one of the 59 selected DOIs on exactly one paper,
zero candidate orphans, and the expected 80,447-paper corpus.  The complete
suite passes (99 tests), `compileall` passes, and `git diff --check` is clean.

Recovery checkpoints for the manual batches are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch-20260817T150500Z.sql.gz
sha256 d2dac00a818f5d30be569d9f534755c1dd47160ea401f7f13d2cafd61b04b970

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch2-20260817T160000Z.sql.gz
sha256 861bc4abd4568f5939ccd8a89d65fbada1bfde1e267f7aa14331cb43c60025e9

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch3-20260817T161000Z.sql.gz
sha256 52d9745b399624991dcd94abd148f5c122b04d442e1876ce22380997e9a554f6
```

Five further guarded manual batches continued the same review.  Across all
eight manual batches, 532 pending rows have now been resolved and 366 verified
DOIs assigned.  The DOI-bearing-paper count rose by 365, from 40,708 to
41,073, because one DOI was moved from an incorrect paper to its true owner.
The pending queue is now 975, down from 1,507; a fresh read-only classification
places all 975 in the ordinary `unresolved` category.  Its report is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual8.json
```

The later batches caught several same-author false matches that title-only
scoring cannot safely decide: alternating runs versus alternating descents,
two versus three filled cells in signed magic rectangles, different pattern
classes, sequels, corrigenda, and later book chapters.  They also corrected
the APN preprint `2111.04197`: the queued IEEE DOI belongs to a different
solo-authored paper, while the verified publication DOI is
`10.5070/C65365555`.  The three parts of Nakanishi's *Cluster Algebras and
Scattering Diagrams* were not assigned the monograph-level DOI
`10.1142/E073`, since that identifier cannot uniquely identify any one of the
three arXiv records.  Duplicate candidate groups were resolved to the paper
whose title and abstract match the publisher record.

Production remains unchanged.  Per the user's direction, no new regression
tests were added or rerun for these database-only manual batches; each batch
was first rolled back as a guarded dry run, then committed with row-count,
unique-ownership, and DOI-count assertions.  The live database should be
backed up and updated only after the local pending queue reaches zero.

Additional recovery checkpoints are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch4-20260817T162000Z.sql.gz
sha256 ebc5dc833403a79e8f5a515e61515c576e47e25bb5bb12c1d6978c7125f1b529

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch5-20260817T170000Z.sql.gz
sha256 7c580330db622ac36284deef7537ced3558209d333797a4b377b8631c03c077d

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch6-20260817T171500Z.sql.gz
sha256 d0119d7ca8f11624ca1f4e7b3f173872678e1083e06c467e1b241996a9880233

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch7-20260817T174000Z.sql.gz
sha256 d8e1410c5780590b0d3b5ed6fc85479c3802906f5cccb525bf4387bb45400581

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch8-20260817T180500Z.sql.gz
sha256 e95c07073e1c8d86b5ffccf539498f77592bed3e7c6fdc20c42f6be3ec7e6526
```
