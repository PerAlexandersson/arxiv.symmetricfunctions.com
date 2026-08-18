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

A ninth guarded manual batch resolved another 125 pending candidate rows and
assigned 96 verified publication DOIs.  The pending queue fell from 975 to
850, and the DOI-bearing-paper count rose from 41,073 to 41,169.  The batch
was rolled back successfully as a dry run before being committed locally.
Postflight checks found all 96 selected DOIs approved on their intended
papers, all 29 explicit false candidates rejected, unique ownership for every
selected DOI, zero candidate orphans, and the unchanged 80,447-paper corpus.

This batch also resolved several competing-preprint groups.  The twisted-cubic
DOI was assigned to the later part whose abstract matches the journal article;
the moon-polyomino DOI was assigned to the preprint explicitly identified as
the updated version; and preliminary or separate records for the symmetric
design, conflict-free coloring, and centrosymmetric-involution papers were
rejected.  Other false positives included an SSRN repository copy, a FOCS
paper whose proceedings version names a different arXiv full version, and a
near-title Zagreb match that changed both the invariant and authorship.

The fresh read-only classification is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual9.json
```

All 850 remaining candidates are currently classified as `unresolved`.
Production remains unchanged, and no broad test suite was run for this
database-only batch.  The recovery checkpoint is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch9-20260817T192310Z.sql.gz
sha256 653c47b16c3d582c182d7de1d27cd98db0a2511b5696923a2e5ef1a0ded9f209
```

### Claude-assisted manual DOI batch

Six independent Claude reviewers were given ten of the strongest remaining
cases each, with read-only web search and no filesystem write tools.  Their
recommendations were reconciled locally against competing DOI candidates and
the existing policy for sequels, supplements, merged preprints, and repository
copies before any database change.

The guarded tenth batch assigned 48 verified DOIs and rejected 20 false or
competing candidates.  One exact owner (`1908.02384`) was restored from an
earlier score-based rejection, and the DOI for a graph-decomposition paper was
assigned to `2103.10808` instead of three related later preprints.  Merged
publications covering two separate arXiv parts were left without a unique DOI
owner, and a computations-only report was not treated as the journal article.

Three rejected false matches also exposed exact local papers that had no DOI
candidate row.  After a separate guarded dry run, their publication DOIs were
recorded directly with approved audit entries:

- `2307.03880`, “A matrix realization of spectral bounds”;
- `2303.02349`, “New Upper Bounds on the Size of Permutation Codes under
  Kendall tau-Metric”;
- `1811.11035`, “Finding perfect matchings in random regular graphs in linear
  time.”

In total this round added 51 verified publication DOIs.  The pending queue fell
from 850 to 783, and the DOI-bearing-paper count rose from 41,169 to 41,220.
Both write phases were rolled back successfully as guarded dry runs before
being committed locally.  Postflight checks found unique ownership for every
selected DOI, all intended audit statuses, zero candidate orphans, and the
unchanged 80,447-paper corpus.  All six Claude child processes exited normally.
Production remains unchanged, and no broad test suite was run for this
database-only round.

The fresh read-only classification is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual10.json
```

All 783 remaining candidates are currently classified as `unresolved`.  The
recovery checkpoint is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch10-20260817T194652Z.sql.gz
sha256 953b26dc0c52400a5f28ac0cb5699e151b2ba6d9a1c1b06a9d26b48d7b7bceba
```

An eleventh Claude-assisted batch used eight parallel ten-case reviewers plus
an independent second review of one initially uncertain publication-title
change.  After local reconciliation, the guarded batch assigned 62 verified
publication DOIs and rejected 19 false candidates.  Two rejected false matches
exposed exact local owners without candidate rows, so their DOIs were recorded
separately on `2303.04462` and `1901.07200`.  The pending queue fell from 783 to
702, and the DOI-bearing-paper count rose from 41,220 to 41,284.

