"""Public reproduction of fixed EXP-016/017 results; no new scientific trial."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biblelab.modern_local import sha, source_check
from biblelab.modern_contextual import reconstruct
from biblelab.modern_shared import serialize
from biblelab.modern_programs import aggregate
from biblelab.sources import write_json
from tools.validate_shared import read_input, verify_reference, verify_p


def replay(experiment):
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text())['files']
    for path, entry in manifest.items():
        assert sha(ROOT / path) == entry['sha256'], path
    fam = '005' if experiment == 'exp016' else '006'
    protocol = ROOT / f'protocol/modern-editions-fam{fam}-v1.json'
    spec = json.loads(protocol.read_text())
    expected = json.loads((ROOT / f'expected/{experiment}/result.json').read_text())
    assert expected['protocol_sha256'] == sha(protocol)
    for path, checksum in spec['code_hashes'].items():
        if (ROOT / path).is_file():
            assert sha(ROOT / path) == checksum, path
    assert source_check(ROOT, fetch=True) == spec['input']['source_hashes']
    folder = ROOT / 'reproduction' / experiment
    assert not folder.exists(), 'Use a fresh extraction; preserve all earlier runs.'
    folder.mkdir(parents=True)
    units = reconstruct(ROOT)
    path = folder / 'input.txt'
    path.write_text(serialize(units['left'], units['right']), encoding='ascii')
    write_json(folder / 'units.json', units)
    assert sha(path) == spec['input']['input_sha256']
    assert sha(folder / 'units.json') == spec['input']['units_sha256']
    compiler = shutil.which('clang++')
    assert compiler, 'C++17 compiler named clang++ required'
    name = 'short_programs_batch' if experiment == 'exp016' else 'stateful_modern_match'
    binary = folder / 'engine'
    subprocess.run([compiler, '-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic', str(ROOT / f'native/{name}.cpp'), '-o', str(binary)], check=True)
    base_args = [str(spec['minimum_length']), str(spec['maximum_length']), str(spec['reference_draws_per_model']), str(spec['seed'])]
    def execute(batch):
        directory = folder / f'batch-{batch["index"]:02d}'
        directory.mkdir()
        entry = directory / 'input.txt'
        entry.write_bytes(path.read_bytes())
        raw = directory / 'raw-result.json'
        with raw.open('w') as out, (directory / 'stderr.txt').open('w') as error:
            subprocess.run([str(binary), str(entry), *base_args, str(batch['begin']), str(batch['end'])], stdout=out, stderr=error, check=True)
        receipt = next(r for r in expected['batch_receipts'] if r['batch']['index'] == batch['index'])
        assert sha(raw) == receipt['raw_sha256']
        for label, sample in expected['reference_samples'].items():
            mode, end = sample['mode'], label.rsplit('_', 1)[1]
            assert sha(Path(str(entry)+f'.{mode}.{end}.txt')) == sample['sha256']
        print('Reproduced exact batch ' + str(batch['index']), flush=True)
        return json.loads(raw.read_text())
    if experiment == 'exp016':
        with ThreadPoolExecutor(max_workers=2) as pool:
            parts = list(pool.map(execute, spec['input']['batches']))
        result = aggregate(parts)
        reference_path = folder / 'batch-00/input.txt'
        raw_checks = 10
    else:
        raw = folder / 'raw-result.json'
        with raw.open('w') as out, (folder / 'stderr.txt').open('w') as error:
            subprocess.run([str(binary), str(path), *base_args], stdout=out, stderr=error, check=True)
        assert sha(raw) == expected['raw_result_sha256']
        result = json.loads(raw.read_text())
        reference_path = path
        raw_checks = 1
    for key, value in result.items():
        assert expected[key] == value, key
    left, right = read_input(path)
    for label, sample in expected['reference_samples'].items():
        mode, end = sample['mode'], label.rsplit('_', 1)[1]
        entry = Path(str(reference_path)+f'.{mode}.{end}.txt')
        assert sha(entry) == sample['sha256']
        a, b = read_input(entry)
        assert a == left
        verify_reference(right, b, mode)
    verify_p(result, expected['references'])
    report = dict(experiment=experiment, pass_status=True, raw_output_files_byte_identical=raw_checks,
        exact_input_and_units_identical=True, all_primary_output_fields_identical=True,
        all_reference_scores_identical=sum(len(s) for s in result['reference_scores'].values()),
        saved_reference_files_identical=40 if experiment == 'exp016' else 4, source_files_verified=32,
        independent_scientific_replication=False, independent_search_algorithm_used_in_this_replay=False,
        new_scientific_trials=0, note='Clean primary reproduction of already reported frozen results; separate internal algorithm checks supplied as expected/check.json.')
    write_json(folder / 'reproduction-check.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('experiment', choices=('exp016', 'exp017'))
    replay(parser.parse_args().experiment)
