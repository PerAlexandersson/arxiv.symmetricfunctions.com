# Title rarity and meaningful DOI score bands

The user proposed weighting shared rare title words more strongly and making
60–100 generally indicate a likely match, with scores below 50 unlikely.
Title-rarity weighting and overall band calibration remain proposals. A later
2026-10-08 increment implements a 50-point deduction for clear author identity
contradictions after separating plausible name variants; see
`../docs/DOI_AUTHOR_TUNING.md`. No IDF weighting or queue rescore was implemented.

## Read-only evidence (2026-10-08)

The local database snapshot contains 82,505 paper titles and 19,030 normalized
tokens. Reused `normalize_title`; counted each token once per title, not its raw
occurrences or appearances in abstracts. No database writes. This snapshot
predates current production and must not be described as a live-site count.

| Token | Titles containing it |
| --- | ---: |
| of | 40,453 |
| the | 24,580 |
| on | 17,057 |
| graphs | 16,054 |
| polynomials | 2,564 |
| conjecture | 2,437 |
| schur | 549 |
| ehrhart | 239 |
| hypercubes | 151 |
| tensegrities | 7 |
| mcneil | 1 |

Result artifact: `/tmp/arxiv-title-frequency-inspection.json`. The bounded
Python orchestration used the existing application normalizer and Counter for
text metadata inspection; it introduces no mathematical computation library.

## Proposed weighting

Use smoothed, capped inverse document frequency from normalized titles, with
one document per logical paper. Weight title-edit costs so missing common
function words matters less than disagreement on distinctive technical terms.
Do not drop part numbers, negations or meaningful mathematical symbols. Cap
weights so a singleton typo, unrecognized markup or novel identifier cannot
dominate. Freeze/version the frequency snapshot used by each scorer so scores
are reproducible. A periodic rebuild is sufficient; no full DB scan per lookup.

Normalized similarity remains 100 for any exact title. Rarity primarily helps
near matches; exact generic-title distinctiveness is a separate feature.
Neither rarity nor title exactness should erase contradictory authors or
competing DOI assignments.

Reference: Stanford IR text, inverse document frequency:
https://nlp.stanford.edu/IR-book/html/htmledition/inverse-document-frequency-1.html

## Validation before assigning score meanings

The existing local candidates include 3,046 approved/current-DOI pairs whose
paper status is `verified`, 40 whose source is `arxiv`, and 32,468 whose source
is `auto`. There are 3,309 rejected candidates. These are potential evidence
strata, not clean training labels. In particular, one rejected candidate has
its DOI currently assigned to a verified paper, and two approved candidates
no longer match their verified paper's current DOI. Rejections may reflect
queue cleanup/conflicts rather than a wrong bibliographic identity.

Do not train on automatic approvals as if they were independently confirmed:
that would learn the old scorer's decisions. Curate both correct and incorrect
pairs, including near-identical titles, shared surnames, changed author lists,
publication lag and renamed titles. Partition by paper/DOI, not candidate row,
so related versions do not leak across development and held-out evaluation.

At the time of this assessment, the heuristic gave the known wrong hypercube
coauthor match 82.5, although the author guard blocked auto-approval. The later
contradiction deduction reduces it to 32.5. Thus a numeric stretch cannot
make the desired bands reliable by itself. Consider an explicit low-score cap
for strong identity contradictions, while keeping incomplete metadata and
simple added/omitted authors distinct from contradictions. Validate any such
cap against actual examples before adopting it.

Possible *target* bands: 90–100 strong, 60–89 likely but review, 50–59 uncertain,
0–49 unlikely. Measure held-out correct/incorrect fractions and errors per band
before claiming those meanings. Keep auto-approval eligibility separate from
the score and retain the current guards.
