import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from fulltext_keyword_prototype import (
    Artifact,
    analyze_paper,
    normalize_arxiv_base_id,
    pdf_paragraphs,
    structured_paragraphs,
)
from extract_keywords import tokenize


class FulltextKeywordPrototypeTests(unittest.TestCase):
    def test_normalizes_modern_and_legacy_arxiv_ids(self):
        cases = {
            'arXiv:2601.12345v3': '2601.12345',
            'https://arxiv.org/pdf/2401.01234v2.pdf': '2401.01234',
            'https://arxiv.org/abs/math/0601001v4': 'math/0601001',
            'MATH/0601001': 'math/0601001',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(expected, normalize_arxiv_base_id(value))
        self.assertIsNone(normalize_arxiv_base_id('not-an-id'))

    def test_structured_parser_suppresses_references_and_placeholders(self):
        payload = json.dumps({
            'body_text': [
                {'section': 'Results', 'text': 'We use {{formula:abc}} Schur functions.'},
                {'section': 'Bibliography', 'text': 'Schur functions, Journal 2020.'},
            ]
        }).encode()
        rows = structured_paragraphs(payload)
        self.assertEqual('We use   Schur functions.', rows[0].text)
        self.assertIsNone(rows[0].suppressed_reason)
        self.assertEqual('structural-section', rows[1].suppressed_reason)

    def test_pdf_parser_suppresses_contents_and_tail_references(self):
        payload = (
            'Contents\n\n1. Introduction ........ 1\f'
            'A body paragraph about Schur functions.\n\nReferences\n\n[1] A. Author'
        ).encode()
        rows = pdf_paragraphs(payload)
        self.assertEqual('contents', rows[0].suppressed_reason)
        body = next(row for row in rows if row.text.startswith('A body'))
        self.assertIsNone(body.suppressed_reason)
        reference = next(row for row in rows if row.text.startswith('[1]'))
        self.assertEqual('references', reference.suppressed_reason)

    def test_pdf_reference_heading_inside_a_layout_chunk_starts_suppression(self):
        rows = pdf_paragraphs(b'Body text.\n\nReferences\n[1] A. Author')
        self.assertIsNone(rows[0].suppressed_reason)
        self.assertEqual('references', rows[1].suppressed_reason)

    def test_analysis_separates_metadata_and_body_only_evidence(self):
        payload = json.dumps({
            'body_text': [
                {'section': 'Main theorem', 'text': (
                    'Schur positivity follows from affine permutation methods. '
                    'The affine permutation construction gives a second proof.'
                )},
                {'section': 'References', 'text': 'Young tableau Young tableau.'},
            ]
        }).encode()
        phrases = {
            tuple(tokenize('symmetric function')): [{
                'keyword_id': 1,
                'canonical_phrase': 'symmetric function',
                'matched_phrase': 'symmetric function',
            }],
            tuple(tokenize('schur positivity')): [{
                'keyword_id': 2,
                'canonical_phrase': 'schur positivity',
                'matched_phrase': 'schur positivity',
            }],
        }
        artifact = Artifact(
            arxiv_id='2601.12345', versioned_arxiv_id='2601.12345v1',
            corpus_name='unarXive', release_id='test', source_kind='structured-corpus',
            relative_path='text/test.json', size=len(payload), sha256='a' * 64,
            format='structured-json', extraction_status='test', quality_rank=100,
            current_version='2601.12345v1',
        )
        result = analyze_paper(
            paper={
                'id': 7,
                'title': 'Symmetric functions',
                'abstract': 'An abstract.',
                'existing_tags': [{'keyword_id': 1, 'source': 'auto'}],
            },
            artifact=artifact,
            payload=payload,
            phrase_index=phrases,
            known_phrases={'symmetric function', 'schur positivity'},
            excluded_candidates=set(),
            max_ngram=3,
            candidate_min_occurrences=2,
            max_candidate_phrases=10,
        )
        self.assertEqual([1], result['metadata_keyword_ids'])
        self.assertEqual(
            ['schur positivity'],
            [row['canonical_phrase'] for row in result['additional_keyword_candidates']],
        )
        self.assertIn(
            'affine permutation',
            [row['phrase'] for row in result['novel_body_phrase_candidates']],
        )
        self.assertEqual({'structural-section': 1}, result['counts']['suppression_reasons'])
        self.assertEqual('body-full-text', result['additional_keyword_candidates'][0]['provenance'])


if __name__ == '__main__':
    unittest.main()