The public `editor_note` field now explains eight non-binary cases from batches
ten and eleven: merged arXiv parts, a computations-only supporting report, a
companion paper, and two related but distinct cyclic-automorphism preprints.
Existing notes are preserved when these annotations are applied.  Both DOI
write phases and the note phase were rolled back successfully as guarded dry
runs before being committed locally.

Postflight checks found the intended candidate statuses, unique ownership for
the newly selected DOIs, zero candidate orphans, all eight notes present, and
the unchanged 80,447-paper corpus.  The fresh read-only classification is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual11.json
```

All 702 remaining candidates are classified as `unresolved`.  Production
remains unchanged, and no broad test suite was run for this database-only
round.  The recovery checkpoint is:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch11-20260818T055152Z.sql.gz
sha256 0d28f5e8290e4e6d4683416831742336f217b77f3c028f2748da92030eb125e2
```

Another parallel group of eight Claude reviewers then checked the next 80
cases.  The guarded twelfth batch assigned 40 verified DOIs and rejected 40
false candidates.
Eight false matches exposed exact local owners without candidate rows; their
DOIs were separately recorded on `2303.17278`, `2309.04892`, `2307.06752`,
`2301.09833`, `2305.20012`, `2306.10523`, `2302.08938`, and `2401.13356`.
The pending queue fell from 702 to 622, and the DOI-bearing-paper count rose
from 41,284 to 41,332.

Forty concise public `editor_note` annotations record the genuinely
non-obvious relationships encountered in this wave, including retitled
publications, companion and sequel papers, translated publications, duplicate
submissions, a retracted earlier paper, an SSRN copy, and a journal extension
of conference work.  The Research Square DOI exposed during review was not
assigned because it is a repository-copy identifier rather than a publication
DOI.  Existing notes were preserved.

All three write phases were rolled back as guarded dry runs before being
committed locally.  Postflight checks found all intended statuses, unique
ownership of every newly selected DOI, zero candidate orphans, and the
unchanged 80,447-paper corpus.  All eight Claude processes exited normally.
Production remains unchanged, and no broad test suite was run.  The fresh
read-only report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual12.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch12-20260818T060500Z.sql.gz
sha256 7305f01dcfcbfbb64418a91f1e9c3315c6c9520f48e8545edeb347ab3df59cd5
```

The thirteenth guarded batch used another eight parallel reviewers plus two
focused Opus second opinions.  Reconciliation resolved 82 pending rows: 49
verified DOI assignments and 33 rejections.  This includes approving the
already-pending candidate on the original short Kronecker-coefficient paper
and rejecting the competing long version, as well as rejecting an additional
vertex-distinguishing candidate competing with the correct edge-distinguishing
paper.  Four rejected false matches exposed exact local owners without
candidate rows; their DOIs were recorded on `1804.00068`, `1905.02387`,
`1903.07346`, and `1904.07070`.

The queue fell from 622 to 540, while the DOI-bearing-paper count rose from
41,332 to 41,385.  Forty-four further public notes document retitlings,
conference/full-paper relationships, split and merged preprints, sequels,
corrections, and competing records.  In particular, the note on `2106.07808`
explains that the suggested journal DOI publishes a theorem removed from the
current arXiv version after a flawed proof, and links the correction DOI.

All three write phases passed guarded rollback runs before local commit.
Postflight checks found the intended statuses, unique ownership for every new
DOI, zero candidate orphans, and 80,447 papers.  All Claude processes exited
normally.  Production remains unchanged, and no broad test suite was run.  The
fresh report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual13.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch13-20260818T062000Z.sql.gz
sha256 fe74df3c34883cf24418b060cf05d4f001bb47bc694b7dc745eb84d80ff3df73
```

The fourteenth eight-reviewer wave resolved another 80 rows: 43 verified DOI
assignments and 37 rejections.  Two low-confidence conference publications
covering only strict subsets of broader arXiv reports were rejected, while an
arXiv record whose authors explicitly identify a “significantly improved
version” as their publication was approved with a clarifying note.  Four false
matches exposed exact local owners; their DOIs were recorded on `1812.04987`,
`1904.02265`, `1905.01921`, and `2412.07974`.

