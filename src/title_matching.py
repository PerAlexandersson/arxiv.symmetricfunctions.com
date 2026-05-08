"""Utilities for normalizing titles/authors and scoring text similarity."""

from difflib import SequenceMatcher
import html
import re
import unicodedata

_DASH_RE = re.compile(r'--+|[‐‑‒–—−-]+')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_MATH_DELIM_RE = re.compile(r'(\\\(|\\\)|\\\[|\\\]|\$+)')
_TEX_ORDINAL_RE = re.compile(r'([a-z0-9])\s*\^\s*\{?\s*(?:st|nd|rd|th)\s*\}?')
_TEX_UNWRAP_COMMANDS = (
    'mathrm', 'mathcal', 'operatorname', 'operatorname*', 'text', 'emph',
    'mathbf', 'mathbb', 'mathsf', 'mathit', 'textrm',
)
_TEX_UNWRAP_RES = [
    re.compile(rf'\\{re.escape(cmd)}\s*\{{([^{{}}]*)\}}', flags=re.IGNORECASE)
    for cmd in _TEX_UNWRAP_COMMANDS
]
_ASCII_FOLD_REPLACEMENTS = {
    'æ': 'ae',
    'ǽ': 'ae',
    'œ': 'oe',
    'ø': 'o',
    'ð': 'd',
    'þ': 'th',
    'ł': 'l',
}
_GREEK_NAME_MAP = {
    'alpha': 'alpha',
    'beta': 'beta',
    'gamma': 'gamma',
    'delta': 'delta',
    'epsilon': 'epsilon',
    'varepsilon': 'epsilon',
    'zeta': 'zeta',
    'eta': 'eta',
    'theta': 'theta',
    'vartheta': 'theta',
    'iota': 'iota',
    'kappa': 'kappa',
    'lambda': 'lambda',
    'mu': 'mu',
    'nu': 'nu',
    'xi': 'xi',
    'omicron': 'omicron',
    'pi': 'pi',
    'varpi': 'pi',
    'rho': 'rho',
    'varrho': 'rho',
    'sigma': 'sigma',
    'varsigma': 'sigma',
    'tau': 'tau',
    'upsilon': 'upsilon',
    'phi': 'phi',
    'varphi': 'phi',
    'chi': 'chi',
    'psi': 'psi',
    'omega': 'omega',
}
_GREEK_UNICODE_MAP = {
    'α': 'alpha', 'Α': 'alpha',
    'β': 'beta', 'Β': 'beta',
    'γ': 'gamma', 'Γ': 'gamma',
    'δ': 'delta', 'Δ': 'delta',
    'ε': 'epsilon', 'Ε': 'epsilon',
    'ϵ': 'epsilon', '϶': 'epsilon',
    'ζ': 'zeta', 'Ζ': 'zeta',
    'η': 'eta', 'Η': 'eta',
    'θ': 'theta', 'Θ': 'theta',
    'ϑ': 'theta',
    'ι': 'iota', 'Ι': 'iota',
    'κ': 'kappa', 'Κ': 'kappa',
    'λ': 'lambda', 'Λ': 'lambda',
    'μ': 'mu', 'Μ': 'mu',
    'ν': 'nu', 'Ν': 'nu',
    'ξ': 'xi', 'Ξ': 'xi',
    'ο': 'omicron', 'Ο': 'omicron',
    'π': 'pi', 'Π': 'pi',
    'ϖ': 'pi',
    'ρ': 'rho', 'Ρ': 'rho',
    'ϱ': 'rho',
    'σ': 'sigma', 'ς': 'sigma', 'Σ': 'sigma',
    'τ': 'tau', 'Τ': 'tau',
    'υ': 'upsilon', 'Υ': 'upsilon',
    'φ': 'phi', 'Φ': 'phi',
    'ϕ': 'phi',
    'χ': 'chi', 'Χ': 'chi',
    'ψ': 'psi', 'Ψ': 'psi',
    'ω': 'omega', 'Ω': 'omega',
}
_TEX_GREEK_RES = [
    (
        re.compile(rf'\\{name}\b', flags=re.IGNORECASE),
        f' {ascii_name} ',
    )
    for name, ascii_name in _GREEK_NAME_MAP.items()
]
_AUTHOR_SURNAME_PARTICLES = {
    'al', 'ap', 'ben', 'bin', 'da', 'de', 'del', 'della', 'der', 'di', 'du',
    'el', 'ibn', 'la', 'le', 'st', 'ten', 'ter', 'van', 'von',
}
_AUTHOR_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


def _unwrap_tex_commands(text):
    """Unwrap common TeX presentation commands while keeping their content."""
    changed = True
    while changed:
        changed = False
        for pattern in _TEX_UNWRAP_RES:
            new_text = pattern.sub(r' \1 ', text)
            if new_text != text:
                text = new_text
                changed = True
    return text


def _ascii_fold(text):
    """Casefold and strip accents/ligatures to a comparable ASCII-ish form."""
    text = text.casefold()
    for src, dst in _ASCII_FOLD_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in text if not unicodedata.combining(c))


def _jaccard(left, right):
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _surname_set(authors, compact=False):
    """Return normalized last-name sets for an author list."""
    surnames = set()
    for name in authors:
        surname = author_last_name(name)
        if compact:
            surname = surname.replace(' ', '')
        if surname:
            surnames.add(surname)
    return surnames


