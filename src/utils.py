"""Shared utility functions."""

import re
import unicodedata
from urllib.parse import unquote, urlparse


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


_ARXIV_ID_PATTERNS = (
    re.compile(r'^\d{4}\.\d{4,5}(?:v\d+)?$', re.IGNORECASE),
    re.compile(r'^[a-z.-]+/\d{7}(?:v\d+)?$', re.IGNORECASE),
)
_ARXIV_ID_SEARCH_RE = re.compile(
    r'(?<![A-Za-z0-9./-])'
    r'((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?)'
    r'(?![A-Za-z0-9./-])',
    re.IGNORECASE,
)


def extract_arxiv_id(value):
    """Return a normalized arXiv ID from a raw ID, arXiv label, or arXiv URL."""
    if not value:
        return None

    candidate = str(value).strip()
    if not candidate:
        return None

    candidate = candidate.strip('<>()[]{}').strip('\'"')
    candidate = candidate.rstrip('.,;')

    if candidate.lower().startswith('arxiv:'):
        candidate = candidate.split(':', 1)[1].strip()
    elif candidate.lower().startswith(('arxiv.org/', 'www.arxiv.org/', 'export.arxiv.org/')):
        candidate = 'https://' + candidate
    elif candidate.startswith('//'):
        candidate = 'https:' + candidate

    parsed = urlparse(candidate)
    hostname = (parsed.netloc or '').lower()

    if hostname.endswith('arxiv.org'):
        path = unquote(parsed.path).lstrip('/')
        parts = path.split('/', 1)
        if parts and parts[0] in {'abs', 'pdf', 'html', 'e-print', 'format'}:
            candidate = parts[1] if len(parts) > 1 else ''
        else:
            candidate = path
    elif parsed.scheme and parsed.netloc:
        return None

    candidate = candidate.strip().strip('/')
    if candidate.lower().endswith('.pdf'):
        candidate = candidate[:-4]
    candidate = candidate.rstrip('.,;')

    for pattern in _ARXIV_ID_PATTERNS:
        if pattern.fullmatch(candidate):
            return candidate

    match = _ARXIV_ID_SEARCH_RE.search(candidate)
    return match.group(1) if match else None


def split_arxiv_id_version(value):
    """Return ``(base_id, version)`` for a valid arXiv identifier.

    arXiv revisions identify versions of one logical paper, not distinct
    papers.  Keeping this normalization in one place prevents fetchers and
    machine-facing APIs from disagreeing about paper identity.
    """
    arxiv_id = extract_arxiv_id(value)
    if not arxiv_id:
        return None, None
    match = re.fullmatch(r'(.+?)(?:v(\d+))?', arxiv_id, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1), int(match.group(2) or 1)


_BIBTEX_KEY_SEARCH_RE = re.compile(r'^\s*([A-Za-z0-9]+?)([12]\d{3})(x?)\s*$')


def parse_bibtex_search_key(value):
    """Return normalized BibTeX search key info, or None for non-key searches."""
    if not value:
        return None

    key = str(value).strip()
    entry_match = re.match(r'@\w+\s*\{\s*([^,\s]+)', key)
    if entry_match:
        key = entry_match.group(1)

    match = _BIBTEX_KEY_SEARCH_RE.fullmatch(key)
    if not match:
        return None

    author_part, year, suffix = match.groups()
    if author_part.lower() != 'arxiv' and len(author_part) < 2:
        return None

    return {
        'key': f'{author_part}{year}{suffix}',
        'key_lower': f'{author_part}{year}{suffix}'.lower(),
        'year': int(year),
    }


def bibtex_keys_for_authors_year(authors, year):
    """Return possible generated keys for a paper's arXiv and published entries."""
    return {
        generate_bibtex_key(authors, year, published=False).lower(),
        generate_bibtex_key(authors, year, published=True).lower(),
    }


def arxiv2bib(paper_data):
    """Generate an arXiv-style BibTeX entry from a paper dict.

    Expected keys: arxiv_id, title, authors (list), published_date, journal_ref, doi.
    """
    date = paper_data['published_date']
    year = date.year if hasattr(date, 'year') else date
    key  = generate_bibtex_key(paper_data.get('authors', []), year, published=False)

    author_str      = ' and '.join(paper_data.get('authors', [])) or 'Unknown'
    arxiv_id        = str(paper_data['arxiv_id']).strip()
    protected_title = protect_capitals_for_bibtex(paper_data['title'])

    bib = (
        f"@article{{{key},\n"
        f"  author = {{{author_str}}},\n"
        f"  title = {{{protected_title}}},\n"
        f"  year = {{{year}}},\n"
        f"  eprint = {{{arxiv_id}}},\n"
        f"  url = {{https://arxiv.org/abs/{arxiv_id}}},\n"
        f"  journal = {{arXiv e-prints}}"
    )
    if paper_data.get('journal_ref'):
        bib += f",\n  journalref = {{{paper_data['journal_ref']}}}"
    if paper_data.get('doi'):
        bib += f",\n  doi = {{{paper_data['doi']}}}"
    bib += "\n}"
    return bib


# ── SymCat label matching ─────────────────────────────────────────────────────

def suggest_sf_labels(phrase, sf_labels, limit=8):
    """Find matching SymCat labels for a keyword phrase.

    Returns a list of (key, label, match_type) tuples, best matches first.
    """
    phrase_lower = phrase.lower()
    words = phrase_lower.split()
    phrase_norm = phrase_lower.replace(' ', '').replace('-', '').replace('_', '')
    suggestions = []
    for key, label in sf_labels.items():
        title_lower = label['title'].lower()
        key_lower = key.lower()
        key_norm = key_lower.replace('-', '').replace('_', '')
        if phrase_lower == title_lower:
            suggestions.insert(0, (key, label, 'exact title'))
        elif key_norm == phrase_norm:
            suggestions.insert(0, (key, label, 'key match'))
        elif (len(phrase_norm) >= 4 and
              (key_norm.startswith(phrase_norm) or phrase_norm.startswith(key_norm))):
            suggestions.insert(0, (key, label, 'key prefix'))
        elif phrase_lower in title_lower:
            suggestions.append((key, label, 'in title'))
        elif title_lower in phrase_lower:
            suggestions.append((key, label, 'title in phrase'))
        elif (len(phrase_norm) >= 4 and
              (phrase_norm in key_norm or key_norm in phrase_norm)):
            suggestions.append((key, label, 'key substr'))
        elif len(words) > 1 and all(w in key_norm for w in words):
            suggestions.append((key, label, 'words in key'))
        elif len(words) > 1 and all(w in title_lower for w in words):
            suggestions.append((key, label, 'words in title'))
    return suggestions[:limit]
