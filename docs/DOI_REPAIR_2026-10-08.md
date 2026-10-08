# DOI repair receipt, 2026-10-08

The user authorized implementing the audit findings and repairing the eight
valid matches. Code checkpoint `8a62b32` is committed/pushed, not deployed.
The assignment repairs below are completed on production and publicly verified.

## Code fixes

- Compatibility-normalize styled Latin and Greek symbols before title mapping,
  and casefold after decomposition. Mathematical italic capital M now survives;
  the Elvey Price title pair scores 100 instead of 93.333 on title/authors.
- Routine discovery and DB-backed bibliography backfill require review when
  paper comments/journal references explicitly identify an extended abstract,
  conference precursor or FPSAC record and the proposed DOI is not explicitly
  typed `proceedings-article`. Scores are unchanged by this guard. A conference
  mention alone does not trigger it; proceedings DOIs retain the other guards.
- AI review evidence includes paper comments/editor notes and the competing
  paper's abstract/comment/journal reference/editor note/provenance. Evidence
  tokens bind these fields so a version-context change invalidates stale reviews.
- Documented reason prefixes for valid publication, wrong work and wrong version.
  Conflicts should be reviewed, not used as automatic negative training labels.

Verification: 183 Python tests pass, with one optional DB test skipped in that
run; all 12 DOI API tests subsequently pass with the MariaDB integration enabled
using connection-local temporary tables. OpenAPI YAML and diff checks pass.
No schema migration is needed. The automatic threshold remains 93.

## Live assignment changes

The restricted bearer API handles pending candidates only. The existing
authenticated admin HTTP endpoints support the approved repairs without code
deployment. Used an admin session with CSRF tokens and same-origin Referer;
password/session values stayed in memory and were not recorded.

| Candidate | arXiv | DOI | Action |
| --- | --- | --- | --- |
| 27047 | 0707.4460 | 10.5802/jolt.583 | Approved previously rejected match |
| 11754 | 1801.05973 | 10.3934/dcds.2022022 | Approved previously rejected match |
| 29083 | math/0312232 | 10.1006/jcta.2002.3291 | Approved previously rejected match |
| 3061 | 2201.06596 | 10.1287/moor.2023.0054 | Approved previously rejected match |
| 6218 | 2011.02139 | 10.1007/s10468-022-10115-8 | Approved previously rejected match |
| 2435 | 2204.06847 | 10.1090/tran/9103 | Approved previously rejected match |
| 20504 | 1306.0542 | 10.7146/math.scand.a-25501 | Approved previously rejected match |
| 49574 | 2310.03527 | 10.1007/s00029-025-01113-x | Reassigned from 2512.02267 and approved |

Source-backed reasons are in the [eleven-case audit](DOI_HIGH_SCORE_REJECTIONS.md)
and the private operation plan. Seven requests used
`POST /admin/dois/{id}/approve`; candidate 49574 used
`POST /admin/dois/49574/reassign`. All eight papers now have provenance
`verified`. The wrong Free boundary paper (paper ID 5559, arXiv 2512.02267)
has its DOI/provenance/confidence cleared, and its candidate 55169 is rejected.

These legacy admin endpoints do not write `doi_review_events`. The operation
therefore retains separate source reasons, intents, responses, and before/after
snapshots. Existing stored candidate scores were preserved as historical values;
this was an editorial repair, not a bulk rescore or threshold-based approval.

## Preservation and verification

- Before writing, fetched all eleven candidates through the bearer read API,
  checked their exact identities, rejected states, empty current assignments,
  expected conflicts and evidence hashes. Rechecked each immediately before
  its admin mutation. Each target paper had only its one audited candidate.
- Read-only production snapshots covered 15 papers and 14 candidate rows,
  including the three correct full-paper owners and the incorrect He–Wheeler
  owner. Exactly nine papers and nine candidate rows changed: eight approvals
  plus the cleared/rejected wrong owner. No rows were added or deleted in this
  inspected set. All other snapshot rows compare equal.
- Candidates 7857, 3221 and 25522 remain rejected; their full-paper assignments
  2007.07078, 2210.17476 and 0910.3047 are unchanged.
- All eight resulting DOI/provenance pairs and the cleared wrong owner were
  independently re-read through the public site MCP. The Periodic DOI occurs
  only on the intended paper in the inspected set; bearer reads show no
  conflicting assignment for any of the eight.
- Admin mutation endpoints scheduled the existing index-cache invalidation.
  No direct database writes, local DB synchronization or deployment occurred.

Durable private evidence, outside Dropbox/Git:
`/home/dev/.local/state/arxiv-symmetricfunctions/repairs/2026-10-08-high-rejections/`.
Contains `before.json`, `after.json`, `plan.json`, eight intent/receipt/after
records and the bounded operation script. Files contain no credentials. The
script refuses changed evidence and records intent before each mutation; it is
not a general-purpose bulk repair command or safe to replay after this repair.

Remaining calibration work: curate a fresh labeled evaluation set before fitting
thresholds or title weights. These repaired examples are development evidence,
not an independent holdout. Structured rejection categories beyond documented
reason prefixes remain a future schema/UI proposal.
