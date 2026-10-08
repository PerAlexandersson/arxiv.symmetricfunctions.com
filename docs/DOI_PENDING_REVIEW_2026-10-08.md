# Pending DOI review, 2026-10-08

## Deployment

Deployed clean checkpoint `58ad92e` (runtime fixes from `8a62b32` and preceding
scoring checkpoints). Ten live runtime/schema files match local hashes.
Homepage, API status, admin login, and OpenAPI returned HTTP 200. Unauthenticated
review reads/writes returned 401; credentialed evidence reads succeeded and
included comments, editor notes, and conflicting-paper version context.

Before deployment, created host backup `backups/pre-doi-scoring-20261008/` with
code/config and a consistent database dump. Deployment log:
`/tmp/arxiv-doi-scoring-deploy.log`. No SQL migration or bulk rescore was run.
Existing validation: 183 Python tests passed (one optional database skip),
and all 12 API tests passed separately against MariaDB temporary tables.

## Review scope and method

Snapshot: 448 pending candidates; 35,593 approved and 3,302 rejected before
review. Three inexpensive agents reviewed 343 candidates without assigned-DOI
conflicts; root reviewed 105 with conflicts and owns all API writes. Initial
agent proposals were not applied: questionable title-change decisions prompted
a second evidence pass. Root then checked publication/version context and
conservatively deferred unresolved cases.

Exact distinctive title/author matches can be established from the supplied
Crossref metadata and indexed arXiv publication context. They are not represented
as fresh publisher full-text audits. Changed titles/authors and conference/full
paper relationships require additional evidence. An existing DOI assignment
conflict alone is never grounds for rejection. Access failures are uncertainty,
not negative labels. Per-case evidence records distinguish these limitations.

Private local artifacts (no credentials):
`/home/dev/.local/state/arxiv-symmetricfunctions/reviews/2026-10-08-pending/`.
They include the original queue, independent proposals, corrected reviews,
root conflict notes, final plan, API intents, receipts, and post-decision snapshots. Only the root applies decisions, with a fresh evidence
snapshot comparison and a re-read after each write. Changed snapshots are skipped.

## Outcome

Completed: **209 approved, 114 rejected, 125 deferred**. All 323 decisions
were applied through the credentialed API, with a fresh unchanged snapshot
before each write and an individual re-read afterward. No writes were skipped
and no errors occurred.

A separate production reconciliation checked all 448 candidate states, paper
DOIs/provenance, every audit reason/token/DOI/paper ID, and the existing DOI
owners from the conflict snapshot. All checks passed. Exactly 323 audit rows
exist; deferred candidates have none. Production totals are 125 pending, 35,802
approved, and 3,416 rejected. No existing DOI assignment was replaced, and no
previously approved/rejected candidate was reopened.

`production-verification.json` records the reconciled totals; `final-plan.json`
and the root/agents intent, receipt and after-snapshot JSONL files preserve
the per-case record in the artifact directory above. The code checkpoint remains
deployed; subsequent commits only record review progress and results.

Examples of review corrections before writes:

- Candidate 55250 is the 2010 Lagarias overview chapter, not his 1985 Monthly
  article. The [author publication list](https://dept.math.lsa.umich.edu/~lagarias/VITA/pubs1nov20.pdf)
  distinguishes them; root rejected the initial proposed approval.
- Candidate 55238 has different publication title and an added author, but the
  [author code repository](https://github.com/AryaGuo/PPO-swap) and publisher
  abstract describe the same swap-based facility-location method. Root deferred
  the proposed rejection pending a direct version link.
- Candidate 55659 cites the 40-page SLC reproduction of Macdonald's 1987
  manuscript; its candidate DOI names an eight-page 1990 chapter. Deferred.
- Explicit FPSAC precursors remain separate from their full-paper DOI owners.
- Merged papers and unresolved superseded versions remain pending.

These reviews are editorial identity labels, not a held-out statistical validation
of score calibration. No automatic cutoff or scoring weights changed in this pass.
