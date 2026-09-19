"""Complete frozen FAM-005 via an exact partition of base classes."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import subprocess

from .sources import ROOT, write_json
from .modern_local import sha, source_check
from .modern_contextual import reconstruct
from .modern_shared import serialize
from .registry import append, read_events

DIRECTORY = 'data/derived/modern-programs-v1'
PROTOCOL = 'protocol/modern-editions-fam005-v1.json'
REPORT = 'reports/modern-programs-exp016-v1.json'
KINDS = ('pair', 'triple', 'product')
RANGES = tuple((i, min(i + 32, 292)) for i in range(0, 292, 32))


def aggregate(parts, seed_limit=5000000):
    """No per-batch p-values: concatenate disjoint rule vectors and maximize."""
    parts = sorted(parts, key=lambda p: p['base_begin'])
    cursor = 0
    scores = [0] * 7008
    draws = len(parts[0]['reference_scores']['words'])
    for part in parts:
        begin, end = part['base_begin'], part['base_end']
        assert begin == cursor and begin < end <= 292, 'Missing, overlapping or duplicated base class'
        cursor = end
        assert len(part['rule_scores']) == 7008
        assert all(x == 0 for i, x in enumerate(part['rule_scores']) if not begin*24 <= i < end*24)
        scores[begin*24:end*24] = part['rule_scores'][begin*24:end*24]
        assert part['score'] == max(part['rule_scores'])
        assert part['maximizing_rule_ids'] == [i for i, x in enumerate(part['rule_scores']) if x > 0 and x == part['score']]
        expected_sub = dict(pair=max(part['rule_scores'][:768]), triple=max(part['rule_scores'][768:4608]), product=max(part['rule_scores'][4608:]))
        assert part['opcode_maxima'] == expected_sub
        for mode in ('words', 'word_types'):
            assert len(part['reference_scores'][mode]) == len(part['reference_seed_pairs'][mode]) == draws
            assert all(len(part['reference_opcode_maxima'][mode][k]) == draws for k in KINDS)
            assert part['reference_scores'][mode] == [max(part['reference_opcode_maxima'][mode][k][i] for k in KINDS) for i in range(draws)]
    assert cursor == 292, 'Incomplete family'
    score = max(scores)
    winners = sorted((w for p in parts if p['score'] == score for w in p['witnesses']), key=lambda w: w['program']['rule_id'])
    ids = [i for i, value in enumerate(scores) if value > 0 and value == score]
    assert ids == [w['program']['rule_id'] for w in winners]
    first = parts[0]
    for part in parts:
        for key in ('right_starts', 'left_oriented_starts_by_span'):
            assert part[key] == first[key]
    indexed = sum(p['indexed_source_starts'] for p in parts)
    seeds = sum(p['compatible_seed_pairs'] for p in parts)
    assert seeds <= seed_limit, 'Whole-family compatible seed guard exceeded'
    reference_scores, reference_opcodes, reference_seeds = {}, {}, {}
    for mode in ('words', 'word_types'):
        reference_scores[mode] = [max(p['reference_scores'][mode][i] for p in parts) for i in range(draws)]
        reference_opcodes[mode] = {k: [max(p['reference_opcode_maxima'][mode][k][i] for p in parts) for i in range(draws)] for k in KINDS}
        reference_seeds[mode] = [sum(p['reference_seed_pairs'][mode][i] for p in parts) for i in range(draws)]
        assert all(s <= seed_limit for s in reference_seeds[mode]), 'Whole-family reference seed guard exceeded'
    return dict(score=score, indexed_source_starts=indexed, right_starts=first['right_starts'],
        formal_program_start_pairs=indexed*first['right_starts']*24, compatible_seed_pairs=seeds,
        left_oriented_starts_by_span=first['left_oriented_starts_by_span'],
        indexed_starts_by_kind={k: sum(p['indexed_starts_by_kind'][k] for p in parts) for k in KINDS},
        opcode_maxima=dict(pair=max(scores[:768]), triple=max(scores[768:4608]), product=max(scores[4608:])),
        rule_scores=scores, maximizing_rule_ids=ids, witnesses=winners, reference_scores=reference_scores,
        reference_opcode_maxima=reference_opcodes, reference_seed_pairs=reference_seeds)


def prepare(root=ROOT):
    sources = source_check(root)
    units = reconstruct(root)
    prior = json.loads((root / 'data/derived/modern-contextual-v1/preparation.json').read_text())
    assert sha(root / prior['units_path']) == prior['units_sha256']
    assert units == json.loads((root / prior['units_path']).read_text())
    text = serialize(units['left'], units['right'])
    assert sha(root / prior['input_path']) == prior['input_sha256']
    assert text == (root / prior['input_path']).read_text()
    folder = root / DIRECTORY
    folder.mkdir(parents=True, exist_ok=True)
    assert not (folder / 'input.txt').exists(), 'Preserve previous preparation'
    (folder / 'input.txt').write_text(text, encoding='ascii')
    write_json(folder / 'units.json', units)
    starts = {span: sum(max(0, sum(map(len, u['words'])) - 8 - span + 2) for u in units['left']) for span in (2, 3)}
    batches = [dict(index=i, begin=a, end=b, indexed_starts=sum(starts[3 if 32 <= base < 192 else 2] for base in range(a, b))) for i, (a, b) in enumerate(RANGES)]
    assert sum(b['indexed_starts'] for b in batches) == 74410992
    assert max(b['indexed_starts'] for b in batches) <= 10000000
    receipt = dict(source_hashes=sources, counts=prior['counts'], normalization=prior['normalization'],
        boundaries=prior['boundaries'], no_dss_files_read=True, all_units_reextracted_from_raw_xml=True,
        indexed_source_starts=74410992, batches=batches)
    for key in ('input', 'units'):
        p = folder / (key + ('.txt' if key == 'input' else '.json'))
        receipt[key + '_path'] = str(p.relative_to(root))
        receipt[key + '_sha256'] = sha(p)
    write_json(folder / 'preparation.json', receipt)
    return {k: v for k, v in receipt.items() if k != 'source_hashes'}


def verify_frozen(root):
    spec = json.loads((root / PROTOCOL).read_text())
    assert source_check(root) == spec['input']['source_hashes']
    for name, checksum in spec['code_hashes'].items():
        assert sha(root / name) == checksum, name
    for key in ('input', 'units'):
        assert sha(root / spec['input'][key + '_path']) == spec['input'][key + '_sha256']
    for entry in spec['existing_diagnostics'].values():
        assert sha(root / entry['path']) == entry['sha256']
    assert [(b['begin'], b['end']) for b in spec['input']['batches']] == list(RANGES)
    return spec


def run(root=ROOT):
    with (root / 'tmp/modern-programs-exp016.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            return _run(root)
        except Exception as exc:
            events = read_events(root / 'registry/events.jsonl')
            started = any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == 'EXP-016' for e in events)
            ended = any(e['kind'] in ('modern_target_failed', 'modern_target_completed') and e['payload'].get('id') == 'EXP-016' for e in events)
            if started and not ended:
                append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id='EXP-016', error=repr(exc),
                    verdict='ouverte; incomplete execution or aggregation', outputs_preserved=True))
            raise


def _run(root):
    spec = verify_frozen(root)
    events = read_events(root / 'registry/events.jsonl')
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha(root / PROTOCOL) for e in events)
    assert not any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == spec['id'] for e in events), 'Never restart a begun target'
    assert not (root / REPORT).exists()
    folder = root / DIRECTORY
    compiler = shutil.which('clang++')
    assert compiler
    binary = folder / 'short_programs_batch'
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic']
    subprocess.run([compiler, *flags, str(root / 'native/short_programs_batch.cpp'), '-o', str(binary)], check=True)
    append(root / 'registry/events.jsonl', 'modern_target_started', dict(id=spec['id'], family='FAM-005',
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'], cumulative_started=16,
        new_target_executions=1, batches=10, new_independent_trials_from_batches=0,
        binary_sha256=sha(binary), compiler=subprocess.check_output([compiler, '--version'], text=True), flags=flags))
    print('EXP-016 started: ten fixed batches, two concurrent, all 7008 programs and 999 references per model.', flush=True)
    def execute(batch):
        directory = folder / f'batch-{batch["index"]:02d}'
        directory.mkdir()
        path = directory / 'input.txt'
        path.write_bytes((root / spec['input']['input_path']).read_bytes())
        raw, error = directory / 'raw-result.json', directory / 'stderr.txt'
        with raw.open('w') as output, error.open('w') as errors:
            process = subprocess.run([str(binary), str(path), str(spec['minimum_length']), str(spec['maximum_length']),
                str(spec['reference_draws_per_model']), str(spec['seed']), str(batch['begin']), str(batch['end'])], stdout=output, stderr=errors)
        return dict(batch=batch, return_code=process.returncode, input_path=str(path.relative_to(root)),
            input_sha256=sha(path), raw_path=str(raw.relative_to(root)), raw_sha256=sha(raw), stderr_sha256=sha(error))
    receipts = []
    failed = False
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {}
        todo = iter(spec['input']['batches'])
        def submit():
            batch = next(todo, None)
            if batch is None:
                return
            append(root / 'registry/events.jsonl', 'modern_batch_submitted', dict(id=spec['id'], **batch))
            pending[pool.submit(execute, batch)] = batch
        submit(); submit()
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                batch = pending.pop(future)
                try:
                    receipt = future.result()
                except Exception as exc:
                    receipt = dict(batch=batch, return_code=-1, exception=repr(exc))
                path = folder / f'batch-{batch["index"]:02d}.receipt.json'
                write_json(path, receipt)
                append(root / 'registry/events.jsonl', 'modern_batch_finished', dict(id=spec['id'], index=batch['index'],
                    receipt_path=str(path.relative_to(root)), receipt_sha256=sha(path), return_code=receipt['return_code']))
                receipts.append(receipt)
                print(f'Batch {batch["index"]+1}/10 finished, exit={receipt["return_code"]}.', flush=True)
                failed = failed or receipt['return_code'] != 0
            if not failed:
                for _ in finished:
                    submit()
    if failed or len(receipts) != 10:
        append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id=spec['id'], complete_batches=sum(r['return_code'] == 0 for r in receipts), verdict='ouverte; incomplete'))
        raise RuntimeError('Incomplete batch family; preserve outputs, no negative or automatic retry')
    parts, samples = [], None
    for receipt in sorted(receipts, key=lambda r: r['batch']['index']):
        assert sha(root / receipt['raw_path']) == receipt['raw_sha256']
        assert receipt['input_sha256'] == spec['input']['input_sha256']
        part = json.loads((root / receipt['raw_path']).read_text())
        assert (part['base_begin'], part['base_end']) == (receipt['batch']['begin'], receipt['batch']['end'])
        assert part['indexed_source_starts'] == receipt['batch']['indexed_starts']
        current = {}
        for mode in ('words', 'word_types'):
            for end in ('first', 'last'):
                path = root / (receipt['input_path'] + f'.{mode}.{end}.txt')
                current[f'{mode}_{end}'] = dict(path=str(path.relative_to(root)), sha256=sha(path), mode=mode)
        if samples is None:
            samples = current
        else:
            assert {k: v['sha256'] for k, v in current.items()} == {k: v['sha256'] for k, v in samples.items()}
        parts.append(part)
    result = aggregate(parts)
    prior = json.loads((root / spec['nested_baseline']['path']).read_text())
    assert sha(root / spec['nested_baseline']['path']) == spec['nested_baseline']['sha256']
    assert result['rule_scores'][:768] == prior['rule_scores']
    references = {}
    for mode, values in result['reference_scores'].items():
        assert len(values) == spec['reference_draws_per_model']
        exceeds = sum(v >= result['score'] for v in values)
        references[mode] = dict(draws=len(values), exceedances=exceeds, p=(1 + exceeds)/(1 + len(values)), histogram=dict(sorted(Counter(values).items())))
        for end, index in [('first', 0), ('last', -1)]:
            samples[f'{mode}_{end}']['score'] = values[index]
            samples[f'{mode}_{end}']['opcode_maxima'] = {k: result['reference_opcode_maxima'][mode][k][index] for k in KINDS}
    alert = result['score'] >= spec['candidate_screen']['minimum_length'] and all(r['p'] <= spec['candidate_screen']['p_each_model_max'] for r in references.values())
    manifest = None
    if alert:
        path = folder / 'alert-rule-manifest.json'
        write_json(path, dict(experiment=spec['id'], observed=result, input_sha256=spec['input']['input_sha256'], note='All maximizing programs frozen; not a retained or confirmed candidate.'))
        manifest = dict(path=str(path.relative_to(root)), sha256=sha(path))
        append(root / 'registry/events.jsonl', 'exploratory_rule_manifest_frozen', dict(id=spec['id'], **manifest))
    report = dict(id=spec['id'], family='FAM-005', completed_utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'], counts=spec['input']['counts'],
        **result, references=references, reference_samples=samples, batch_receipts=receipts,
        nested_768_scores_identical_to_exp015=True, numerical_alert=alert, candidate_retained=False, alert_rule_manifest=manifest,
        verdict='ouverte' if alert else 'rien', internal_verification_pending=True, verdict_pending_internal_check=True,
        historical_certification_required_to_compute=False, independent_scientific_replication=False, confirmatory_p=False,
        cumulative_target_executions=16, cumulative_completed_target_executions=15, cumulative_incomplete_target_executions=1)
    write_json(root / REPORT, report)
    append(root / 'registry/events.jsonl', 'modern_target_completed', dict(id=spec['id'], report=REPORT, report_sha256=sha(root / REPORT),
        score=result['score'], numerical_alert=alert, cumulative_started=16, cumulative_completed=15))
    return {k: report[k] for k in ('id', 'score', 'opcode_maxima', 'maximizing_rule_ids', 'references', 'numerical_alert', 'verdict')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'run'))
    print(json.dumps(globals()[parser.parse_args().command](), indent=2), flush=True)
