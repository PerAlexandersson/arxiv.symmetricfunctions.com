"""Utilities for normalizing titles/authors and scoring text similarity."""

from difflib import SequenceMatcher
import html
import re
import unicodedata

_DASH_RE = re.compile(r'--+|[‐‑‒–—−-]+')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_TEX_UNICODE_RE = re.compile(r'\\unicode\s*\{\s*(x[0-9a-f]{1,6}|[0-9]{1,7})\s*\}', re.I)
_MATHML_RE = re.compile(
    r'<(?P<ns>[\w.-]+:)?math\b[^>]*>(?P<body>.*?)</(?(ns)(?P=ns))math\s*>',
    re.I | re.S,
)
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
_TEX_DECLARATION_RE = re.compile(
    r'\\(?:rm|bf|it|cal|sf|tt)\b',
    flags=re.IGNORECASE,
)
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
_TITLE_WORD_NORMALIZATIONS = {
    'analogue': 'analog',
    'analogues': 'analogs',
    'behaviour': 'behavior',
    'behaviours': 'behaviors',
    'catalogue': 'catalog',
    'catalogues': 'catalogs',
    'centre': 'center',
    'centres': 'centers',
    'colour': 'color',
    'colours': 'colors',
    'coloured': 'colored',
    'colouring': 'coloring',
    'colourings': 'colorings',
    'fibre': 'fiber',
    'fibres': 'fibers',
    'labelled': 'labeled',
    'labelling': 'labeling',
    'modelling': 'modeling',
    'optimisation': 'optimization',
    'optimisations': 'optimizations',
    'randomisation': 'randomization',
    'randomisations': 'randomizations',
}
_AUTHOR_SURNAME_PARTICLES = {
    'al', 'ap', 'ben', 'bin', 'da', 'de', 'del', 'della', 'der', 'di', 'du',
    'el', 'ibn', 'la', 'le', 'st', 'ten', 'ter', 'van', 'von',
}
_AUTHOR_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}
AUTHOR_MISSING_PENALTY = 0.20
AUTHOR_ADDED_PENALTY = 0.15
AUTHOR_CONTRADICTION_PENALTY = 0.50
AUTHOR_VARIANT_SIMILARITY = 0.85


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


def _author_name_tokens(name):
    """Return normalized name tokens, omitting generational suffixes."""
    return [
        token for token in normalize_author_name(name).split()
        if token not in _AUTHOR_SUFFIXES
    ]


def _author_given_token(name):
    """Return the first normalized given-name token when one is supplied."""
    raw = str(name or '')
    if ',' in raw:
        given = raw.split(',', 1)[1]
        # Given-name initials such as V. are not generational suffixes.
        tokens = normalize_author_name(given).split()
        return tokens[0] if tokens else ''

    tokens = normalize_author_name(raw).split()
    surname_tokens = author_last_name(raw).split()
    if surname_tokens and tokens[-len(surname_tokens):] == surname_tokens:
        tokens = tokens[:-len(surname_tokens)]
    return tokens[0] if tokens else ''


def _author_name_similarity(left_name, right_name):
    """Compare one author name without assuming a given-name/surname order.

    Crossref normally stores names as ``family, given``, but real deposits also
    contain multiword surnames, reversed Asian names, and occasionally swapped
    family/given fields. Token matching handles these cases while still
    requiring a shared non-initial token before initials may match.
    """
    left = _author_name_tokens(left_name)
    right = _author_name_tokens(right_name)
    if not left or not right:
        return 0.0

    left_surname = author_last_name(left_name).replace(' ', '')
    right_surname = author_last_name(right_name).replace(' ', '')
    left_given = _author_given_token(left_name)
    right_given = _author_given_token(right_name)
    if (
        left_surname
        and left_surname == right_surname
        and left_given
        and right_given
        and left_given[0] == right_given[0]
        and (
            left_given == right_given
            or len(left_given) == 1
            or len(right_given) == 1
        )
    ):
        # Middle names, patronymics, and abbreviated given names vary widely
        # between arXiv and registry deposits. An exact surname plus compatible
        # first initial is a stable author-identity signal.
        return 1.0

    shared_words = {
        token for token in set(left) & set(right)
        if len(token) > 1
    }
    if not shared_words:
        return 0.0

    available = list(right)
    matched_left = set()
    matched = 0
    # Match exact tokens first so that initials cannot consume full-name tokens.
    for index, token in enumerate(left):
        if token in available:
            available.remove(token)
            matched_left.add(index)
            matched += 1
    for index, token in enumerate(left):
        if index in matched_left:
            continue
        match_index = next(
            (
                other_index
                for other_index, other in enumerate(available)
                if (len(token) == 1 or len(other) == 1)
                and token[0] == other[0]
            ),
            None,
        )
        if match_index is not None:
            available.pop(match_index)
            matched += 1

    return matched / max(len(left), len(right))


