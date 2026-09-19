"""Prospectively declared resource-only recovery of incomplete EXP-013."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

from .sources import ROOT, write_json
from .modern_local import source_check, sha
from .modern_shared import DIRECTORY as OLD_DIRECTORY
from .registry import append, read_events

DIRECTORY = 'data/derived/modern-shared-recovery-v1'
PROTOCOL = 'protocol/modern-editions-fam003-recovery-v1.json'
REPORT = 'reports/modern-shared-exp014-v1.json'


def verify_frozen(root):
    spec = json.loads((root / PROTOCOL).read_text())
    assert source_check(root) == spec['input']['source_hashes']
    for path, expected in spec['code_hashes'].items():
        assert sha(root / path) == expected, path
    for label in ('input', 'units', 'crosswalk'):
        assert sha(root / spec['input'][label + '_path']) == spec['input'][label + '_sha256']
    for item in spec['existing_diagnostics'].values():
        assert sha(root / item['path']) == item['sha256']
    assert sha(root / spec['failure_report']) == spec['failure_report_sha256']
    old_native = (root / 'native/shared_match.cpp').read_bytes()
    assert old_native.count(b'out.checks>50000000') == 1
    assert (root / 'native/modern_shared_match.cpp').read_bytes() == old_native.replace(b'out.checks>50000000', b'out.checks>1000000000')
    assert (root / spec['input']['input_path']).read_bytes() == (root / OLD_DIRECTORY / 'input.txt').read_bytes()
    return spec


def run(root=ROOT):
    from collections import Counter
    spec = verify_frozen(root)
    events = read_events(root / 'registry/events.jsonl')
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha(root / PROTOCOL) for e in events)
    assert not any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == spec['id'] for e in events)
    assert not (root / REPORT).exists()
    folder = root / DIRECTORY
    compiler = shutil.which('clang++')
    assert compiler
    binary = folder / 'shared_match'
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic']
    subprocess.run([compiler, *flags, str(root / 'native/modern_shared_match.cpp'), '-o', str(binary)], check=True)
    append(root / 'registry/events.jsonl', 'modern_target_started', dict(id=spec['id'], family='FAM-003',
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'],
        new_target_executions=1, cumulative_started=14, recovery_of='EXP-013', new_independent_experiments=0,
        compiler=subprocess.check_output([compiler, '--version'], text=True), flags=flags, binary_sha256=sha(binary)))
    raw_path, error_path = folder / 'raw-result.json', folder / 'stderr.txt'
    print('EXP-014 resource-only recovery started; same399 input corpora and same statistical choices.', flush=True)
    with raw_path.open('w') as output, error_path.open('w') as error:
        process = subprocess.run([str(binary), str(root / spec['input']['input_path']), str(spec['minimum_length']),
            str(spec['maximum_length']), str(spec['reference_draws_per_model']), str(spec['seed'])], stdout=output, stderr=error)
    if process.returncode:
        append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id=spec['id'], exit_code=process.returncode,
            partial_output_sha256=sha(raw_path), stderr_sha256=sha(error_path), verdict='ouverte; execution incomplete'))
        raise RuntimeError('Incomplete recovery; keep all evidence and do not claim a negative')
    raw = json.loads(raw_path.read_text())
    failure = json.loads((root / spec['failure_report']).read_text())
    assert all(raw[k] == v for k, v in failure['completed_observed'].items())
    assert raw['reference_scores']['words'] == failure['completed_words_scores']
    references, samples = {}, {}
    for mode, values in raw['reference_scores'].items():
        assert len(values) == spec['reference_draws_per_model']
        exceeds = sum(v >= raw['score'] for v in values)
        references[mode] = dict(draws=len(values), exceedances=exceeds, p=(1 + exceeds) / (1 + len(values)),
                               histogram=dict(sorted(Counter(values).items())))
        for label, index in [('first', 0), ('last', -1)]:
            p = root / (spec['input']['input_path'] + f'.{mode}.{label}.txt')
            samples[f'{mode}_{label}'] = dict(path=str(p.relative_to(root)), sha256=sha(p), mode=mode, score=values[index])
            old_name = f'input.txt.{mode}.{label}.txt'
            if old_name in failure['saved_reference_hashes']:
                assert sha(p) == failure['saved_reference_hashes'][old_name]
    alert = raw['score'] >= spec['candidate_screen']['minimum_length'] and all(
        r['p'] <= spec['candidate_screen']['p_each_model_max'] for r in references.values())
    report = dict(id=spec['id'], family='FAM-003', completed_utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'], counts=spec['input']['counts'],
        raw_result_path=str(raw_path.relative_to(root)), raw_result_sha256=sha(raw_path),
        **raw, references=references, reference_samples=samples, numerical_alert=alert, candidate_retained=False,
        internal_verification_pending=True, verdict='ouverte' if alert else 'rien', verdict_pending_internal_check=True,
        historical_certification_required_to_compute=False, confirmatory_p=False, independent_scientific_replication=False,
        recovery_of='EXP-013', original_observed_and199_word_scores_identical=True, original3_reference_files_identical=True,
        cumulative_target_executions=14, cumulative_completed_target_executions=13, cumulative_incomplete_target_executions=1,
        scope='Same exposed target and randomization as EXP-013; resource-only recovery, no new independent evidence; bounded FAM-003 on full modern editions.')
    write_json(root / REPORT, report)
    append(root / 'registry/events.jsonl', 'modern_target_completed', dict(id=spec['id'], report=REPORT,
        report_sha256=sha(root / REPORT), score=raw['score'], numerical_alert=alert, cumulative_completed=13,
        cumulative_started=14, recovery_of='EXP-013', new_independent_experiments=0))
    return {k: report[k] for k in ('id', 'score', 'references', 'numerical_alert', 'verdict')}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2), flush=True)
