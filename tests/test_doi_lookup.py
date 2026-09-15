import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import doi_lookup as doi_lookup_module
from doi_lookup import (
    filter_rejected_doi_items,
    get_papers_needing_doi,
    query_crossref,
    score_match,
)
from title_matching import (
    author_coverage_similarity,
    author_last_name,
    author_similarity,
    normalize_author_name,
    normalize_title,
    score_title_author_match,
    summarize_author_list_for_display,
    title_similarity,
)


class NormalizeTests(unittest.TestCase):
    def test_doi_queue_uses_explicit_priority_bands(self):
        cursor = mock.Mock()
        cursor.fetchall.return_value = []

        self.assertEqual([], get_papers_needing_doi(cursor, 250, 180))

        sql, params = cursor.execute.call_args.args
        self.assertIn("TRIM(p.journal_ref) <> '' THEN 0", sql)
        self.assertIn('INTERVAL 730 DAY', sql)
        self.assertIn('ORDER BY queue_priority', sql)
        self.assertIn('p.doi_checked_at ASC', sql)
        self.assertEqual([180, 180, 250], params)

    def test_rejected_doi_candidates_are_not_reconsidered(self):
        items = [
            {'DOI': '10.1000/Rejected'},
            {'DOI': '10.1000/alternative'},
        ]
        self.assertEqual(
            [{'DOI': '10.1000/alternative'}],
            filter_rejected_doi_items(items, {' 10.1000/rejected '}),
        )

    def test_crossref_failure_is_distinct_from_successful_empty_result(self):
        response = mock.Mock()
        response.raise_for_status.side_effect = RuntimeError('429 Too Many Requests')
        with mock.patch.object(doi_lookup_module.requests, 'get',
                               return_value=response), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(query_crossref('A title', 'Author'))

        response.raise_for_status.side_effect = None
        response.json.return_value = {'message': {'items': []}}
        with mock.patch.object(doi_lookup_module.requests, 'get',
                               return_value=response):
            self.assertEqual([], query_crossref('A title', 'Author'))

    def test_failed_crossref_request_leaves_paper_eligible(self):
        cursor = mock.Mock()
        connection = mock.Mock()
        connection.cursor.return_value = cursor
        paper = {
            'id': 7,
            'arxiv_id': '2401.00007v1',
            'title': 'Retry this paper',
            'published_date': '2024-01-02',
        }
        with mock.patch.object(doi_lookup_module.pymysql, 'connect',
                               return_value=connection), \
                mock.patch.object(doi_lookup_module, 'get_papers_needing_doi',
                                  return_value=[paper]), \
                mock.patch.object(doi_lookup_module, 'get_paper_authors',
                                  return_value=['Ada Lovelace']), \
                mock.patch.object(doi_lookup_module, 'query_crossref',
                                  return_value=None), \
                mock.patch.object(doi_lookup_module.time, 'sleep'), \
                contextlib.redirect_stdout(io.StringIO()):
            exit_code = doi_lookup_module.main(['--batch', '1'])

        executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(1, exit_code)
        self.assertFalse(any('doi_checked_at = NOW()' in sql for sql in executed_sql))

    def test_successful_empty_crossref_result_marks_paper_checked(self):
        cursor = mock.Mock()
        connection = mock.Mock()
        connection.cursor.return_value = cursor
        paper = {
            'id': 8,
            'arxiv_id': '2401.00008v1',
            'title': 'No published match yet',
            'published_date': '2024-01-03',
        }
        with mock.patch.object(doi_lookup_module.pymysql, 'connect',
                               return_value=connection), \
                mock.patch.object(doi_lookup_module, 'get_papers_needing_doi',
                                  return_value=[paper]), \
                mock.patch.object(doi_lookup_module, 'get_paper_authors',
                                  return_value=['Ada Lovelace']), \
                mock.patch.object(doi_lookup_module, 'get_rejected_dois',
                                  return_value=set()), \
                mock.patch.object(doi_lookup_module, 'query_crossref',
                                  return_value=[]), \
                mock.patch.object(doi_lookup_module.time, 'sleep'), \
                contextlib.redirect_stdout(io.StringIO()):
            exit_code = doi_lookup_module.main(['--batch', '1'])

        executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(0, exit_code)
        self.assertTrue(any('doi_checked_at = NOW()' in sql for sql in executed_sql))

    def test_tex_math_and_unicode_titles_normalize_together(self):
        tex_title = r"Phase transitions for the minimizers of the $p^{th}$ frame potentials in $\mathbb{R}^2$"
        unicode_title = "Phase Transitions for the Minimizers of the p-Frame Potentials in R^2"
        self.assertEqual(normalize_title(tex_title), normalize_title(unicode_title))

    def test_mathml_and_html_fragments_preserve_inner_text(self):
        html_title = (
            "Counting <math><mi>&lambda;</mi><mo>-</mo><mi>partitions</mi></math> "
            "in <em>Young</em> diagrams"
        )
        plain_title = "Counting lambda partitions in Young diagrams"
        self.assertEqual(normalize_title(html_title), normalize_title(plain_title))

    def test_dash_variants_normalize(self):
        ascii_dash = "e-positivity of chromatic symmetric functions"
        unicode_dash = "e—positivity of chromatic symmetric functions"
        double_dash = "e--positivity of chromatic symmetric functions"
        normalized = normalize_title(ascii_dash)
        self.assertEqual(normalized, normalize_title(unicode_dash))
        self.assertEqual(normalized, normalize_title(double_dash))

    def test_casefold_handles_capitalization(self):
        self.assertEqual(
            normalize_title("Schur Positivity in Macdonald Theory"),
            normalize_title("schur positivity in macdonald theory"),
        )

    def test_british_and_american_spellings_normalize_together(self):
        self.assertEqual(
            normalize_title("coloured graph labelling"),
            normalize_title("colored graph labeling"),
        )

    def test_author_normalization_handles_accents_and_suffixes(self):
        self.assertEqual(
            normalize_author_name("Dvořák-Smith, Jr."),
            normalize_author_name("Dvorak Smith Jr"),
        )
        self.assertEqual("dvorak smith", author_last_name("Dvořák-Smith, Jr."))
        self.assertEqual("ben av", author_last_name("Radel Ben Av"))
        self.assertEqual("cameron", author_last_name("Ben Cameron"))
        self.assertEqual("vu", author_last_name("Van Vu"))
        self.assertEqual("han", author_last_name("Bin Han"))

    def test_author_display_summary_normalizes_name_order(self):
        summary, full_list = summarize_author_list_for_display(
            "Doe, Jane; Ben Av, Radel; Dvořák-Smith, Alice; Jones, Pat"
        )
        self.assertEqual(
            "jane doe, radel ben av, alice dvořák-smith et al.",
            summary,
        )
        self.assertEqual(
            "jane doe, radel ben av, alice dvořák-smith, pat jones",
            full_list,
        )

    def test_title_similarity_treats_spacing_only_differences_as_exact(self):
        self.assertEqual(
            1.0,
            title_similarity("Macdonald polynomial", "MacdonaldPolynomial"),
        )

    def test_exact_titles_allow_compacted_author_surnames(self):
        self.assertEqual(
            1.0,
            score_title_author_match(
                "Total Thue colourings of graphs",
                ["Erika Škrabuláková"],
                "Total Thue colourings of graphs",
                ["Škrabul’áková, Erika"],
            ),
        )

    def test_exact_titles_allow_subset_author_lists_when_two_match(self):
        self.assertEqual(
            1.0,
            score_title_author_match(
                "Connectivity for Kite-Linked Graphs",
                ["Runrun Liu", "Martin Rolek", "D. Christopher Stephens"],
                "Connectivity for Kite-Linked Graphs",
                ["Liu, Runrun", "Rolek, Martin"],
            ),
        )

    def test_author_similarity_handles_reordered_multiword_names(self):
        examples = [
            ("Jesse Campion Loth", "Campion Loth, Jesse"),
            ("Nguyen Thi Thanh Tam", "Thi Thanh Tam, Nguyen"),
            ("Zhai Mingqing", "Zhai, Mingqing"),
        ]
        for arxiv_name, crossref_name in examples:
            with self.subTest(arxiv_name=arxiv_name):
                self.assertEqual(
                    1.0,
                    author_similarity([arxiv_name], [crossref_name]),
                )

    def test_author_similarity_allows_one_added_name_part(self):
        self.assertGreaterEqual(
            author_similarity(
                ["Cetin Hakimoglu-Brown"],
                ["Hakimoglu, Cetin"],
            ),
            2 / 3,
        )

    def test_author_similarity_matches_initials_to_full_given_names(self):
        self.assertEqual(
            1.0,
            author_similarity(["Ahmet Batal"], ["Batal, A."]),
        )

    def test_author_similarity_allows_extra_middle_initials(self):
        self.assertEqual(
            1.0,
            author_similarity(["Anton Ayzenberg"], ["Ayzenberg, A. A."]),
        )
        self.assertEqual(
            1.0,
            author_similarity(["Igor Makhlin"], ["Makhlin, I. Yu."]),
        )

    def test_author_coverage_allows_added_publication_authors(self):
        self.assertGreaterEqual(
            author_coverage_similarity(
                ["Vincent E. Coll", "Nicholas W. Mayers"],
                [
                    "Coll, Vincent",
                    "Mayers, Nicholas W.",
                    "Russoniello, Nicholas",
                ],
            ),
            0.8,
        )

    def test_author_similarity_does_not_equate_shared_surname_only(self):
        self.assertLess(
            author_similarity(["Jane Loth"], ["Jesse Campion Loth"]),
            0.65,
        )

    def test_spacing_only_title_match_needs_one_author_overlap(self):
        self.assertEqual(
            1.0,
            score_title_author_match(
                "Macdonald polynomial positivity",
                ["Jane Doe", "Alex Smith"],
                "MacdonaldPolynomial positivity",
                ["Doe, Jane"],
            ),
        )

    def test_short_published_suffix_boosts_near_substring_match(self):
        self.assertGreaterEqual(
            score_title_author_match(
                "Coloured Graphs",
                ["Jane Doe"],
                "Colored Graphs II",
                ["Doe, Jane"],
            ),
            0.97,
        )

    def test_dropped_published_suffix_boosts_near_substring_match(self):
        self.assertGreaterEqual(
            score_title_author_match(
                "Bounding the multiplicities of eigenvalues of graph matrices "
                "in terms of circuit rank using a new approach",
                ["Ahmet Batal"],
                "Bounding the multiplicities of eigenvalues of graph matrices "
                "in terms of circuit rank",
                ["Batal, A."],
            ),
            0.97,
        )

    def test_old_tex_font_declarations_do_not_pollute_titles(self):
        self.assertEqual(
            1.0,
            title_similarity(
                r"$q{\rm RS}t$: A probabilistic correspondence",
                "qRSt: A probabilistic correspondence",
            ),
        )