The queue fell from 540 to 460, and the DOI-bearing-paper count rose from
41,385 to 41,432.  Fifty-one new public notes explain correction records,
retitlings, translations, narrower conference subsets, surveys, sequels,
withdrawn drafts, and alternate publication titles.  The note on `1806.04457`
also records its correct COCOON DOI after rejecting the unrelated queued DOI.

All write phases passed rollback dry runs before local commit.  Postflight
checks found the intended statuses, unique ownership for each newly assigned
DOI, zero candidate orphans, and the unchanged 80,447-paper corpus.  All eight
Claude processes exited normally.  Production remains unchanged, and no broad
test suite was run.  The fresh report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual14.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch14-20260818T064000Z.sql.gz
sha256 b4acf68bea1e4877b096da34d60bcc88839d2261fee3f3ac5332eb86c7ff6703
```

The fifteenth wave used eight ten-case reviewers and two focused Opus second
opinions.  It resolved 81 pending rows: 51 reviewed assignments, 29 reviewed
rejections, and one additional pending true-owner candidate.  A previously
score-rejected candidate on the true skew-growth-paper owner was also restored.
The shared DOI for two merged directed-hypergraph parts was assigned to neither
individual record; both now carry explanatory notes.

The queue fell from 460 to 379, and the DOI-bearing-paper count rose from
41,432 to 41,485.  Thirty-five new public notes cover split and merged papers,
expanded or subset publications, thesis/chapter mismatches, competing APN and
skew-growth records, and the two-part shared DOI.  Guarded rollback and commit
runs completed successfully.  Postflight checks found unique ownership of the
two corrected DOIs, zero candidate orphans, and 80,447 papers.  Production
remains unchanged, and no broad test suite was run.  The report and checkpoint
are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual15.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch15-20260818T070000Z.sql.gz
sha256 505b869970da4abb874f482f6e3edb5edca59bc127daf18451927a2d1e390a5d
```

The completed portion of the sixteenth review wave resolved 31 more pending
rows before the Claude account reached its session limit: 19 verified DOI
assignments and 12 rejections.  One rejected false match exposed the exact
local owner `1301.4459`, where that DOI was recorded with an approved audit
row.  Sixteen public notes explain the non-obvious retitlings, companion
papers, survey and dissertation mismatches, and competing-owner relationships.
No decision was inferred from the 13 Claude jobs that stopped without output.

The queue fell from 379 to 348, while the DOI-bearing-paper count rose from
41,485 to 41,505.  Postflight checks found 80,447 papers, zero candidate
orphans, the intended candidate statuses, and the unique corrected owner.  The
fresh report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual16-partial.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch16-partial-20260818T071000Z.sql.gz
sha256 9cf682930c721fa64e220f7d7d64a6f332a9412a44f0ee747d4c0ab2d254e0df
```

Work then continued with two parallel read-only Codex reviewers, with all
database changes still reconciled and applied by the main worker.  The guarded
seventeenth batch resolved 30 rows: 13 approvals and 17 rejections.  A false
match to the authors' earlier `s=1,2,3,4` paper exposed the correct publication
DOI for `1511.04983`; that DOI was recorded separately with an approved audit
row.  Fourteen new public notes document translations, preliminary and
conference subsets, companion or sequel papers, a combined proceedings
article, and other cases where a binary status alone would be misleading.

The queue fell from 348 to 318, and the DOI-bearing-paper count rose from
41,505 to 41,519.  All three phases passed rollback dry runs before local
commit.  Postflight found 80,447 papers, zero candidate orphans, all 30 planned
rows resolved, and the corrected DOI on `1511.04983`.  Production remains
unchanged, and no broad test suite was run for these database-only batches.
The report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual17.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch17-20260818T065113Z.sql.gz
sha256 ec43786bef35538c553abfe919821918c5a29e6723a48096b6458d839a30b4d4
```