def _title_similarity_from_normalized(left_norm, right_norm):
    """Score two already-normalized titles."""
    if left_norm and right_norm and left_norm.replace(' ', '') == right_norm.replace(' ', ''):
        return 1.0
    token_sim = _jaccard(set(left_norm.split()), set(right_norm.split()))
    string_sim = SequenceMatcher(None, left_norm, right_norm).ratio()
    return 0.65 * token_sim + 0.35 * string_sim


def normalize_title(text):
    """Normalize titles across TeX, HTML/MathML, Unicode, and punctuation."""
    if not text:
        return ''

    text = html.unescape(str(text))
    text = _HTML_TAG_RE.sub(' ', text)
    text = _DASH_RE.sub(' - ', text)
    text = _MATH_DELIM_RE.sub(' ', text)
    text = _unwrap_tex_commands(text)
    text = _TEX_ORDINAL_RE.sub(r'\1', text)

    for pattern, replacement in _TEX_GREEK_RES:
        text = pattern.sub(replacement, text)
    for src, dst in _GREEK_UNICODE_MAP.items():
        text = text.replace(src, f' {dst} ')

    text = _ascii_fold(text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalize_author_name(text):
    """Normalize author names for comparison across accents and punctuation."""
    if not text:
        return ''
    text = html.unescape(str(text))
    text = _ascii_fold(text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalize_author_display_name(text):
    """Normalize author punctuation/order while keeping display-friendly text."""
    if not text:
        return ''

    text = html.unescape(str(text)).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip(' ,;')
    if not text:
        return ''

    parts = [part.strip() for part in text.split(',') if part.strip()]
    if len(parts) == 2:
        if parts[1].rstrip('.').casefold() in _AUTHOR_SUFFIXES:
            text = f'{parts[0]} {parts[1]}'.strip()
        else:
            text = f'{parts[1]} {parts[0]}'.strip()
    elif len(parts) == 3 and parts[1].rstrip('.').casefold() in _AUTHOR_SUFFIXES:
        text = f'{parts[2]} {parts[0]} {parts[1]}'.strip()

    return text.lower()


def summarize_author_list_for_display(authors, limit=3):
    """Return (summary, full_list) for a list/string of author names."""
    if not authors:
        return '', ''

    if isinstance(authors, str):
        raw_names = [part.strip() for part in authors.split(';') if part.strip()]
    else:
        raw_names = [str(part).strip() for part in authors if str(part).strip()]

    normalized = [normalize_author_display_name(name) for name in raw_names]
    normalized = [name for name in normalized if name]
    if not normalized:
        return '', ''

    full_list = ', '.join(normalized)
    summary = ', '.join(normalized[:limit])
    if len(normalized) > limit:
        summary += ' et al.'
    return summary, full_list


def author_last_name(full_name):
    """Extract a normalized last name from 'First Last' or 'Last, First'."""
    if not full_name:
        return ''
    if ',' in full_name:
        return normalize_author_name(full_name.split(',', 1)[0])

    parts = str(full_name).strip().split()
    if not parts:
        return ''

    surname_parts = [parts[-1]]
    index = len(parts) - 2
    while index >= 0:
        token = normalize_author_name(parts[index])
        # Treat particles as part of the surname only when there is
        # another token before them; otherwise two-word names like
        # "Ben Cameron" and "Van Vu" should keep the final token as surname.
        if token not in _AUTHOR_SURNAME_PARTICLES or index == 0:
            break
        surname_parts.insert(0, parts[index])
        index -= 1
    return normalize_author_name(' '.join(surname_parts))


def title_similarity(left_title, right_title):
    """Blend token overlap and whole-string similarity for titles."""
    left_norm = normalize_title(left_title)
    right_norm = normalize_title(right_title)
    return _title_similarity_from_normalized(left_norm, right_norm)


def author_similarity(left_authors, right_authors, compact=False):
    """Compare author lists by normalized last-name overlap."""
    left_last_names = _surname_set(left_authors, compact=compact)
    right_last_names = _surname_set(right_authors, compact=compact)
    return _jaccard(left_last_names, right_last_names)


def score_title_author_match(left_title, left_authors, right_title, right_authors):
    """Score two records using only title and author information."""
    left_norm = normalize_title(left_title)
    right_norm = normalize_title(right_title)
    title_sim = _title_similarity_from_normalized(left_norm, right_norm)
    author_sim = author_similarity(left_authors, right_authors)

    # When titles normalize identically, Crossref author data is often a
    # truncated or punctuation-split version of the arXiv author list.
    exactish_title = bool(left_norm) and (
        left_norm.replace(' ', '') == right_norm.replace(' ', '')
    )
    if exactish_title:
        author_sim = max(author_sim, author_similarity(
            left_authors, right_authors, compact=True))
        left_compact = _surname_set(left_authors, compact=True)
        right_compact = _surname_set(right_authors, compact=True)
        if left_compact & right_compact:
            author_sim = 1.0
        elif (left_compact and right_compact
              and min(len(left_compact), len(right_compact)) >= 2
              and (left_compact <= right_compact
                   or right_compact <= left_compact)):
            author_sim = 1.0

    return 0.75 * title_sim + 0.25 * author_sim
