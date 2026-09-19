"""EXP-016: full literal oracle, batch completeness and paired reference checks."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biblelab.sources import write_json
from biblelab.modern_local import sha
from biblelab.modern_contextual import reconstruct
from biblelab.modern_shared import serialize
from biblelab.modern_programs import PROTOCOL, REPORT, DIRECTORY, verify_frozen, aggregate, KINDS
from biblelab.short_programs import validate
from biblelab.registry import append
from tools.validate_shared import read_input, verify_reference, verify_p


def check(root=ROOT):
    spec = verify_frozen(root)
    report = json.loads((root / REPORT).read_text())
    assert report['protocol_sha256'] == sha(root / PROTOCOL)
    assert report['input_sha256'] == spec['input']['input_sha256']
    input_path = root / spec['input']['input_path']
    units = reconstruct(root)
    assert units == json.loads((root / spec['input']['units_path']).read_text())
    assert input_path.read_text() == serialize(units['left'], units['right'])
    left, right = read_input(input_path)
    parts = []
    endpoint_files = 0
    for receipt in report['batch_receipts']:
        batch = receipt['batch']
        assert batch == spec['input']['batches'][batch['index']]
        saved = root / DIRECTORY / f'batch-{batch["index"]:02d}.receipt.json'
        assert json.loads(saved.read_text()) == receipt and receipt['return_code'] == 0
        path = root / receipt['input_path']
        assert sha(path) == receipt['input_sha256'] == sha(input_path)
        assert sha(root / receipt['raw_path']) == receipt['raw_sha256']
        assert sha(path.parent / 'stderr.txt') == receipt['stderr_sha256']
        part = json.loads((root / receipt['raw_path']).read_text())
        assert (part['base_begin'], part['base_end']) == (batch['begin'], batch['end'])
        assert part['indexed_source_starts'] == batch['indexed_starts']
        parts.append(part)
        for label, sample in report['reference_samples'].items():
            mode, end = sample['mode'], label.rsplit('_', 1)[1]
            assert sha(Path(str(path) + f'.{mode}.{end}.txt')) == sample['sha256']
            endpoint_files += 1
    merged = aggregate(parts)
    assert all(report[k] == v for k, v in merged.items())
    validate(report, left, right)
    ls = {span: 2*sum(max(0, sum(map(len, u['words']))-8-span+2) for u in left) for span in (2, 3)}
    rs = sum(max(0, sum(map(len, u['words']))-7) for u in right)
    counts = dict(pair=ls[2]*16, triple=ls[3]*80, product=ls[2]*50)
    assert report['left_oriented_starts_by_span'] == {str(k): v for k, v in ls.items()}
    assert report['indexed_starts_by_kind'] == counts
    assert report['indexed_source_starts'] == sum(counts.values()) == 74410992
    assert report['right_starts'] == rs
    assert report['formal_program_start_pairs'] == sum(counts.values())*rs*24
    baseline = json.loads((root / spec['nested_baseline']['path']).read_text())
    assert sha(root / spec['nested_baseline']['path']) == spec['nested_baseline']['sha256']
    assert report['rule_scores'][:768] == baseline['rule_scores']
    folder = root / DIRECTORY
    compiler = shutil.which('clang++')
    binaries = {}
    for name in ('short_programs_oracle', 'reference_replay'):
        binary = folder / name
        subprocess.run([compiler, '-std=c++17', '-O3', str(root / f'native/{name}.cpp'), '-o', str(binary)], check=True)
        binaries[name] = binary
    def oracle(path):
        return json.loads(subprocess.check_output([str(binaries['short_programs_oracle']), str(path),
            str(spec['minimum_length']), str(spec['maximum_length'])], text=True))
    observed = oracle(input_path)
    for key in ('score', 'rule_scores', 'maximizing_rule_ids', 'compatible_seed_pairs', 'opcode_maxima'):
        assert observed[key] == report[key], key
    print('All 7008 observed scores and seed counts agree with the literal oracle.', flush=True)
    replay = folder / 'seed-replay'
    replay.mkdir(exist_ok=True)
    subprocess.run([str(binaries['reference_replay']), str(input_path), str(replay)+'/',
        str(spec['reference_draws_per_model']), str(spec['seed'])], check=True)
    references = []
    for label, sample in report['reference_samples'].items():
        path = root / sample['path']
        mode, end = sample['mode'], label.rsplit('_', 1)[1]
        index = 0 if end == 'first' else -1
        assert sha(path) == sample['sha256'] == sha(replay / f'{mode}.{end}.txt')
        a, b = read_input(path)
        assert a == left
        verify_reference(right, b, mode)
        result = oracle(path)
        assert result['score'] == sample['score'] == report['reference_scores'][mode][index]
        assert result['opcode_maxima'] == sample['opcode_maxima'] == {k: report['reference_opcode_maxima'][mode][k][index] for k in KINDS}
        assert result['compatible_seed_pairs'] == report['reference_seed_pairs'][mode][index]
        references.append(dict(label=label, **result))
        print(label + ' independently checked: score=' + str(result['score']), flush=True)
    assert all(len(v) == spec['reference_draws_per_model'] for v in report['reference_scores'].values())
    verify_p(report, report['references'])
    alert = report['score'] >= spec['candidate_screen']['minimum_length'] and all(
        p['p'] <= spec['candidate_screen']['p_each_model_max'] for p in report['references'].values())
    assert alert == report['numerical_alert']
    if alert:
        entry = report['alert_rule_manifest']
        assert sha(root / entry['path']) == entry['sha256']
        assert json.loads((root / entry['path']).read_text())['observed']['maximizing_rule_ids'] == observed['maximizing_rule_ids']
    else:
        assert report['alert_rule_manifest'] is None
    result = dict(id='CHECK-EXP-016', report_sha256=sha(root / REPORT), source_files_verified=32,
        all_units_reextracted=True, complete_nonoverlapping_base_partition=True, batch_endpoint_files_checked=endpoint_files,
        observed=observed, observed_rule_scores_checked=7008, nested768_scores_identical_to_exp015=True,
        reference_checks=references, reference_scans_independently_reexecuted=4, reference_scans_not_independently_reexecuted=1994,
        declared_seed_reproduces_all_saved_endpoints=True, intermediate_references_share_frozen_generation_by_construction=True,
        seed_replay_is_independent_rng=False, pass_status=True, numerical_alert=alert, candidate_retained=False,
        candidate_review_required=alert, verdict='ouverte' if alert else 'rien', independent_scientific_replication=False,
        method='Separate absolute-program oracle for all observed scores and four full references. Raw units, literal witnesses, exact batch partition, max aggregation, seed-pair sums, all saved tails and forty endpoint files checked; remaining1994reference scans not independently repeated.')
    destination = root / 'reports/modern-programs-exp016-check-v1.json'
    assert not destination.exists(), 'Preserve completed check'
    write_json(destination, result)
    append(root / 'registry/events.jsonl', 'modern_target_checked', dict(id='EXP-016', report=str(destination.relative_to(root)),
        report_sha256=sha(destination), pass_status=True, numerical_alert=alert, verdict=result['verdict']))
    return {k: result[k] for k in ('id', 'pass_status', 'verdict', 'numerical_alert', 'observed_rule_scores_checked')}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2), flush=True)
