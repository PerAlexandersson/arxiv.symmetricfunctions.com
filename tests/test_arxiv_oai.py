import unittest
from datetime import date

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from arxiv_oai import PoliteRequester, fetch_oai_papers, fetch_rss_ids


STRUCTURED_XML = b'''<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:a="http://arxiv.org/OAI/arXiv/">
  <ListRecords>
    <record>
      <header><identifier>oai:arXiv.org:2609.12345</identifier></header>
      <metadata><a:arXiv>
        <a:id>2609.12345</a:id>
        <a:created>2026-09-12</a:created>
        <a:updated>2026-09-14</a:updated>
        <a:authors>
          <a:author><a:keyname>Lovelace</a:keyname><a:forenames>Ada</a:forenames></a:author>
          <a:author>
            <a:keyname>Example</a:keyname><a:forenames>Emmy</a:forenames>
            <a:suffix>Jr.</a:suffix>
          </a:author>
        </a:authors>
        <a:title> A multiline
          title </a:title>
        <a:categories>math.CO math.AG</a:categories>
        <a:comments>12 pages</a:comments>
        <a:journal-ref>Example Journal</a:journal-ref>
        <a:doi>10.1000/example</a:doi>
        <a:abstract>An abstract.</a:abstract>
      </a:arXiv></metadata>
    </record>
  </ListRecords>
</OAI-PMH>'''

RAW_XML = b'''<?xml version="1.0"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:r="http://arxiv.org/OAI/arXivRaw/">
  <ListRecords>
    <record>
      <header><identifier>oai:arXiv.org:2609.12345</identifier></header>
      <metadata><r:arXivRaw>
        <r:id>2609.12345</r:id>
        <r:version version="v1"><r:date>Sat, 12 Sep 2026 00:00:00 GMT</r:date></r:version>
        <r:version version="v2"><r:date>Mon, 14 Sep 2026 00:00:00 GMT</r:date></r:version>
      </r:arXivRaw></metadata>
    </record>
  </ListRecords>
</OAI-PMH>'''

RSS_XML = b'''<?xml version="1.0"?>
<rss><channel>
  <item><guid>oai:arXiv.org:2609.12345v2</guid></item>
  <item><guid>oai:arXiv.org:2609.54321v1</guid></item>
</channel></rss>'''


class QueueRequester:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url, params=None):
        return self.responses.pop(0)


class FakeResponse:
    def __init__(self, status_code, content=b''):
        self.status_code = status_code
        self.content = content
        self.url = 'https://example.test/request'


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ArxivOaiTests(unittest.TestCase):
    def test_combines_structured_metadata_with_exact_raw_version(self):
        requester = QueueRequester([STRUCTURED_XML, RAW_XML])
        papers = fetch_oai_papers(
            date(2026, 9, 12),
            date(2026, 9, 15),
            requester=requester,
        )
        self.assertEqual(1, len(papers))
        paper = papers[0]
        self.assertEqual('https://arxiv.org/abs/2609.12345v2', paper.entry_id)
        self.assertEqual('A multiline title', paper.title)
        self.assertEqual(['Ada Lovelace', 'Emmy Example Jr.'], paper.authors)
        self.assertEqual(['math.CO', 'math.AG'], paper.categories)
        self.assertEqual('math.CO', paper.primary_category)
        self.assertEqual('2026-09-12', paper.published.date().isoformat())
        self.assertEqual('2026-09-14', paper.updated.date().isoformat())
        self.assertEqual('10.1000/example', paper.doi)

    def test_rss_ids_are_stable_base_ids(self):
        ids = fetch_rss_ids(QueueRequester([RSS_XML]))
        self.assertEqual({'2609.12345', '2609.54321'}, ids)

    def test_429_uses_long_retry_delay(self):
        clock = Clock()
        session = FakeSession([
            FakeResponse(429, b'Rate exceeded.'),
            FakeResponse(200, b'<ok/>'),
        ])
        requester = PoliteRequester(
            retry_delays=(7,),
            session=session,
            sleep=clock.sleep,
            monotonic=clock.time,
        )
        self.assertEqual(b'<ok/>', requester.get('https://example.test'))
        self.assertEqual(2, session.calls)
        self.assertEqual([7], clock.sleeps)


if __name__ == '__main__':
    unittest.main()
