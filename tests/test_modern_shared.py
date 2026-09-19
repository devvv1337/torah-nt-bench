import unittest
from biblelab.modern_shared import common_deletion, serialize


class ModernSharedTests(unittest.TestCase):
    def test_written_iotas_retained(self):
        for raw in ('ᾠδι', 'ω\u0345δι', 'Ω\u0345δι'):
            item = common_deletion(raw)
            self.assertEqual(item['old'], 'ωιδι')
            self.assertEqual(item['common'], 'ωδι')
            self.assertEqual(item['removed_old_positions'], [1])
            self.assertEqual(item['common_to_old'], [0, 2, 3])
        self.assertEqual(common_deletion('ωιδι')['common'], 'ωιδι')

    def test_raw_offsets_and_final_sigma(self):
        item = common_deletion('τῷς')
        self.assertEqual(item['common'], 'τωσ')
        self.assertEqual(item['common_source_codepoint_offsets'], [0, 1, 2])
        self.assertEqual(item['common_to_old'], [0, 1, 3])

    def test_disappearing_word_errors(self):
        with self.assertRaises(ValueError):
            common_deletion('\u0345')

    def test_distinct_groups_and_word_boundaries(self):
        left = [dict(id='a', group=0, words=['AB', 'CD']), dict(id='b', group=1, words=['EF'])]
        right = [dict(id='z', group=0, words=['X', 'VW'])]
        self.assertEqual(serialize(left, right), '2 1\n0 AB CD\n1 EF\n0 X VW\n')
        left[1]['group'] = 0
        with self.assertRaises(AssertionError):
            serialize(left, right)


if __name__ == '__main__':
    unittest.main()
