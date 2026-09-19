import unittest

from biblelab.modern_local import all_matches, independent_letters


class ModernLocalTests(unittest.TestCase):
    def test_verse_boundaries_cannot_form_match(self):
        self.assertEqual(all_matches([{'encoded': 'AB'}, {'encoded': 'CD'}],
                                     [{'encoded_words': ['WXYZ']}], 4), set())

    def test_reverse_coordinates_and_injective_pattern(self):
        hits = all_matches([{'encoded': 'ABBAC'}], [{'encoded_words': ['CD', 'EED']}], 5)
        self.assertEqual(hits, {(0, -1, 0, 5, 0, 0, 5)})
        self.assertEqual(all_matches([{'encoded': 'ABBA'}], [{'encoded_words': ['CDED']}], 4), set())

    def test_original_fam002_iota_and_final_forms(self):
        self.assertEqual(independent_letters('τῷ λόγῳ', 'grc'), 'τωιλογωι')
        self.assertEqual(independent_letters('מֶלֶךְ', 'he'), 'מלכ')


if __name__ == '__main__':
    unittest.main()
