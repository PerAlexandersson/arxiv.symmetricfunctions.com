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


# ── BibTeX helpers ─────────────────────────────────────────────────────────────

def protect_capitals_for_bibtex(title):
    """Wrap capital letters in braces so BibTeX won't lowercase them.

    The first character is left unprotected (BibTeX preserves it regardless).
    Example: 'A new formula for Macdonald polynomials using LLT polynomials'
          -> 'A new formula for {M}acdonald polynomials using {LLT} polynomials'
    """
    if not title:
        return title

    def _protect(match):
        return f"{{{match.group(0)}}}"

    first_char = title[0]
    rest = title[1:]
    rest = re.sub(r'[A-Z]{2,}', _protect, rest)   # acronyms first
    rest = re.sub(r'[A-Z]',     _protect, rest)   # remaining singles
    return first_char + rest


def generate_bibtex_key(authors, year, published=False):
    """Generate a BibTeX citation key from author last names and year.

    Returns e.g. 'SmithJones2024x' (preprint) or 'SmithJones2024' (published).
    """
    suffix = '' if published else 'x'
    if authors:
        last_names = []
        for author in authors:
            last_name = author.split()[-1]
            last_name = strip_accents(last_name)
            last_name = ''.join(c for c in last_name if c.isalnum())
            last_names.append(last_name)
        return f"{''.join(last_names)}{year}{suffix}"
    return f"arxiv{year}{suffix}"


def arxiv2bib(paper_data):
    """Generate an arXiv-style BibTeX entry from a paper dict.

    Expected keys: arxiv_id, title, authors (list), published_date, journal_ref, doi.
    """
    date = paper_data['published_date']
    year = date.year if hasattr(date, 'year') else date
    key  = generate_bibtex_key(paper_data.get('authors', []), year, published=False)

    author_str      = ' and '.join(paper_data.get('authors', [])) or 'Unknown'
    clean_arxiv_id  = re.sub(r'v\d+$', '', paper_data['arxiv_id'])
    protected_title = protect_capitals_for_bibtex(paper_data['title'])

    bib = (
        f"@article{{{key},\n"
        f"Author = {{{author_str}}},\n"
        f"Title = {{{protected_title}}},\n"
        f"Year = {{{year}}},\n"
        f"Eprint = {{{clean_arxiv_id}}},\n"
        f"  url = {{https://arxiv.org/abs/{clean_arxiv_id}}},\n"
        f"journal = {{arXiv e-prints}}"
    )
    if paper_data.get('journal_ref'):
        bib += f",\njournalref = {{{paper_data['journal_ref']}}}"
    if paper_data.get('doi'):
        bib += f",\ndoi = {{{paper_data['doi']}}}"
    bib += "\n}"
    return bib
