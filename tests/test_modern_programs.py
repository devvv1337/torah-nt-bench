import copy
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from biblelab.modern_programs import aggregate
from biblelab.short_programs import predict, validate
from biblelab.shared_search import save_input

ROOT = Path(__file__).resolve().parents[1]


class ModernProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.binaries = {}
        for name in ('short_programs', 'short_programs_batch'):
            path = cls.folder / name
            subprocess.run(['clang++', '-std=c++17', '-O2', str(ROOT / f'native/{name}.cpp'), '-o', str(path)], check=True)
            cls.binaries[name] = path

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compare(self, left, right, minimum=4, cap=10, draws=5):
        partitions = [(0, 7), (7, 47), (47, 195), (195, 292)]
        def execute(name, index, extra):
            path = self.folder / f'input-{index}.txt'
            save_input(path, left, right)
            result = json.loads(subprocess.check_output([str(self.binaries[name]), str(path), str(minimum), str(cap), str(draws), '167', *map(str, extra)], text=True))
            samples = [Path(str(path) + f'.{mode}.{end}.txt').read_bytes()
                       for mode in ('words', 'word_types') for end in ('first', 'last')]
            return result, samples
        original, expected_samples = execute('short_programs', 'whole', [])
        parts = []
        for i, limits in enumerate(partitions):
            result, samples = execute('short_programs_batch', i, limits)
            self.assertEqual(samples, expected_samples)
            parts.append(result)
        merged = aggregate(parts)
        for key, value in original.items():
            self.assertEqual(merged[key], value, key)
        validate(merged, left, right)
        return parts, merged

    def test_catalog_is_unchanged_for_all7008_codes(self):
        catalogs = [json.loads(subprocess.check_output([str(b), '--catalog'], text=True)) for b in self.binaries.values()]
        self.assertEqual(catalogs[0], catalogs[1])
        self.assertEqual(len(catalogs[0]), 7008)

    def test_partition_across_opcodes_preserves_scores_witnesses_and_references(self):
        rng = random.Random(181)
        for rule in (455, 3125, 5303, 7007):
            left = [dict(group=i, words=[''.join(chr(65+rng.randrange(22)) for _ in range(15))]) for i in range(4)]
            direction = -1 if rule in (455, 3125, 7007) else 1
            right = [dict(group=i, words=[predict(u['words'][0][::direction], rule)]) for i, u in enumerate(left)]
            _, result = self.compare(left, right)
            self.assertEqual(result['rule_scores'][rule], 10)

    def test_all_constant_ties_and_zero_group_scores_are_preserved(self):
        left = [dict(group=i, words=['A'*34]) for i in range(3)]
        right = [dict(group=i, words=['A'*8]*4) for i in range(3)]
        parts, result = self.compare(left, right, 8, 32, 2)
        self.assertEqual(result['maximizing_rule_ids'], list(range(0, 7008, 24)))
        self.assertEqual(result['compatible_seed_pairs'], 1672200)
        for u in left:
            u['group'] = 0
        _, result = self.compare(left, right, 8, 32, 2)
        self.assertEqual(result['score'], 0)
        with self.assertRaises(AssertionError):
            aggregate(parts, seed_limit=1)

    def test_missing_duplicate_or_out_of_partition_scores_are_rejected(self):
        left = [dict(group=i, words=['ABCDEFGHIJKL']) for i in range(3)]
        right = [dict(group=i, words=['BCDEFGHIJKL']) for i in range(3)]
        parts, _ = self.compare(left, right)
        for invalid in (parts[1:], parts[:-1], parts + [parts[0]]):
            with self.assertRaises(AssertionError):
                aggregate(invalid)
        invalid = copy.deepcopy(parts)
        invalid[0]['rule_scores'][1000] = 8
        with self.assertRaises(AssertionError):
            aggregate(invalid)

    def test_invalid_or_empty_base_interval_fails(self):
        path = self.folder / 'empty.txt'
        path.write_text('0 0\n')
        for begin, end in [(-1, 5), (3, 3), (2, 293)]:
            result = subprocess.run([str(self.binaries['short_programs_batch']), str(path), '8', '32', '0', '1', str(begin), str(end)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
