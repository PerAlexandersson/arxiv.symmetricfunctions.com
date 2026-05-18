"""Publication metadata parsing for DOI and DOI-less venues."""

import re
from urllib.parse import urlparse


KNOWN_NO_DOI_VENUES = {
    'jis': {
        'label': 'Journal of Integer Sequences',
        'hosts': {'cs.uwaterloo.ca', 'www.cs.uwaterloo.ca'},
        'path_prefixes': ('/journals/jis/',),
    },
    'slc': {
        'label': 'Séminaire Lotharingien de Combinatoire',
        'hosts': {
            'mat.univie.ac.at',
            'www.mat.univie.ac.at',
            'emis.de',
            'www.emis.de',
        },
        'path_prefixes': ('/~slc/', '/journals/slc/'),
    },
}

DOI_RE = re.compile(r'(10\.\d{4,9}/[^\s<>"{}|\\^`\[\]]+)', re.I)


def normalize_doi(value):
    """Return a DOI from raw text or a doi.org URL, or None."""
    text = (value or '').strip()
    if not text:
        return None
    text = re.sub(r'^doi:\s*', '', text, flags=re.I)
    match = re.search(r'doi\.org/(.+)$', text, flags=re.I)
    if match:
        text = match.group(1).strip()
    match = DOI_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip('.,;)')


def detect_known_no_doi_venue(url):
    """Return a known no-DOI venue key for URL, or None."""
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    for key, venue in KNOWN_NO_DOI_VENUES.items():
        if host in venue['hosts'] and any(
            path.startswith(prefix) for prefix in venue['path_prefixes']
        ):
            return key
    return None


def normalize_url(value):
    """Return a normalized http(s) URL, accepting bare www-style URLs."""
    text = (value or '').strip()
    if not text:
        return None
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', text) is None:
        text = f'https://{text}'
    parsed = urlparse(text)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return None
    return text


def parse_publication_input(mode, value):
    """Parse admin publication input."""
    mode = (mode or 'auto').strip().lower()
    raw = (value or '').strip()

    if mode == 'arxiv_only':
        return {
            'kind': 'arxiv_only',
            'doi': None,
            'publication_url': None,
            'publication_venue_key': 'arxiv',
            'publication_status': 'arxiv_only',
            'doi_status': 'skipped',
        }

    if mode in {'auto', 'doi'}:
        doi = normalize_doi(raw)
        if doi:
            return {
                'kind': 'doi',
                'doi': doi,
                'publication_url': None,
                'publication_venue_key': None,
                'publication_status': 'published',
                'doi_status': 'verified',
            }
        if mode == 'doi':
            raise ValueError('Could not parse a DOI from the input.')

    url = normalize_url(raw)
    if not url:
        raise ValueError('Enter a DOI, DOI URL, or publication URL.')

    venue_key = detect_known_no_doi_venue(url)
    if mode == 'known_no_doi' and not venue_key:
        raise ValueError('This URL is not recognized as a known no-DOI venue.')

    if venue_key:
        return {
            'kind': 'known_no_doi',
            'doi': None,
            'publication_url': url,
            'publication_venue_key': venue_key,
            'publication_status': 'known_no_doi',
            'doi_status': 'skipped',
        }

    return {
        'kind': 'publication_url',
        'doi': None,
        'publication_url': url,
        'publication_venue_key': None,
        'publication_status': 'published',
        'doi_status': None,
    }


def publication_venue_label(venue_key):
    """Human label for a known venue key."""
    if venue_key == 'arxiv':
        return 'arXiv only'
    venue = KNOWN_NO_DOI_VENUES.get(venue_key)
    return venue['label'] if venue else None
