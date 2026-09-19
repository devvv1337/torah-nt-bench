"""EXP-017: frozen FAM-006 on all modern verses, no manuscript prerequisite."""
import argparse
import fcntl
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from .sources import ROOT, TORAH, NT, write_json
from .editions import OSIS
from .modern_local import sha, source_check, encode, independent_letters
from .modern_shared import common_deletion, serialize
from .registry import append, read_events
from .modern_contextual import reconstruct

DIRECTORY = 'data/derived/modern-stateful-v1'
PROTOCOL = 'protocol/modern-editions-fam006-v1.json'
REPORT = 'reports/modern-stateful-exp017-v1.json'


def prepare(root=ROOT):
    sources = source_check(root)
    units = reconstruct(root)
    prior = json.loads((root / 'data/derived/modern-shared-v1/preparation.json').read_text())
    for key in ('input', 'units', 'crosswalk'):
        assert sha(root / prior[key + '_path']) == prior[key + '_sha256']
    assert units == json.loads((root / prior['units_path']).read_text())
    text = serialize(units['left'], units['right'])
    assert text == (root / prior['input_path']).read_text()
    folder = root / DIRECTORY
    folder.mkdir(parents=True, exist_ok=True)
    assert not (folder / 'input.txt').exists(), 'Preserve previous preparation'
    (folder / 'input.txt').write_text(text, encoding='ascii')
    write_json(folder / 'units.json', units)
    indexed = 32 * sum(max(0, sum(map(len, u['words'])) - 7) for u in units['left'])
    assert indexed == 8444256 and indexed <= 10000000
    receipt = dict(source_hashes=sources, counts={k: prior['counts'][k] for k in
        ('left_units', 'right_units', 'left_groups', 'right_groups', 'left_letters', 'right_letters')},
        all_verses_reextracted_from_raw_xml=True, no_dss_files_read=True, normalization=prior['normalization'],
        boundaries=prior['boundaries'], source_indexed_starts=indexed,
        previous_input_sha256=prior['input_sha256'], previous_crosswalk_path=prior['crosswalk_path'],
        previous_crosswalk_sha256=prior['crosswalk_sha256'])
    for key in ('input', 'units'):
        path = folder / (key + ('.txt' if key == 'input' else '.json'))
        receipt[key + '_path'] = str(path.relative_to(root))
        receipt[key + '_sha256'] = sha(path)
    write_json(folder / 'preparation.json', receipt)
    return {k: v for k, v in receipt.items() if k != 'source_hashes'}


def verify_frozen(root):
    spec = json.loads((root / PROTOCOL).read_text())
    assert source_check(root) == spec['input']['source_hashes']
    for path, expected in spec['code_hashes'].items():
        assert sha(root / path) == expected, path
    for key in ('input', 'units'):
        assert sha(root / spec['input'][key + '_path']) == spec['input'][key + '_sha256']
    for item in spec['existing_diagnostics'].values():
        assert sha(root / item['path']) == item['sha256']
    original = (root / 'native/stateful_match.cpp').read_bytes()
    assert original.count(b'left_starts*16>5000000') == 1
    assert (root / 'native/stateful_modern_match.cpp').read_bytes() == original.replace(b'left_starts*16>5000000', b'left_starts*16>10000000')
    return spec


def run(root=ROOT):
    with (root / 'tmp/modern-stateful-exp017.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            return _run(root)
        except Exception as exc:
            events = read_events(root / 'registry/events.jsonl')
            started = any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == 'EXP-017' for e in events)
            ended = any(e['kind'] in ('modern_target_failed', 'modern_target_completed') and e['payload'].get('id') == 'EXP-017' for e in events)
            if started and not ended:
                append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id='EXP-017', error=repr(exc),
                    verdict='ouverte; incomplete execution or postprocessing', outputs_preserved=True))
            raise


