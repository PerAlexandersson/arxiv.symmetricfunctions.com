"""Author identity, proportional penalties and competing-DOI regressions."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from doi_lookup import rank_crossref_matches, score_match
from title_matching import author_changes, title_similarity, score_title_author_match


def item(doi='10.1234/a', title='A title', names=None):
    return {'DOI': doi, 'title': [title], 'container-title': ['Journal'],
            'issued': {'date-parts': [[2026]]},
            'author': [{'given': given, 'family': family}
                       for given, family in (names or [('Jane', 'Doe')])]}


class AuthorPolicyTests(unittest.TestCase):
    def test_v_initial_is_not_a_generational_suffix(self):
        self.assertEqual(author_changes(['Vojtěch Rödl'], ['Rödl, V.'])['matched'], 1)
        self.assertEqual(author_changes(['V. Voronov'], ['Voronov, V. A.'])['penalty'], 0)

    def test_variants_and_incomplete_names_do_not_get_contradiction_deduction(self):
        for left, right in [('Gerhard Roehrle', 'Röhrle, Gerhard'),
                            ('Emily Leven', 'Sergel Leven, Emily'),
                            ('Renhong Wang', 'Wang, Ren-Hong'),
                            ('Jane Doe', 'Doe'),
                            ('Harry Richman', 'Richman, David Harry')]:
            with self.subTest(left=left, right=right):
                change = author_changes([left], [right])
                self.assertEqual(change['contradictions'], 0)
                self.assertEqual(change['contradiction_penalty'], 0)
                self.assertEqual(change['uncertain'], 1)
                self.assertEqual(change['matched'], 0)
                self.assertTrue(change['conflicting'])  # Still requires manual review.

    def test_one_missing_initial_cannot_hide_a_different_coauthor(self):
        change = author_changes(['Jane Doe', 'Alice Grey'], ['Doe', 'Bob Black'])
        self.assertEqual(change['uncertain'], 1)
        self.assertEqual(change['contradictions'], 1)
        self.assertAlmostEqual(change['contradiction_penalty'], .5)
        self.assertEqual(author_changes(['J. Doe'], ['A. Grey'])['contradictions'], 1)

    def test_clear_replacement_cannot_remain_in_likely_match_band(self):
        names = ['Jane Doe', 'Bob Brown', 'Sela Fried', 'Alex Green', 'Iris White']
        self.assertAlmostEqual(score_title_author_match('Same title', names, 'Same title',
                                                       names[:-1] + ['Ted Black']), .43)
        self.assertAlmostEqual(score_title_author_match('Same title', ['Jane Doe'],
                                                       'Same title', ['Bob Brown']), .15)

    def test_full_names_initials_accents_order_and_compound_surnames(self):
        left = ['Sela Fried', 'Jesse Campion Loth', 'Erika Škrabuláková']
        right = ['Škrabul’áková, E.', 'Fried, S.', 'Campion Loth, Jesse']
        change = author_changes(left, right)
        self.assertEqual(change['matched'], 3)
        self.assertEqual(change['penalty'], 0)
        self.assertEqual(score_title_author_match('A title', left, 'A title', right), 1)

    def test_different_full_given_names_are_not_equated_by_first_letter(self):
        self.assertTrue(author_changes(['Jane Doe'], ['John Doe'])['conflicting'])
        self.assertEqual(author_changes(['Jane Doe'], ['J. Doe'])['penalty'], 0)
        self.assertGreater(author_changes(['Jane Doe'], ['Doe'])['penalty'], 0)
        self.assertEqual(author_changes(['Jane Doe'], ['Jane Smith'])['matched'], 0)

    def test_matching_is_one_to_one_and_handles_ambiguous_initials(self):
        self.assertEqual(author_changes(['John Smith', 'Jane Smith'],
                                        ['J. Smith', 'John Smith'])['matched'], 2)
        changed = author_changes(['John Smith', 'Jane Smith'], ['J. Smith'])
        self.assertEqual(changed['matched'], 1)
        self.assertEqual(changed['missing'], 1)
        self.assertAlmostEqual(changed['penalty'], .10)

    def test_five_to_four_six_and_replacement(self):
        names = ['Jane Doe', 'Bob Brown', 'Sela Fried', 'Alex Green', 'Iris White']
        self.assertAlmostEqual(author_changes(names, names[:-1])['penalty'], .04)
        self.assertAlmostEqual(author_changes(names, names + ['Ted Black'])['penalty'], .03)
        replacement = author_changes(names, names[:-1] + ['Ted Black'])
        self.assertAlmostEqual(replacement['change_penalty'], .07)
        self.assertTrue(replacement['conflicting'])
        self.assertAlmostEqual(replacement['penalty'], .57)
        full = item(names=[tuple(name.split()) for name in names])
        added = item(names=[tuple(name.split()) for name in names + ['Ted Black']])
        removed = item(names=[tuple(name.split()) for name in names[:-1]])
        self.assertEqual(score_match('A title', names, 2022, full)[0], 1)
        self.assertEqual(score_match('A title', names, 2022, added)[0], .97)
        self.assertEqual(score_match('A title', names, 2022, removed)[0], .96)

    def test_exact_title_does_not_erase_wrong_coauthor(self):
        score = score_title_author_match('Same title', ['Jane Doe', 'Alex Smith'],
                                         'Same title', ['Jane Doe', 'Bob Brown'])
        self.assertAlmostEqual(score, .325)
        rank = rank_crossref_matches('Same title', ['Jane Doe', 'Alex Smith'], 2022,
                                    [item(title='Same title', names=[('Jane', 'Doe'), ('Bob', 'Brown')])])
        self.assertFalse(rank[0]['auto_eligible'])

    def test_missing_author_lists_are_not_perfect_or_auto_eligible(self):
        self.assertGreater(author_changes([], [])['penalty'], 0)
        record = item()
        record['author'] = []
        self.assertFalse(rank_crossref_matches('A title', ['Jane Doe'], 2022, [record])[0]['auto_eligible'])

    def test_real_hypercube_title_collision_keeps_wrong_coauthor_for_review(self):
        # arXiv 2501.19029 and 2401.01769 share a title, not their second author.
        title = 'Matchings in hypercubes extend to long cycles'
        publication = item('10.1137/24M1670093', title,
                           [('Jiří', 'Fink'), ('Torsten', 'Mütze')])
        wrong = rank_crossref_matches(title, ['Jiří Fink', 'Vojtěch Hotmar'],
                                      2025, [publication])[0]
        right = rank_crossref_matches(title, ['Jiří Fink', 'Torsten Mütze'],
                                      2024, [publication])[0]
        self.assertEqual(wrong['score'], .325)
        self.assertFalse(wrong['auto_eligible'])
        self.assertEqual(right['score'], 1)
        self.assertTrue(right['auto_eligible'])


class TitlePolicyTests(unittest.TestCase):
    def test_one_and_five_word_changes_out_of_ten(self):
        original = 'one two three four five six seven eight nine ten'
        self.assertAlmostEqual(title_similarity(original, 'one two three four five six seven eight nine other'), .9)
        self.assertAlmostEqual(title_similarity(original, 'alpha beta gamma delta epsilon six seven eight nine ten'), .5)
        self.assertAlmostEqual(title_similarity(original, 'one two three four five six seven eight nine'), .9)
        self.assertAlmostEqual(title_similarity(original, original + ' extra'), 10 / 11)

    def test_repetitions_and_part_numbers_are_not_lost_in_sets(self):
        self.assertAlmostEqual(title_similarity('on graphs graphs', 'on graphs'), 2 / 3)
        self.assertAlmostEqual(title_similarity('Colored graphs I', 'Colored graphs II'), 2 / 3)
        self.assertEqual(title_similarity('', ''), 0)


class RunnerUpPolicyTests(unittest.TestCase):
    def test_tie_discount_and_duplicate_doi_deduplication(self):
        ranked = rank_crossref_matches('A title', ['Jane Doe'], 2022, [item(), item('10.1234/b')])
        self.assertEqual(ranked[0]['raw_score'], 1)
        self.assertEqual(ranked[0]['score'], .92)
        self.assertFalse(ranked[0]['auto_eligible'])
        self.assertEqual(ranked[0]['runner_up_doi'], '10.1234/b')
        duplicate = rank_crossref_matches('A title', ['Jane Doe'], 2022, [item(), item(' 10.1234/A ')])
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0]['score'], 1)
        self.assertTrue(duplicate[0]['auto_eligible'])

    def test_gap_threshold_linear_discount_and_weak_rival(self):
        for first, second, expected, eligible in [(.96, .94, .912, False),
                                                 (1, .95, 1, True),
                                                 (1, .94, 1, True),
                                                 (.83, .79, .83, True)]:
            with self.subTest(first=first, second=second):
                with mock.patch('doi_lookup.score_match', side_effect=[(first, 'A title', 2026),
                                                                       (second, 'A title', 2026)]):
                    ranked = rank_crossref_matches('A title', ['Jane Doe'], 2022,
                                                   [item(), item('10.1234/b')])
                self.assertEqual(ranked[0]['score'], expected)
                self.assertEqual(ranked[0]['auto_eligible'], eligible)
                self.assertEqual(ranked[0]['doi'], '10.1234/a')

    def test_unrelated_authors_do_not_make_a_plausible_rival(self):
        ranked = rank_crossref_matches('A title', ['Jane Doe'], 2022,
                                       [item(), item('10.1234/b', names=[('Bob', 'Brown')])])
        self.assertEqual(ranked[0]['score'], 1)
        self.assertTrue(ranked[0]['auto_eligible'])


if __name__ == '__main__':
    unittest.main()
