# DOI author-contradiction parameters (2026-10-08)

The user asked for stronger author-mismatch deductions while preserving the
proportional treatment of added and missing authors. This change is a heuristic
parameter adjustment, not a calibrated probability model.

## Selected rule

Retain the previous directional deductions, relative to arXiv author count N:

- Missing: 20 × missing/N points.
- Added: 15 × added/N points.
- One or more clear identity contradictions: another 50 points per candidate.

A contradiction means unmatched identities remain on both sides after maximum
one-to-one matching of both exact identities and possible metadata variants.
Exact identities match surnames and full first names/compatible initials.
Possible variants include incomplete given names with compatible surnames,
close name spellings, reordered/split components, and added name components.
They are uncertainty, not confirmed identity: they receive no full-match credit
and cannot authorize automatic approval. An initial with a clearly different
surname is still contradictory. Malformed TeX is treated as uncertainty.

The initial V. is now preserved when extracting a given name; previously it
could be discarded as a generational suffix.

Named constants in `src/title_matching.py`:
`AUTHOR_MISSING_PENALTY=0.20`, `AUTHOR_ADDED_PENALTY=0.15`,
`AUTHOR_CONTRADICTION_PENALTY=0.50`, `AUTHOR_VARIANT_SIMILARITY=0.85`.
Variant string similarity is used only to avoid overclaiming a contradiction,
never to award exact author credit. There are no person-specific alias lists.

| Same title; otherwise complete metadata | Score |
| --- | ---: |
| Five authors, all matching | 100 |
| Five authors → six, one added | 97 |
| Five authors → four, one omitted | 96 |
| Five authors, one clearly replaced | 43 |
| Two authors, one clearly replaced | 32.5 |
| One author, clearly different identity | 15 |

The extra 50 points ensure a clear contradiction falls below 50 even with an
exact title. Date, journal and runner-up deductions still apply. Scores remain
bounded to 0–100. Existing queue values are not recalculated automatically.

## Exploratory check

Inspected the local database read-only: 400 approved candidates whose DOI still
matches a paper marked verified, and 400 rejected candidates whose DOI is not
currently assigned to their paper. Selection used SHA-256 of a fixed salt and
candidate ID. This is a historical snapshot, not live production.

The old identity rule flagged 24 of the verified and 49 of the rejected pairs
as mismatched on both sides. That included parsing/name-form variants, so simply
increasing every mismatch deduction would be inappropriate. With the V. fix and
conservative uncertainty pairing, the strong-contradiction counts are 2 and 35.
Both remaining verified examples contain explicit coauthor changes in stored
metadata; they require source review before any claim that those DOI assignments
are wrong. No database records were changed.

Compared extra deductions of 0, 30, 40 and 50 points using the title/author
component only. Date, journal and runner-up evidence was not reconstructed.

| Extra contradiction deduction | Verified sample below 50 | Rejected sample below 50 |
| --- | ---: | ---: |
| 0, updated name handling | 44/400 | 231/400 |
| 30 | 45/400 | 236/400 |
| 40 | 46/400 | 237/400 |
| 50 | 46/400 | 237/400 |

The choice of 50 follows the requested below-50 interpretation for clear
contradictions; this sample does not establish that 50 is statistically optimal.
The known hypercube title collision (2501.19029 versus 2401.01769) now scores
32.5 rather than 82.5 for the wrong coauthor, while the correct author list
remains at 100 in the fixture.

Historical labels are not audited ground truth. Rejections may reflect cleanup,
and approved papers may have changed author lists or stale deposited metadata.
The diagnostic split grouped by paper ID, but both groups were inspected while
refining name handling; it is not an untouched validation set. The overall
60–100/under-50 interpretation remains unvalidated: title changes and noisy
metadata still cause substantial overlap. IDF weighting and a fresh curated
holdout are separate next steps.

Evidence outside the repository:
`/tmp/arxiv-author-penalty-sample.json`,
`/tmp/arxiv-author-tuning-results.json`,
`/tmp/arxiv-author-tuning-tests.log`.
