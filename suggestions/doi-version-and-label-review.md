# DOI version distinctions and historical labels

Update 2026-10-08: the user authorized the fixes and repairs. Styled Unicode and
precursor guards are implemented in `8a62b32` (not deployed); all eight live
assignments are repaired, and the three precursor rejections preserved.
See [the receipt](../docs/DOI_REPAIR_2026-10-08.md). Items below describe the
original proposal; category columns/UI and a curated holdout remain future work.

The requested audit of eleven high-scoring rejections found three legitimate
conference-precursor/full-paper distinctions and eight apparent valid matches.
See [the case-by-case audit](../docs/DOI_HIGH_SCORE_REJECTIONS.md).

Impact: fitting a cutoff to raw historical approvals/rejections would reward
old mistakes. All three wrong-version examples score 100, so raising the
threshold cannot resolve them. A DOI currently marked verified also appears
attached to the wrong He–Wheeler paper.

Original proposed steps:

- Perform an editorial correction pass for the eight sourced apparent valid
  matches, including the conflicting He–Wheeler assignment; retain the three
  precursor rejections. Preserve an audit trail and existing assignment guards.
- Require review when a journal DOI is proposed for an explicitly marked
  extended abstract or separately published conference precursor. Keep actual
  conference DOIs eligible; a conference keyword alone is not proof of error.
- Record rejection categories and primary evidence, separating wrong work,
  wrong version, assignment conflict and unknown legacy reasons. Do not use
  the six probable batch rejections as negative training labels.
- Fix styled Unicode capitals being dropped by casefold/NFKD ordering. Add
  regression coverage for mathematical Latin and Greek symbols before tuning
  title weights or thresholds.
- Evaluate the entire approval decision, including guards, on a fresh curated
  sample. Retain the 93 automatic threshold until that evaluation supports a
  change; the proposed 60 boundary has no special standing.

The original audit made no runtime, score, database or production changes;
the subsequent authorized work is recorded in the linked receipt.
