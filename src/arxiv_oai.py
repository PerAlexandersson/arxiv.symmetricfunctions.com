"""Polite OAI-PMH and RSS access for incremental arXiv metadata updates."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import os
import re
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set
import xml.etree.ElementTree as ET

import requests


OAI_ENDPOINT = 'https://oaipmh.arxiv.org/oai'
OAI_SET = 'math:math:CO'
RSS_URL = 'https://rss.arxiv.org/rss/math.CO'
USER_AGENT = 'arxiv.symmetricfunctions.com metadata fetcher'
MIN_REQUEST_DELAY = 3.5
DEFAULT_RETRY_DELAYS = (30, 120, 600)

OAI_NS = 'http://www.openarchives.org/OAI/2.0/'
ARXIV_NS = 'http://arxiv.org/OAI/arXiv/'
ARXIV_RAW_NS = 'http://arxiv.org/OAI/arXivRaw/'
DC_NS = 'http://purl.org/dc/elements/1.1/'


class ArxivMetadataError(RuntimeError):
    """Raised when an arXiv metadata service cannot provide a valid result."""


@dataclass
class OaiPaper:
    """The subset of ``arxiv.Result`` consumed by ``insert_or_update_paper``."""

    entry_id: str
    title: str
    summary: str
    published: datetime
    updated: datetime
    comment: Optional[str]
    journal_ref: Optional[str]
    doi: Optional[str]
    primary_category: str
    authors: List[str]
    categories: List[str]


def retry_delays_from_env() -> Sequence[int]:
    """Return configurable long retry delays for 429 and transient failures."""
    raw = os.environ.get('ARXIV_RETRY_DELAYS', '').strip()
    if not raw:
        return DEFAULT_RETRY_DELAYS
    if raw.lower() in {'none', 'off', '0'}:
        return ()
    try:
        delays = tuple(int(part.strip()) for part in raw.split(','))
    except ValueError as exc:
        raise ValueError('ARXIV_RETRY_DELAYS must be comma-separated seconds') from exc
    if any(delay < 0 for delay in delays):
        raise ValueError('ARXIV_RETRY_DELAYS cannot contain negative values')
    return delays


class PoliteRequester:
    """Serialize arXiv requests and back off well beyond the three-second floor."""

    def __init__(
        self,
        retry_delays: Optional[Sequence[int]] = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.retry_delays = tuple(
            retry_delays_from_env() if retry_delays is None else retry_delays
        )
        self.session = session or requests.Session()
        self.sleep = sleep
        self.monotonic = monotonic
        self.last_request_at = None

    def get(self, url: str, params: Optional[Dict[str, str]] = None) -> bytes:
        attempts = len(self.retry_delays) + 1
        last_error = None
        for attempt in range(attempts):
            self._wait_for_rate_limit()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={'User-Agent': USER_AGENT},
                    timeout=60,
                )
                self.last_request_at = self.monotonic()
                if response.status_code == 200:
                    return response.content
                retryable = response.status_code == 429 or response.status_code >= 500
                last_error = ArxivMetadataError(
                    f'arXiv metadata request returned HTTP {response.status_code}: '
                    f'{response.url}'
                )
                if not retryable:
                    raise last_error
            except requests.RequestException as exc:
                self.last_request_at = self.monotonic()
                last_error = ArxivMetadataError(
                    f'arXiv metadata request failed: {exc}'
                )

            if attempt < len(self.retry_delays):
                delay = self.retry_delays[attempt]
                print(
                    f'  arXiv metadata temporarily unavailable; retrying in '
                    f'{delay} seconds ({attempt + 1}/{len(self.retry_delays)}).'
                )
                self.sleep(delay)

        raise last_error or ArxivMetadataError('arXiv metadata request failed')

    def _wait_for_rate_limit(self):
        if self.last_request_at is None:
            return
        elapsed = self.monotonic() - self.last_request_at
        if elapsed < MIN_REQUEST_DELAY:
            self.sleep(MIN_REQUEST_DELAY - elapsed)


def _oai_tag(namespace: str, name: str) -> str:
    return f'{{{namespace}}}{name}'


def _text(element: ET.Element, namespace: str, name: str) -> Optional[str]:
    value = element.findtext(_oai_tag(namespace, name))
    return value.strip() if value and value.strip() else None


def _list_oai_metadata(
    requester: PoliteRequester,
    metadata_prefix: str,
    start_date: date,
    end_date: date,
) -> Dict[str, ET.Element]:
    """Return all records in the inclusive OAI datestamp range, following pages."""
    params = {
        'verb': 'ListRecords',
        'from': start_date.isoformat(),
        'until': end_date.isoformat(),
        'set': OAI_SET,
        'metadataPrefix': metadata_prefix,
    }
    records = {}
    while True:
        root = ET.fromstring(requester.get(OAI_ENDPOINT, params=params))
        error = root.find(_oai_tag(OAI_NS, 'error'))
        if error is not None:
            if error.attrib.get('code') == 'noRecordsMatch':
                return records
            raise ArxivMetadataError(
                f"OAI-PMH {error.attrib.get('code', 'error')}: "
                f"{(error.text or '').strip()}"
            )

        list_records = root.find(_oai_tag(OAI_NS, 'ListRecords'))
        if list_records is None:
            raise ArxivMetadataError('OAI-PMH response has no ListRecords element')
        for record in list_records.findall(_oai_tag(OAI_NS, 'record')):
            header = record.find(_oai_tag(OAI_NS, 'header'))
            if header is None or header.attrib.get('status') == 'deleted':
                continue
            identifier = header.findtext(_oai_tag(OAI_NS, 'identifier')) or ''
            base_id = identifier.removeprefix('oai:arXiv.org:').strip()
            metadata = record.find(_oai_tag(OAI_NS, 'metadata'))
            if not base_id or metadata is None or len(metadata) != 1:
                continue
            records[base_id] = metadata[0]

        token = list_records.findtext(_oai_tag(OAI_NS, 'resumptionToken'))
        if not token or not token.strip():
            break
        params = {'verb': 'ListRecords', 'resumptionToken': token.strip()}
    return records


def _parse_date(value: Optional[str], field: str) -> datetime:
    if not value:
        raise ArxivMetadataError(f'OAI-PMH record has no {field}')
    try:
        return datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        return parsedate_to_datetime(value).astimezone(timezone.utc)


def _version_number(raw: ET.Element) -> int:
    versions = raw.findall(_oai_tag(ARXIV_RAW_NS, 'version'))
    if not versions:
        raise ArxivMetadataError('arXivRaw record has no version history')
    value = versions[-1].attrib.get('version', '')
    match = re.fullmatch(r'v([1-9][0-9]*)', value)
    if not match:
        raise ArxivMetadataError(f'Invalid arXiv version value: {value!r}')
    return int(match.group(1))


def _author_name(author: ET.Element) -> str:
    forenames = _text(author, ARXIV_NS, 'forenames') or ''
    keyname = _text(author, ARXIV_NS, 'keyname') or ''
    suffix = _text(author, ARXIV_NS, 'suffix') or ''
    name = ' '.join(part for part in (forenames, keyname, suffix) if part)
    if not name:
        raise ArxivMetadataError('OAI-PMH record contains an empty author')
    return name


def fetch_oai_papers(
    start_date: date,
    end_date: date,
    requester: Optional[PoliteRequester] = None,
) -> List[OaiPaper]:
    """Fetch complete current metadata for math.CO records changed in a date range."""
    requester = requester or PoliteRequester()
    structured = _list_oai_metadata(requester, 'arXiv', start_date, end_date)
    raw = _list_oai_metadata(requester, 'arXivRaw', start_date, end_date)
    if set(structured) != set(raw):
        missing_structured = sorted(set(raw) - set(structured))
        missing_raw = sorted(set(structured) - set(raw))
        raise ArxivMetadataError(
            'OAI-PMH metadata formats returned different record sets; '
            f'missing structured={missing_structured[:5]}, missing raw={missing_raw[:5]}'
        )

    papers = []
    for base_id, metadata in structured.items():
        version = _version_number(raw[base_id])
        categories = (_text(metadata, ARXIV_NS, 'categories') or '').split()
        if not categories:
            raise ArxivMetadataError(f'OAI-PMH record {base_id} has no categories')
        authors_parent = metadata.find(_oai_tag(ARXIV_NS, 'authors'))
        authors = [] if authors_parent is None else [
            _author_name(author)
            for author in authors_parent.findall(_oai_tag(ARXIV_NS, 'author'))
        ]
        created = _parse_date(_text(metadata, ARXIV_NS, 'created'), 'created date')
        updated = _parse_date(
            _text(metadata, ARXIV_NS, 'updated') or created.date().isoformat(),
            'updated date',
        )
        papers.append(OaiPaper(
            entry_id=f'https://arxiv.org/abs/{base_id}v{version}',
            title=' '.join((_text(metadata, ARXIV_NS, 'title') or '').split()),
            summary=(_text(metadata, ARXIV_NS, 'abstract') or '').strip(),
            published=created,
            updated=updated,
            comment=_text(metadata, ARXIV_NS, 'comments'),
            journal_ref=_text(metadata, ARXIV_NS, 'journal-ref'),
            doi=_text(metadata, ARXIV_NS, 'doi'),
            primary_category=categories[0],
            authors=authors,
            categories=categories,
        ))
    return papers


def fetch_rss_ids(requester: Optional[PoliteRequester] = None) -> Set[str]:
    """Return stable arXiv IDs in the current math.CO announcement feed."""
    requester = requester or PoliteRequester()
    root = ET.fromstring(requester.get(RSS_URL))
    channel = root.find('channel')
    if channel is None:
        raise ArxivMetadataError('arXiv RSS response has no channel')
    ids = set()
    for item in channel.findall('item'):
        guid = (item.findtext('guid') or '').strip()
        value = guid.removeprefix('oai:arXiv.org:')
        value = re.sub(r'v[0-9]+$', '', value)
        if value:
            ids.add(value)
    return ids