def _run(root):
    previous = json.loads((root / 'reports/modern-programs-exp016-check-v1.json').read_text())
    assert previous['pass_status'] and previous['verdict'] == 'rien'
    spec = verify_frozen(root)
    events = read_events(root / 'registry/events.jsonl')
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha(root / PROTOCOL) for e in events)
    assert not any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == spec['id'] for e in events)
    assert not (root / REPORT).exists()
    compiler = shutil.which('clang++')
    assert compiler
    folder = root / DIRECTORY
    binary = folder / 'stateful_match'
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic']
    subprocess.run([compiler, *flags, str(root / 'native/stateful_modern_match.cpp'), '-o', str(binary)], check=True)
    append(root / 'registry/events.jsonl', 'modern_target_started', dict(id=spec['id'], family='FAM-006',
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'],
        new_target_executions=1, cumulative_started=17, compiler=subprocess.check_output([compiler, '--version'], text=True),
        flags=flags, binary_sha256=sha(binary)))
    raw_path, error_path = folder / 'raw-result.json', folder / 'stderr.txt'
    print('EXP-017 started: unchanged768rules, full modern editions,999references per model.', flush=True)
    with raw_path.open('w') as output, error_path.open('w') as error:
        process = subprocess.run([str(binary), str(root / spec['input']['input_path']), str(spec['minimum_length']),
            str(spec['maximum_length']), str(spec['reference_draws_per_model']), str(spec['seed'])], stdout=output, stderr=error)
    if process.returncode:
        append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id=spec['id'], exit_code=process.returncode,
            partial_output_sha256=sha(raw_path), stderr_sha256=sha(error_path), verdict='ouverte; execution incomplete'))
        raise RuntimeError('Incomplete execution preserved; no truncated negative or automatic retry')
    result = json.loads(raw_path.read_text())
    references, samples = {}, {}
    for mode, scores in result['reference_scores'].items():
        assert len(scores) == spec['reference_draws_per_model']
        exceeds = sum(v >= result['score'] for v in scores)
        references[mode] = dict(draws=len(scores), exceedances=exceeds, p=(1 + exceeds) / (1 + len(scores)),
                               histogram=dict(sorted(Counter(scores).items())))
        for end, index in [('first', 0), ('last', -1)]:
            path = root / (spec['input']['input_path'] + f'.{mode}.{end}.txt')
            samples[f'{mode}_{end}'] = dict(path=str(path.relative_to(root)), sha256=sha(path), mode=mode, score=scores[index])
    alert = result['score'] >= spec['candidate_screen']['minimum_length'] and all(
        r['p'] <= spec['candidate_screen']['p_each_model_max'] for r in references.values())
    manifest = None
    if alert:
        path = folder / 'alert-rule-manifest.json'
        write_json(path, dict(experiment=spec['id'], family='FAM-006', rule_ids=result['maximizing_rule_ids'],
            observed_result=result, input_sha256=spec['input']['input_sha256'], units_sha256=spec['input']['units_sha256'],
            note='Exploratory freeze of every maximizing formula; no candidate or reserved-data confirmation claimed.'))
        manifest = dict(path=str(path.relative_to(root)), sha256=sha(path))
        append(root / 'registry/events.jsonl', 'exploratory_rule_manifest_frozen', dict(id=spec['id'], **manifest))
    report = dict(id=spec['id'], family='FAM-006', completed_utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'], counts=spec['input']['counts'],
        raw_result_path=str(raw_path.relative_to(root)), raw_result_sha256=sha(raw_path), **result,
        references=references, reference_samples=samples, numerical_alert=alert, candidate_retained=False,
        internal_verification_pending=True, verdict='ouverte' if alert else 'rien', verdict_pending_internal_check=True,
        alert_rule_manifest=manifest, unique_maximizing_parameter=len(result['maximizing_rule_ids']) == 1,
        historical_certification_required_to_compute=False, confirmatory_p=False, independent_scientific_replication=False,
        cumulative_target_executions=17, cumulative_completed_target_executions=16, cumulative_incomplete_target_executions=1,
        scope='Complete modern editions; exactly768frozen reset-at-window recurrences, shared three verse groups, Greek length8..32. This bounded exploratory screen does not exclude other relations.')
    write_json(root / REPORT, report)
    append(root / 'registry/events.jsonl', 'modern_target_completed', dict(id=spec['id'], report=REPORT,
        report_sha256=sha(root / REPORT), score=result['score'], numerical_alert=alert, cumulative_completed=16, cumulative_started=17))
    return {k: report[k] for k in ('id', 'score', 'maximizing_rule_ids', 'references', 'numerical_alert', 'verdict')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'run'))
    print(json.dumps(globals()[parser.parse_args().command](), indent=2), flush=True)
