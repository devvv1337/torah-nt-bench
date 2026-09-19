"""Public-release replay of EXP-014 or EXP-015; no new scientific evaluation."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biblelab.modern_local import source_check, sha
from biblelab.modern_contextual import reconstruct
from biblelab.modern_shared import serialize
from biblelab.sources import write_json
from tools.validate_shared import read_input, verify_reference, verify_p


def replay(experiment):
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text())['files']
    for name, entry in manifest.items():
        assert sha(ROOT / name) == entry['sha256'], name
    choices = {
        'exp014': ('protocol/modern-editions-fam003-recovery-v1.json', 'native/modern_shared_match.cpp'),
        'exp015': ('protocol/modern-editions-fam004-v1.json', 'native/contextual_modern_match.cpp'),
    }
    protocol, native = choices[experiment]
    spec = json.loads((ROOT / protocol).read_text())
    expected = json.loads((ROOT / f'expected/{experiment}/result.json').read_text())
    assert expected['protocol_sha256'] == sha(ROOT / protocol)
    for name, checksum in spec['code_hashes'].items():
        if (ROOT / name).is_file():
            assert sha(ROOT / name) == checksum, name
    # A replay of published fixed results does not register a new experiment.
    sources = source_check(ROOT, fetch=True)
    assert sources == spec['input']['source_hashes']
    folder = ROOT / 'reproduction' / experiment
    assert not folder.exists(), 'Use a fresh extraction; preserve earlier runs.'
    folder.mkdir(parents=True)
    units = reconstruct(ROOT)
    input_path = folder / 'input.txt'
    input_path.write_text(serialize(units['left'], units['right']), encoding='ascii')
    write_json(folder / 'units.json', units)
    assert sha(input_path) == spec['input']['input_sha256']
    assert sha(folder / 'units.json') == spec['input']['units_sha256']
    binary = folder / 'engine'
    compiler = shutil.which('clang++')
    assert compiler, 'C++17 compiler named clang++ required'
    subprocess.run([compiler, '-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic', str(ROOT / native), '-o', str(binary)], check=True)
    raw_path = folder / 'raw-result.json'
    with raw_path.open('w') as output, (folder / 'stderr.txt').open('w') as error:
        subprocess.run([str(binary), str(input_path), str(spec['minimum_length']), str(spec['maximum_length']),
            str(spec['reference_draws_per_model']), str(spec['seed'])], stdout=output, stderr=error, check=True)
    result = json.loads(raw_path.read_text())
    for name, value in result.items():
        assert expected[name] == value, name
    assert sha(raw_path) == expected['raw_result_sha256']
    left, right = read_input(input_path)
    for label, sample in expected['reference_samples'].items():
        mode, end = sample['mode'], label.rsplit('_', 1)[1]
        path = Path(str(input_path) + f'.{mode}.{end}.txt')
        assert sha(path) == sample['sha256']
        a, b = read_input(path)
        assert a == left
        verify_reference(right, b, mode)
    verify_p(result, expected['references'])
    report = dict(experiment=experiment, pass_status=True, raw_result_sha256=sha(raw_path),
        exact_input_and_units_identical=True, all_primary_output_fields_identical=True,
        all_reference_scores_identical=sum(len(s) for s in result['reference_scores'].values()),
        saved_reference_inputs_identical=4, source_files_verified=len(sources),
        independent_scientific_replication=False, independent_search_algorithm_used_in_this_replay=False,
        new_scientific_trials=0, note='End-to-end reproduction with original primary algorithm; alternate-algorithm check supplied separately.')
    write_json(folder / 'reproduction-check.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('experiment', choices=('exp014', 'exp015'))
    replay(parser.parse_args().experiment)