The eighteenth guarded batch resolved another 30 rows: 15 verified DOI
assignments and 15 rejections.  Two false candidates exposed the actual
publication DOIs for `1410.7287` and `1407.4533`; both were assigned directly
with approved audit rows after publisher verification.  Twenty-seven new
public notes preserve the useful context behind retitlings, translations,
conference subsets, follow-on papers, a proceedings article covering two
preprints, and the corrected DOI records.

The queue fell from 318 to 288, and the DOI-bearing-paper count rose from
41,519 to 41,536.  The candidate, corrected-DOI, and note phases all passed
rollback dry runs before local commit.  Postflight found all 30 planned rows
resolved, the two corrected DOI assignments in place, 80,447 papers, and zero
candidate orphans.  Production remains unchanged, and no broad tests were run.
The report and recovery checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual18.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch18-20260818T065508Z.sql.gz
sha256 53bd888c50fd0b3930236349ea7d92b10a8a1f4c074a6e54f3cb9eace52d13bd
```

The nineteenth guarded batch resolved 30 further rows: 16 approvals and 14
rejections.  A false match between the algebraic and bijective random-matrix
papers exposed the correct Annals of Combinatorics DOI for `1311.7690`; it was
recorded directly with an approved audit row.  Public notes were appropriate
for all 30 papers because the wave was dominated by revised titles, conference
subsets, split manuscripts, companion code, changed author attribution, and
related-but-distinct publications.

The queue fell from 288 to 258, and the DOI-bearing-paper count rose from
41,536 to 41,553.  All write phases passed rollback dry runs before local
commit.  Postflight found all planned rows resolved, the corrected DOI in
place, 80,447 papers, and zero candidate orphans.  Production remains
unchanged, and no broad tests were run.  The report and recovery checkpoint
are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual19.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch19-20260818T065829Z.sql.gz
sha256 f723df5f4c39769a4c94120767660de95408bab086b54da5d6f793f896bd33cd
```

The twentieth guarded batch resolved another 30 rows, split evenly between 15
approvals and 15 rejections.  Three false candidates exposed the actual
publication DOIs for `1301.7602`, `1212.0177`, and `1211.1899`; all three were
assigned directly with approved audit rows.  Public notes on all 30 records
capture subset papers, conference/full-version relationships, retitlings,
later replacements, and related but distinct works.

The queue fell from 258 to 228, and the DOI-bearing-paper count rose from
41,553 to 41,571.  All phases passed rollback dry runs before local commit.
Postflight found all planned rows resolved, all three corrected DOI assignments
in place, 80,447 papers, and zero candidate orphans.  Production remains
unchanged, and no broad tests were run.  The report and recovery checkpoint
are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual20.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch20-20260818T070308Z.sql.gz
sha256 1ddd19db83d3306e078d809f01497391c1ffe88c7caf9d091fa8f0817bb47bb7
```

The twenty-first guarded batch resolved 20 further rows: seven approvals and
13 rejections.  It also recovered the final Algorithmica DOI for `1208.5345`
and reassigned a repeated false candidate to the exact simple-cycle paper
`1205.0128`.  Twenty public notes explain a withdrawn successor, two-preprint
mergers, preliminary and extended versions, DOI-less journal appearances,
retitlings, and the corrected owner.

The queue fell from 228 to 208, and the DOI-bearing-paper count rose from
41,571 to 41,580.  Each phase passed a rollback dry run before its local
commit.  Postflight found all 20 planned rows resolved, both recovered DOI
assignments in place, 80,447 papers, and zero candidate orphans.  Production
remains unchanged, and no broad tests were run.  The report and recovery
checkpoint are:

```text
/home/dev/.cache/arxiv.symmetricfunctions.com/doi-triage/post-manual21.json

/home/dev/.cache/arxiv.symmetricfunctions.com/backups/local-pre-manual-doi-batch21-20260818T070614Z.sql.gz
sha256 8327cb39b3b19a793eafecf72d0266d01c5f08e57a9248bd371137a721608c0e
```