def _author_list_name_match_total(left_authors, right_authors):
    """Greedily pair author names and return the total matched-name score."""
    if not left_authors or not right_authors:
        return 0.0
    scores = sorted(
        (
            (_author_name_similarity(left, right), left_index, right_index)
            for left_index, left in enumerate(left_authors)
            for right_index, right in enumerate(right_authors)
        ),
        reverse=True,
    )
    used_left = set()
    used_right = set()
    total = 0.0
    for score, left_index, right_index in scores:
        if score <= 0.0:
            break
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        total += score
    return total


def _author_list_name_similarity(left_authors, right_authors):
    """Return order-independent author overlap over the longer list."""
    total = _author_list_name_match_total(left_authors, right_authors)
    if not left_authors or not right_authors:
        return 0.0
    return total / max(len(left_authors), len(right_authors))


def _title_similarity_from_normalized(left_norm, right_norm):
    """One minus word edit distance divided by the longer title's word count."""
    if not left_norm or not right_norm:
        return 0.0
    if left_norm and right_norm and left_norm.replace(' ', '') == right_norm.replace(' ', ''):
        return 1.0
    left, right = left_norm.split(), right_norm.split()
    previous = list(range(len(right) + 1))
    for i, word in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (word != other)))
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def _normalize_regional_spellings(text):
    """Canonicalize a small curated set of British/American spellings."""
    if not text:
        return ''
    return ' '.join(_TITLE_WORD_NORMALIZATIONS.get(word, word) for word in text.split())


def _decode_tex_unicode(match):
    """Decode MathJax Unicode escapes, leaving invalid scalar values intact."""
    value = match.group(1)
    codepoint = int(value[1:], 16) if value.lower().startswith('x') else int(value)
    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        return match.group(0)
    char = chr(codepoint)
    return char if not unicodedata.category(char).startswith('C') else match.group(0)


def _remove_duplicate_mathml_symbols(text):
    """Drop a MathML Greek symbol repeated immediately after its plain-text copy.

    Some publisher deposits include both renderings. Keep standalone MathML,
    different symbols, and repeated symbols within mathematical expressions.
    """
    def replace(match):
        symbol = _HTML_TAG_RE.sub('', match.group('body')).strip()
        prefix = text[:match.start()].rstrip()
        if (symbol in _GREEK_UNICODE_MAP and prefix.endswith(symbol)
                and (len(prefix) == 1 or not prefix[-2].isalnum())):
            return ''
        return match.group(0)

    return _MATHML_RE.sub(replace, text)


