import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def test_only_resource_constant_changes(self):
        old = (ROOT / 'native/shared_match.cpp').read_bytes()
        self.assertEqual(old.count(b'out.checks>50000000'), 1)
        self.assertEqual((ROOT / 'native/modern_shared_match.cpp').read_bytes(),
                         old.replace(b'out.checks>50000000', b'out.checks>1000000000'))

    def test_complete_synthetic_outputs_and_reference_inputs_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            paths = []
            for name in ('shared_match', 'modern_shared_match'):
                binary = directory / name
                subprocess.run(['clang++', '-std=c++17', '-O2', str(ROOT / f'native/{name}.cpp'), '-o', str(binary)], check=True)
                paths.append(binary)
            for words in [('IJKLMNOP', 'IJKLMNOP', 'IJKLMNOP'), ('IJKLMNOP', 'IJKLMNPQ', 'IJKLMNOP')]:
                outputs, samples = [], []
                for i, binary in enumerate(paths):
                    path = directory / f'input{i}.txt'
                    path.write_text('3 3\n0 ABCD EFGH\n1 ABCD EFGH\n2 ABCD EFGH\n' +
                                    '\n'.join(f'{g} {w[:4]} {w[4:]}' for g, w in enumerate(words)) + '\n')
                    outputs.append(json.loads(subprocess.check_output([str(binary), str(path), '8', '8', '19', '214'])) )
                    samples.append([Path(str(path) + f'.{mode}.{end}.txt').read_bytes()
                                    for mode in ('words', 'word_types') for end in ('first', 'last')])
                self.assertEqual(outputs[0], outputs[1])
                self.assertEqual(samples[0], samples[1])
                self.assertEqual(outputs[0]['score'], 8 if words[0] == words[1] else 0)


if __name__ == '__main__':
    unittest.main()