class ScoreMatchTests(unittest.TestCase):
    def test_allows_journal_publication_before_later_arxiv_upload(self):
        cr_item = {
            'title': ['Same title'],
            'author': [{'family': 'Doe'}],
            'container-title': ['Journal'],
            'issued': {'date-parts': [[2022, 12, 1]]},
        }
        confidence, _, cr_year = score_match(
            "Same title",
            ["Jane Doe"],
            2022,
            cr_item,
            paper_published_date="2022-12-08",
        )
        self.assertGreater(confidence, 0.9)
        self.assertEqual(2022, cr_year)

    def test_does_not_false_reject_incomplete_crossref_month_precision(self):
        cr_item = {
            'title': ['Same title'],
            'author': [{'family': 'Doe'}],
            'container-title': ['Journal'],
            'issued': {'date-parts': [[2022, 12]]},
        }
        confidence, _, _ = score_match(
            "Same title",
            ["Jane Doe"],
            2022,
            cr_item,
            paper_published_date="2022-12-31",
        )
        self.assertGreater(confidence, 0.0)

    def test_uses_online_date_when_closer_than_print_date(self):
        cr_item = {
            'title': ['Same title'],
            'author': [{'family': 'Doe'}],
            'container-title': ['Journal'],
            'published-print': {'date-parts': [[2024, 5]]},
            'published-online': {'date-parts': [[2023, 3, 7]]},
        }
        confidence, _, cr_year = score_match(
            'Same title',
            ['Jane Doe'],
            2022,
            cr_item,
            paper_published_date='2022-02-01',
        )
        self.assertGreater(confidence, 0.95)
        self.assertEqual(2023, cr_year)

    def test_created_date_does_not_override_publication_date(self):
        cr_item = {
            'title': ['Same title'],
            'author': [{'family': 'Doe'}],
            'container-title': ['Journal'],
            'issued': {'date-parts': [[2024]]},
            'created': {'date-parts': [[2022]]},
        }
        _, _, cr_year = score_match('Same title', ['Jane Doe'], 2022, cr_item)
        self.assertEqual(2024, cr_year)

    def test_uses_earlier_crossref_year_as_proximity_evidence(self):
        cr_item = {
            'title': ['Same title'],
            'author': [{'family': 'Doe'}],
            'container-title': ['Journal'],
            'issued': {'date-parts': [[2021]]},
        }
        confidence, _, _ = score_match(
            "Same title",
            ["Jane Doe"],
            2022,
            cr_item,
            paper_published_date="2022-01-02",
        )
        self.assertGreater(confidence, 0.9)


if __name__ == '__main__':
    unittest.main()
