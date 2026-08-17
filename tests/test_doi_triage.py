import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from doi_triage import (
    arxiv_base_id,
    classify_candidate,
    enrich_replacement_decisions,
    enrich_metadata_decisions,
    enrich_conflict_decisions,
    enrich_exact_external_decisions,
    enrich_journal_reference_decisions,
    enrich_resolver_replacement_decisions,
    is_preprint_doi,
    is_known_doi_less_journal,
    journal_reference_evidence,
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

    def test_arxiv_preprint_doi_is_not_a_publication_doi(self):
        self.assertTrue(is_preprint_doi('https://doi.org/10.48550/arXiv.2211.02774'))
        self.assertFalse(is_preprint_doi('10.1016/j.ejc.2024.104019'))

    def test_known_doi_less_journal_is_recognized(self):
        self.assertTrue(is_known_doi_less_journal(
            'Journal of Integer Sequences, Vol. 15 (2012), Article 12.7.3'))
        self.assertFalse(is_known_doi_less_journal(
            'Journal of Combinatorial Theory, Series A 120 (2013)'))


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

    def test_near_exact_metadata_with_article_word_is_staged(self):
        result = classify_candidate(
            candidate(
                paper_title='Lower bounds for the depth of second powers',
                crossref_title=(
                    'Lower bounds for the depth of the second powers'
                ),
            ),
            {'title': 'Lower bounds for the depth of second powers'},
            set(),
        )
        self.assertEqual('metadata_exact', result['decision'])

    def test_strong_renamed_metadata_is_prioritized_for_manual_review(self):
        result = classify_candidate(
            candidate(
                paper_title=(
                    'Rainbow solutions to the Sidon equation in cyclic groups'
                ),
                crossref_title=(
                    'Rainbow solutions to the Sidon equation in cyclic groups '
                    'and the interval'
                ),
                paper_authors=['Zhanar Berikkyzy', 'Jürgen Kritschgau'],
                crossref_authors='Berikkyzy, Zhanar; Kritschgau, Jürgen',
            ),
            None,
            set(),
        )
        self.assertEqual('review_high_evidence', result['decision'])

    def test_high_evidence_conflict_is_not_prioritized_as_unambiguous(self):
        result = classify_candidate(
            candidate(
                paper_title=(
                    'Rainbow solutions to the Sidon equation in cyclic groups'
                ),
                crossref_title=(
                    'Rainbow solutions to the Sidon equation in cyclic groups '
                    'and the interval'
                ),
                paper_authors=['Zhanar Berikkyzy', 'Jürgen Kritschgau'],
                crossref_authors='Berikkyzy, Zhanar; Kritschgau, Jürgen',
            ),
            None,
            {'10.1000/example'},
        )
        self.assertEqual('unresolved', result['decision'])

    def test_arxiv_preprint_doi_is_ignored_as_external_evidence(self):
        result = classify_candidate(
            candidate(crossref_title='A different article'),
            record(doi='10.48550/arxiv.2211.02774'),
            set(),
        )
        self.assertEqual('unresolved', result['decision'])
        self.assertEqual(
            '10.48550/arxiv.2211.02774',
            result['ignored_preprint_doi'],
        )

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

    def test_non_crossref_replacement_accepts_csl_metadata(self):
        row = candidate()
        row['published_date'] = '2022-11-01'
        decision = classify_candidate(
            row, record(doi='10.4230/example'), set())
        decision['decision'] = 'review_replacement_no_crossref'
        resolver = {
            '10.4230/example': {
                'DOI': '10.4230/example',
                'title': 'A theorem about graphs',
                'author': [{'family': 'Campion Loth', 'given': 'Jesse'}],
                'container-title': 'Proceedings',
                'issued': {'date-parts': [[2023]]},
            },
        }
        enrich_resolver_replacement_decisions(
            [decision], {row['id']: row}, resolver)
        self.assertEqual('approve_replacement', decision['decision'])
        self.assertEqual(
            'doi_resolver', decision['replacement_metadata_source'])

    def test_non_crossref_replacement_rejects_repository_copy(self):
        row = candidate()
        decision = classify_candidate(
            row, record(doi='10.13016/example'), set())
        decision['decision'] = 'review_replacement_no_crossref'
        resolver = {
            '10.13016/example': {
                'DOI': '10.13016/example',
                'title': 'A theorem about graphs',
                'author': [{'family': 'Campion Loth', 'given': 'Jesse'}],
                'publisher': 'Digital Repository at Example University',
                'URL': 'https://example.edu/handle/1234/5678',
            },
        }
        enrich_resolver_replacement_decisions(
            [decision], {row['id']: row}, resolver)
        self.assertEqual('review_replacement_repository', decision['decision'])

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

    def test_conflict_is_rejected_when_existing_assignment_is_better(self):
        row = candidate(crossref_title='The published title')
        decision = classify_candidate(row, None, {'10.1000/example'})
        assignments = {
            '10.1000/example': [{
                'paper_id': 99,
                'arxiv_id': '2201.00001v1',
                'doi_status': 'verified',
                'paper_title': 'The published title',
                'paper_authors': ['Jesse Campion Loth'],
            }],
        }
        enrich_conflict_decisions(
            [decision], {row['id']: row}, assignments)
        self.assertEqual(
            'reject_conflict_assigned_better', decision['decision'])

    def test_weak_exact_link_accepts_live_title_and_author_coverage(self):
        row = candidate(
            paper_title='Hypercontractivity: Approximate decompositions',
            crossref_title='Hypercontractivity',
            paper_authors=['Vincent E. Coll', 'Nicholas W. Mayers'],
        )
        decision = classify_candidate(row, record(), set())
        decision['decision'] = 'review_exact_weak_metadata'
        crossref = {
            '10.1000/example': {
                'DOI': '10.1000/example',
                'title': ['Hypercontractivity: Approximate decompositions'],
                'author': [
                    {'family': 'Coll', 'given': 'Vincent'},
                    {'family': 'Mayers', 'given': 'Nicholas W.'},
                    {'family': 'Russoniello', 'given': 'Nicholas'},
                ],
            },
        }
        enrich_exact_external_decisions(
            [decision], {row['id']: row}, crossref, {})
        self.assertEqual('approve_exact_external', decision['decision'])

    def test_journal_reference_corroborates_changed_publication_title(self):
        row = candidate(
            paper_title='Catalan intervals and realizers of triangulations',
            paper_authors=['Olivier Bernardi', 'Nicolas Bonichon'],
            journal_ref=(
                'Journal of Combinatorial Theory Series A 116, 1 (2009) '
                '55-75'
            ),
        )
        decision = classify_candidate(row, None, set())
        crossref = {
            '10.1000/example': {
                'DOI': '10.1000/example',
                'title': [
                    'Intervals in Catalan lattices and realizers of '
                    'triangulations'
                ],
                'author': [
                    {'family': 'Bernardi', 'given': 'Olivier'},
                    {'family': 'Bonichon', 'given': 'Nicolas'},
                ],
                'container-title': [
                    'Journal of Combinatorial Theory, Series A'
                ],
                'volume': '116',
                'page': '55-75',
                'issued': {'date-parts': [[2009]]},
            },
        }
        enrich_journal_reference_decisions(
            [decision], {row['id']: row}, crossref, {})
        self.assertEqual('approve_journal_reference', decision['decision'])
        self.assertTrue(decision['journal_bibliographic_match'])

    def test_doi_less_journal_overrides_false_candidate(self):
        row = candidate(
            journal_ref=(
                'Journal of Integer Sequences, Vol. 15 (2012), '
                'Article 12.7.3'
            ),
        )
        decision = classify_candidate(row, record(), set())
        enrich_journal_reference_decisions(
            [decision], {row['id']: row}, {}, {})
        self.assertEqual('skip_known_doi_less', decision['decision'])


class JournalReferenceTests(unittest.TestCase):
    def test_bibliographic_evidence_matches_start_page(self):
        evidence = journal_reference_evidence(
            'Discrete Optimization, 14:72-77, 2014',
            {
                'container-title': ['Discrete Optimization'],
                'volume': '14',
                'page': '72',
                'issued': {'date-parts': [[2014]]},
            },
        )
        self.assertTrue(evidence['bibliographic_match'])


if __name__ == '__main__':
    unittest.main()
