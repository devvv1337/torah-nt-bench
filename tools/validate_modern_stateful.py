"""Full FAM-006 vector check using the separate Greek-difference oracle."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biblelab.sources import write_json
from biblelab.modern_local import sha
from biblelab.modern_shared import serialize
from biblelab.modern_stateful import DIRECTORY, PROTOCOL, REPORT, verify_frozen, reconstruct
from biblelab.registry import append
from biblelab.stateful import validate
from tools.validate_shared import read_input, verify_reference, verify_p


def check(root=ROOT):
    spec = verify_frozen(root)
    report = json.loads((root / REPORT).read_text())
    assert report['protocol_sha256'] == sha(root / PROTOCOL)
    assert report['input_sha256'] == spec['input']['input_sha256']
    raw_path = root / report['raw_result_path']
    assert sha(raw_path) == report['raw_result_sha256']
    assert all(report[k] == v for k, v in json.loads(raw_path.read_text()).items())
    units = reconstruct(root)
    assert units == json.loads((root / spec['input']['units_path']).read_text())
    input_path = root / spec['input']['input_path']
    assert input_path.read_text() == serialize(units['left'], units['right'])
    left, right = read_input(input_path)
    ls = 2 * sum(max(0, sum(map(len, u['words'])) - 7) for u in left)
    rs = sum(max(0, sum(map(len, u['words'])) - 7) for u in right)
    assert [report[k] for k in ('left_oriented_starts', 'indexed_source_starts', 'right_starts', 'start_pairs', 'formal_rule_start_pairs')] == [ls, ls*16, rs, ls*rs, ls*rs*384]
    assert report['right_seed_queries'] == 4*rs
    validate(report, left, right)
    folder = root / DIRECTORY
    compiler = shutil.which('clang++')
    binaries = {}
    for name in ('stateful_oracle', 'reference_replay'):
        binary = folder / name
        subprocess.run([compiler, '-std=c++17', '-O3', str(root / f'native/{name}.cpp'), '-o', str(binary)], check=True)
        binaries[name] = binary
    def oracle(path):
        return json.loads(subprocess.check_output([str(binaries['stateful_oracle']), str(path),
            str(spec['minimum_length']), str(spec['maximum_length'])], text=True))
    observed = oracle(input_path)
    for key in ('score', 'rule_scores', 'maximizing_rule_ids', 'compatible_seed_pairs'):
        assert observed[key] == report[key], key
    print('All768observed scores, maxima and seed counts independently checked: score=' + str(observed['score']), flush=True)
    replay = folder / 'seed-replay'
    replay.mkdir(exist_ok=True)
    subprocess.run([str(binaries['reference_replay']), str(input_path), str(replay) + '/',
        str(spec['reference_draws_per_model']), str(spec['seed'])], check=True)
    checked = []
    for label, sample in report['reference_samples'].items():
        path = root / sample['path']
        mode, end = sample['mode'], label.rsplit('_', 1)[1]
        assert sha(path) == sample['sha256'] == sha(replay / f'{mode}.{end}.txt')
        a, b = read_input(path)
        assert a == left
        verify_reference(right, b, mode)
        actual = oracle(path)
        assert actual['score'] == sample['score'] == report['reference_scores'][mode][0 if end == 'first' else -1]
        checked.append(dict(label=label, **actual))
        print(label + ' checked: score=' + str(actual['score']), flush=True)
    assert set(report['reference_scores']) == {'words', 'word_types'}
    assert all(len(s) == spec['reference_draws_per_model'] for s in report['reference_scores'].values())
    verify_p(report, report['references'])
    alert = report['score'] >= spec['candidate_screen']['minimum_length'] and all(
        p['p'] <= spec['candidate_screen']['p_each_model_max'] for p in report['references'].values())
    assert alert == report['numerical_alert']
    if alert:
        manifest = report['alert_rule_manifest']
        assert sha(root / manifest['path']) == manifest['sha256']
        assert json.loads((root / manifest['path']).read_text())['rule_ids'] == observed['maximizing_rule_ids']
    else:
        assert report['alert_rule_manifest'] is None
    result = dict(id='CHECK-EXP-017', report_sha256=sha(root / REPORT), source_files_verified=32,
        all_units_reextracted=True, observed=observed, reference_checks=checked, observed_rule_scores_checked=768,
        reference_scans_independently_reexecuted=4, reference_scans_not_independently_reexecuted=1994,
        declared_seed_reproduces_all_four_saved_inputs=True, seed_replay_is_independent_rng=False,
        pass_status=True, numerical_alert=alert, candidate_retained=False, candidate_review_required=alert,
        verdict='ouverte' if alert else 'rien', independent_scientific_replication=False,
        method='Unchanged separate transformed-Greek absolute-key oracle and disjoint-edge inclusion-exclusion; all768observed scores/seeds and four full reference scans. Python literal witnesses, raw units, reference invariants and both inclusive tails checked.')
    destination = root / 'reports/modern-stateful-exp017-check-v1.json'
    assert not destination.exists(), 'Preserve completed check'
    write_json(destination, result)
    append(root / 'registry/events.jsonl', 'modern_target_checked', dict(id='EXP-017', report=str(destination.relative_to(root)),
        report_sha256=sha(destination), pass_status=True, numerical_alert=alert, verdict=result['verdict']))
    return {k: result[k] for k in ('id', 'pass_status', 'verdict', 'numerical_alert', 'observed_rule_scores_checked', 'reference_scans_independently_reexecuted')}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2), flush=True)
