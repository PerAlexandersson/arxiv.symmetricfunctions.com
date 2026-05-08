import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from doi_lookup import score_match
from title_matching import (
    author_last_name,
    normalize_author_name,
    normalize_title,
    score_title_author_match,
    summarize_author_list_for_display,
    title_similarity,
)


class NormalizeTests(unittest.TestCase):
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


class ScoreMatchTests(unittest.TestCase):
    def test_rejects_crossref_full_date_before_arxiv(self):
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
        self.assertEqual(0.0, confidence)
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

    def test_rejects_crossref_year_before_arxiv_year(self):
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
        self.assertEqual(0.0, confidence)


if __name__ == '__main__':
    unittest.main()
