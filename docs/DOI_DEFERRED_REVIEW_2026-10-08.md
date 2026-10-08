# Deferred DOI review, 2026-10-08

Follow-up to [the initial 448-candidate review](DOI_PENDING_REVIEW_2026-10-08.md).
The remaining 125 candidates received deeper publication-identity checks.
Root retained all mutation ownership; inexpensive workers provided read-only
evidence. No runtime code, scoring parameters, or deployment changed.

## Decisions and evidence

Completed: **40 approved, 85 rejected, none deferred**. The live pending queue
is empty. One approval required the DOI reassignment described below.

Exact titles, authors, and matching journal references support straightforward
matches. Changed titles and author lists received additional checks against
publisher abstracts, author repositories, full texts, or publication lists.
Root fetched 75 exact Crossref records independently; the other requests failed
and were not represented as successful fetches. Supplied metadata remained
available alongside other sources.

Worker proposals were corrected before writes. In particular, some cited DOI
URLs did not match the candidate DOI, and some proposed approvals conflated
proceedings reports or superseded manuscripts with the full publication. These
original proposals are retained as review history, not authoritative labels.

Notable resolved cases:

- **55565 / 55566:** the two Aval records have swapped titles in their arXiv
  metadata. The actual PDFs and [author bibliography](https://www.labri.fr/perso/aval/pub.html)
  distinguish the 19-page journal paper from the shorter LaCIM proceedings
  contribution. Approve the journal record 0711.0900; reject 0711.0902 for this DOI.
- **55675:** Rather's new manuscript explicitly cites the proposed older DOI
  paper as reference 12 and studies its problem. Reject this follow-up match.
- **55795:** the 12-page [RIMS proceedings report](https://www.kurims.kyoto-u.ac.jp/~kyodo/kokyuroku/contents/pdf/2332-20.pdf)
  cites the separate full two-vertex paper in Math. J. Okayama University 66
  (2024), 1–30. Reject the proceedings DOI for the 32-page arXiv manuscript.
- **55780 / 55843:** retain the DOI on the corrected or merged full-paper record;
  reject the superseded path-cover manuscript and the separate odd-case
  intersecting-family contribution for those publication assignments.
- **55824:** the [author-hosted final article](https://www.csie.ntu.edu.tw/~hil/paper/yinco26.pdf)
  publishes the odd-hole/perfect-graph portion of arXiv:2207.07613. Direct full-text
  comparison confirms the same Theorems 1–2, parameterized runtimes, Lemmas
  2.1–2.4, and proof reduction. Approve with an explicit version qualification:
  the journal article omits the even-hole section and Kai-Yuan Lai. This does not
  assert that every result in the preprint appears in the publication.
- **55803:** the [publisher abstract](https://www.sciencedirect.com/science/article/pii/S0166218X25000289)
  identifies the ker/core/corona results of Levit–Mandrescu's 2209.00308.
  Existing owner 2405.13176 is a distinct *Revisited* paper and cites that work
  separately. Transfer the DOI from paper 11012 to paper 20276 through the
  authenticated admin interface; preserve the previously rejected SSRN candidate.

These decisions identify publications; they are not proof audits or statistical
validation of the matching score.

## Execution record

Artifacts outside the synced repository, without credentials:

`/home/dev/.local/state/arxiv-symmetricfunctions/reviews/2026-10-08-deferred/`

The directory contains the 125-row original queue, independent proposals and
corrections, root evidence, independently fetched Crossref metadata, final plan,
API intents/receipts/after snapshots, and admin reassignment before/after records.

The bearer API handles 124 ordinary decisions with fresh snapshot checks and
durable per-request journaling. Rejections precede approvals so the Aval journal
assignment does not invalidate the conference candidate's reviewed snapshot.
The single admin reassignment has a separate journal because that existing
endpoint does not write `doi_review_events`.

Final production reconciliation passed for all 125 candidate states, paper DOIs
and provenance, and all 124 bearer-API audit reasons, tokens, DOI values and paper
IDs. There were no skipped or failed writes. The admin before/after comparison
verified exactly two changed paper assignments and two changed candidate states;
the older SSRN rejection remained identical. Public MCP metadata independently
confirmed the corrected assignment and cleared former owner.

Production totals: **0 pending, 35,841 approved, 3,502 rejected**. There are
**447 review audit events**, the previous 323 plus these 124 API decisions.
The additional rejected candidate is 51206, the old owner of the transferred
DOI; it is outside the 125-candidate queue. Existing other DOI owners were
unchanged. A final authenticated queue read returned no candidates.

Verification artifacts: `production-verification.json`, `admin-before.json`,
`admin-after.json`, and `55803-{intent,receipt,after}.json`. Source changes are
documentation only; `git diff --check` passed. Runtime tests and deployment
were not rerun because neither application code nor configuration changed.

## Separate assignment findings

The pending review also exposed two existing assignments needing a separate
scoped repair review. Neither is grounds for approving the pending candidate:

- DOI `10.3390/axioms15050382` is assigned to 2603.02831, while the publisher
  title and width-9 results match 2604.12029. Pending candidate 55203 is yet
  another paper (2603.25191), and its proposed assignment is rejected.
- DOI `10.5486/pmd.2020.8577` has two existing owners: 1803.10051, matching the
  2020 publication and journal reference, and 2111.04538, a later conjecture
  paper. Pending candidate 55760 is a separate binary-quadratic-forms paper
  which cites the 2020 article; reject its match and preserve existing owners
  during this pending-candidate pass.

The exact owner snapshots are retained in `queue.json` for a subsequent repair.
