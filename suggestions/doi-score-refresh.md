# Pending DOI score refresh

Stored queue confidence predates later normalization fixes, while the review
interface renders titles with the current normalizer. This can make exact
matches appear to have unexpectedly low scores. Historical scores also use the
old symmetric date rule (McNeil: 2022 to 2026 scored 90%). The user-approved
asymmetric rule now gives that exact match 100% on fresh scoring.

Consider storing the scorer version and a score breakdown with future lookup
results. Add a dry-run-first refresh of pending evidence/scores, using current
Crossref records, without approving candidates or changing review history.
Compare score changes against reviewed correct and incorrect matches before
any bulk approval. This score-refresh workflow remains a proposal, not an
authorized queue mutation.
