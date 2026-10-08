# Pending DOI score refresh

Stored queue confidence predates later normalization fixes, while the review
interface renders titles with the current normalizer. This can make exact
matches appear to have unexpectedly low scores. Publication lag also deducts
up to ten points even for exact title/author matches (McNeil: 2022 to 2026).

Consider storing the scorer version and a score breakdown with future lookup
results. Add a dry-run-first refresh of pending evidence/scores, using current
Crossref records, without approving candidates or changing review history.
Before changing the date weights, compare the proposed rule against reviewed
correct and incorrect matches. This is a proposal, not an active scoring change.
