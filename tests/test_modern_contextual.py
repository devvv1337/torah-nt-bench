import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModernContextualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.binaries = []
        for name in ('contextual_match', 'contextual_modern_match'):
            binary = cls.directory / name
            subprocess.run(['clang++', '-std=c++17', '-O2', str(ROOT / f'native/{name}.cpp'), '-o', str(binary)], check=True)
            cls.binaries.append(binary)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_only_index_guard_changed(self):
        original = (ROOT / 'native/contextual_match.cpp').read_bytes()
        self.assertEqual(original.count(b'indexed_starts>5000000'), 1)
        self.assertEqual((ROOT / 'native/contextual_modern_match.cpp').read_bytes(),
                         original.replace(b'indexed_starts>5000000', b'indexed_starts>10000000'))

    def test_original_guard_failure_and_complete_modern_index(self):
        path = self.directory / 'large-synthetic.txt'
        path.write_text('1 0\n0 ' + 'A' * 156259 + '\n')
        old = subprocess.run([str(self.binaries[0]), str(path), '8', '32', '0', '4'], capture_output=True, text=True)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn('indexed start resource guard exceeded', old.stderr)
        result = json.loads(subprocess.check_output([str(self.binaries[1]), str(path), '8', '32', '0', '4'], text=True))
        self.assertEqual(result['indexed_source_starts'], 5000032)
        self.assertEqual(result['rule_scores'], [0] * 768)

    def test_same_scores_and_random_inputs_on_a_planted_synthetic_example(self):
        outputs, samples = [], []
        for i, binary in enumerate(self.binaries):
            path = self.directory / f'planted{i}.txt'
            source = 'ABCDEFGHIJKLMNOPQRSTUVABC'
            predicted = ''.join(chr(65 + (ord(x) - 65 + ord(y) - 65) % 24) for x, y in zip(source, source[1:]))
            path.write_text('3 3\n' + ''.join(f'{g} {source}\n' for g in range(3)) +
                            ''.join(f'{g} {predicted[:8]} {predicted[8:16]} {predicted[16:]}\n' for g in range(3)))
            outputs.append(json.loads(subprocess.check_output([str(binary), str(path), '8', '32', '19', '1007'], text=True)))
            samples.append([Path(str(path) + f'.{mode}.{end}.txt').read_bytes()
                            for mode in ('words', 'word_types') for end in ('first', 'last')])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(samples[0], samples[1])
        self.assertEqual(outputs[0]['score'], 24)


if __name__ == '__main__':
    unittest.main()
