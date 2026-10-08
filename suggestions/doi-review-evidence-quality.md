# DOI review evidence quality

The 2026-10-08 pending-queue audit found that a first inexpensive-agent pass
sometimes treated changed titles as harmless without checking publication
identity, and sometimes rejected a renamed paper for the same reason. A second
pass and root review caught examples before any API writes.

Proposal: extend the review artifact format to distinguish supplied indexed
metadata from newly fetched primary evidence, record final URL/status and an
exact short identifying fact, and require a separate version check for title or
author changes. DOI/arXiv URLs synthesized from IDs are not evidence of access.
Leave uncertainty pending; do not use these legacy scores as truth labels.

Next step: use this format for the next review batch before considering an
unattended review worker. Preserve the existing root-owned API-write gate.
