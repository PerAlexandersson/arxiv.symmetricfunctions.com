import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from doi_triage import (
    arxiv_base_id,
    classify_candidate,
    enrich_replacement_decisions,
    enrich_metadata_decisions,
    normalize_doi,
)


def candidate(**overrides):
    row = {
        'id': 7,
        'paper_id': 11,
        'arxiv_id': '2211.02774v3',
        'doi': '10.1000/example',
        'paper_title': 'A theorem about graphs',
        'paper_authors': ['Jesse Campion Loth'],
        'crossref_title': 'A theorem about graphs',
        'crossref_authors': 'Campion Loth, Jesse',
    }
    row.update(overrides)
    return row


def record(doi='10.1000/example', title='A theorem about graphs'):
    return {
        'title': title,
        'authors': [{'name': 'Jesse Campion Loth'}],
        'externalIds': {'DOI': doi},
    }


class IdentifierTests(unittest.TestCase):
    def test_normalize_doi_removes_resolver_prefix(self):
        self.assertEqual(
            '10.1000/example',
            normalize_doi('HTTPS://DOI.ORG/10.1000/Example.'),
        )

    def test_arxiv_base_id_strips_only_revision(self):
        self.assertEqual('2211.02774', arxiv_base_id('2211.02774v3'))
        self.assertEqual('math/0001175', arxiv_base_id('math/0001175v2'))


class ClassificationTests(unittest.TestCase):
    def test_exact_external_agreement_is_approved(self):
        result = classify_candidate(candidate(), record(), set())
        self.assertEqual('approve_confirmed', result['decision'])

    def test_exact_agreement_with_assignment_conflict_needs_review(self):
        result = classify_candidate(
            candidate(), record(), {'10.1000/example'})
        self.assertEqual('review_exact_conflict', result['decision'])

    def test_exact_agreement_with_pending_duplicate_needs_review(self):
        result = classify_candidate(
            candidate(), record(), {'10.1000/example'})
        self.assertEqual('review_exact_conflict', result['decision'])

    def test_strong_different_doi_is_a_replacement(self):
        result = classify_candidate(
            candidate(), record(doi='10.1000/better'), set())
        self.assertEqual('replacement_confirmed', result['decision'])

    def test_missing_external_doi_remains_unresolved(self):
        result = classify_candidate(
            candidate(crossref_title='A different article'),
            {'title': 'A theorem about graphs'},
            set(),
        )
        self.assertEqual('unresolved', result['decision'])

    def test_exact_metadata_without_external_doi_is_staged(self):
        result = classify_candidate(
            candidate(), {'title': 'A theorem about graphs'}, set())
        self.assertEqual('metadata_exact', result['decision'])

    def test_replacement_requires_matching_crossref_metadata(self):
        row = candidate()
        decision = classify_candidate(
            row, record(doi='10.1000/better'), set())
        crossref = {
            '10.1000/better': {
                'DOI': '10.1000/better',
                'title': ['A theorem about graphs'],
                'author': [{'family': 'Campion Loth', 'given': 'Jesse'}],
                'container-title': ['Journal'],
                'issued': {'date-parts': [[2023]]},
            },
        }
        row['published_date'] = '2022-11-01'
        enrich_replacement_decisions(
            [decision], {row['id']: row}, crossref)
        self.assertEqual('approve_replacement', decision['decision'])

    def test_exact_metadata_requires_live_crossref_confirmation(self):
        row = candidate()
        row['published_date'] = '2022-11-01'
        decision = classify_candidate(
            row, {'title': 'A theorem about graphs'}, set())
        crossref = {
            '10.1000/example': {
                'DOI': '10.1000/example',
                'title': ['A theorem about graphs'],
                'author': [{'family': 'Campion Loth', 'given': 'Jesse'}],
                'container-title': ['Journal'],
                'issued': {'date-parts': [[2023]]},
            },
        }
        enrich_metadata_decisions(
            [decision], {row['id']: row}, crossref)
        self.assertEqual('approve_metadata_exact', decision['decision'])


if __name__ == '__main__':
    unittest.main()