def normalize_title(text):
    """Normalize titles across TeX, HTML/MathML, Unicode, and punctuation."""
    if not text:
        return ''

    text = html.unescape(str(text))
    text = _TEX_UNICODE_RE.sub(_decode_tex_unicode, text)
    text = _remove_duplicate_mathml_symbols(text)
    text = _HTML_TAG_RE.sub(' ', text)
    text = _DASH_RE.sub(' - ', text)
    text = _MATH_DELIM_RE.sub(' ', text)
    text = _unwrap_tex_commands(text)
    text = _TEX_DECLARATION_RE.sub('', text)
    text = _TEX_ORDINAL_RE.sub(r'\1', text)

    for pattern, replacement in _TEX_GREEK_RES:
        text = pattern.sub(replacement, text)
    for src, dst in _GREEK_UNICODE_MAP.items():
        text = text.replace(src, f' {dst} ')

    text = _ascii_fold(text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = _normalize_regional_spellings(text)
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
    """Compare normalized titles by proportional word edits."""
    left_norm = normalize_title(left_title)
    right_norm = normalize_title(right_title)
    return _title_similarity_from_normalized(left_norm, right_norm)


def author_similarity(left_authors, right_authors, compact=False):
    """Compare author lists by normalized last-name overlap."""
    left_last_names = _surname_set(left_authors, compact=compact)
    right_last_names = _surname_set(right_authors, compact=compact)
    surname_similarity = _jaccard(left_last_names, right_last_names)
    name_similarity = _author_list_name_similarity(left_authors, right_authors)
    names_are_complete = (
        all(len(_author_name_tokens(name)) >= 2 for name in left_authors)
        and all(len(_author_name_tokens(name)) >= 2 for name in right_authors)
    )
    if names_are_complete:
        return name_similarity
    return max(surname_similarity, name_similarity)


def author_coverage_similarity(left_authors, right_authors):
    """Return matched-name coverage of the shorter author list.

    This is useful as supporting evidence when a publication adds or omits
    authors, but should not replace the stricter list similarity in fuzzy DOI
    discovery.
    """
    if not left_authors or not right_authors:
        return 0.0
    total = _author_list_name_match_total(left_authors, right_authors)
    return min(1.0, total / min(len(left_authors), len(right_authors)))


def _author_identity_matches(left, right):
    surname = author_last_name(left).replace(' ', '')
    other_surname = author_last_name(right).replace(' ', '')
    surname_agrees = bool(surname and surname == other_surname)
    # A structured family field can disambiguate an unhyphenated compound
    # surname in arXiv's display name, e.g. "Jesse Campion Loth".
    for plain, structured in ((left, right), (right, left)):
        if ',' not in plain and ',' in structured:
            family = author_last_name(structured)
            if family and normalize_author_name(plain).endswith(' ' + family):
                surname_agrees = True
    if not surname_agrees:
        return False
    given, other = _author_given_token(left), _author_given_token(right)
    return bool(given and other and given[0] == other[0]
                and (given == other or len(given) == 1 or len(other) == 1))


def _pair_authors(left, right, compatible):
    """Maximum one-to-one pairing, returned as right-index -> left-index."""
    edges = [[j for j, other in enumerate(right) if compatible(name, other)] for name in left]
    paired = {}
    for start in range(len(left)):
        queue, parents_left, parents_right = [start], {start: None}, {}
        free = None
        for i in queue:
            for j in edges[i]:
                if j in parents_right:
                    continue
                parents_right[j] = i
                if j not in paired:
                    free = j
                    break
                next_left = paired[j]
                if next_left not in parents_left:
                    parents_left[next_left] = j
                    queue.append(next_left)
            if free is not None:
                break
        while free is not None:
            i = parents_right[free]
            paired[free] = i
            free = parents_left[i]
    return paired


def _author_variant_or_incomplete(left, right):
    """Possible metadata variant, not sufficient evidence for an identity match.

    Short/absent given names alone do not establish a contradiction; a clearly
    different surname still can. Malformed TeX and close variants are uncertain.
    This predicate never gives full author credit or enables auto-approval.
    """
    if '\\' in left or '\\' in right:
        return True
    left_tokens = normalize_author_name(normalize_author_display_name(left)).split()
    right_tokens = normalize_author_name(normalize_author_display_name(right)).split()
    # Added given/family name components and malformed merged author fields
    # are evidence of uncertainty rather than a different identity.
    if set(left_tokens) <= set(right_tokens) or set(right_tokens) <= set(left_tokens):
        return True
    surname = author_last_name(left).replace(' ', '')
    other_surname = author_last_name(right).replace(' ', '')
    if (len(_author_given_token(left)) <= 2 or len(_author_given_token(right)) <= 2):
        # An incomplete given name does not erase a clearly different surname.
        surname_similarity = SequenceMatcher(None, surname, other_surname,
                                             autojunk=False).ratio()
        if surname_similarity >= AUTHOR_VARIANT_SIMILARITY:
            return True
    left_key, right_key = ''.join(left_tokens), ''.join(right_tokens)
    similarity = SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()
    return similarity >= AUTHOR_VARIANT_SIMILARITY


def author_changes(arxiv_authors, publication_authors):
    """Proportional author changes plus a separate identity-contradiction cost.

    Exact one-to-one matches receive full credit. Unmatched names can be
    incomplete or plausible variants; pair these conservatively before
    counting contradictions. Pure additions/omissions retain their old cost.
    """
    left = [name for name in arxiv_authors if str(name).strip()]
    right = [name for name in publication_authors if str(name).strip()]
    paired = _pair_authors(left, right, _author_identity_matches)
    matched = len(paired)
    missing, added = len(left) - matched, len(right) - matched
    unmatched_left = [name for i, name in enumerate(left) if i not in paired.values()]
    unmatched_right = [name for j, name in enumerate(right) if j not in paired]
    uncertain = len(_pair_authors(unmatched_left, unmatched_right, _author_variant_or_incomplete))
    contradictions = min(missing, added) - uncertain
    change_penalty = ((AUTHOR_MISSING_PENALTY * missing + AUTHOR_ADDED_PENALTY * added)
                      / len(left) if left else AUTHOR_MISSING_PENALTY)
    contradiction_penalty = AUTHOR_CONTRADICTION_PENALTY if contradictions else 0.0
    penalty = change_penalty + contradiction_penalty
    return dict(matched=matched, missing=missing, added=added, penalty=penalty,
                contradictions=contradictions, uncertain=uncertain,
                change_penalty=change_penalty, contradiction_penalty=contradiction_penalty,
                complete=bool(left and right),
                conflicting=bool(missing and added))


def score_title_author_match(left_title, left_authors, right_title, right_authors):
    """Title agreement minus directional, proportional author deductions."""
    return max(0.0, title_similarity(left_title, right_title)
               - author_changes(left_authors, right_authors)['penalty'])
