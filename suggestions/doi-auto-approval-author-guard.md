# Require author agreement for DOI auto-approval

Observed friction: the DOI lookup assigned `10.1137/24M1670093` to arXiv
`2501.19029` at confidence 1.000 because its title exactly matched the journal
article. The arXiv paper has a different coauthor and proves a different
result; the DOI belongs to arXiv `2401.01769`. The collision audit caught this
case only because the correct paper was also present.

Impact: an exact or near-exact title can currently outweigh contradictory
author metadata and create a false automatic DOI assignment. A collision may
not exist to make every such error visible.

Concrete next step: before auto-approval, require a positive author-identity
guard (for example, agreement on every available surname or an explicitly
tested subset rule). Treat a strong author mismatch as ineligible for automatic
approval regardless of title score, add regression fixtures for the two
hypercube papers, and keep the candidate pending for manual review.
