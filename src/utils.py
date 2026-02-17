"""Shared utility functions."""

import re
import unicodedata


def strip_accents(text):
    """Strip diacritics/accents from text: Erdos -> Erdos, Garcia -> Garcia."""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def slugify(name):
    """Convert a name to a URL-friendly slug: 'Per Alexandersson' -> 'per-alexandersson'."""
    s = strip_accents(name).lower()
    s = re.sub(r"[^a-z0-9\s-]", '', s)   # remove non-alphanumeric (keep spaces and hyphens)
    s = re.sub(r'[\s]+', '-', s.strip())  # spaces to hyphens
    s = re.sub(r'-+', '-', s)             # collapse multiple hyphens
    return s
