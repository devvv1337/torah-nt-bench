"""CAL-008: artificial shared signals on the full exposed target background."""
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import random

from .sources import ROOT, digest, write_json
from .registry import append, canonical
from .local_search import report_record
from .shared_target import inputs
from .shared_followup import setup, execute
from .shared_search import validate_witness, reference_summary
from .statistics import wilson


def assignments(left, right, spec):
    """Use only within-side length/diversity and fixed RNGs, never matching scores."""
    eligible = {}
    for direction in (1, -1):
        by_group = defaultdict(list)
        for index, unit in enumerate(left):
            text = ''.join(unit['words'])[::direction]
            for start in range(len(text)-31):
                if len(set(text[start:start+16])) >= 8:
                    by_group[unit['group']].append((index,start))
        eligible[direction] = by_group
        if len(by_group) < 3:
            raise ValueError('Fewer than three eligible Hebrew groups')
    right_eligible = [i for i,u in enumerate(right) if sum(map(len,u['words'])) >= 32]
    if len(right_eligible) < 3:
        raise ValueError('Fewer than three eligible Greek groups')
    assert len({right[i]['group'] for i in right_eligible}) == len(right_eligible)
    rng = random.Random(spec['coordinate_seed'])
    map_rng = random.Random(spec['mapping_seed'])
    trials = []
    for trial in range(spec['trials_per_length']):
        direction = 1 if trial % 2 == 0 else -1
        by_group = eligible[direction]
        group_ids = rng.sample(sorted(by_group),3)
        sources = [rng.choice(by_group[group]) for group in group_ids]
        destinations = rng.sample(right_eligible,3)
        starts = [rng.randrange(sum(map(len,right[i]['words']))-31) for i in destinations]
        coordinates = [dict(left_unit=li,left_oriented_start=ls,right_unit=ri,right_start=rs)
                       for (li,ls),ri,rs in zip(sources,destinations,starts,strict=True)]
        mapping = list(range(24)); map_rng.shuffle(mapping)
        trials.append(dict(trial=trial,direction=direction,mapping=mapping,coordinates=coordinates,
                           seed=2026093890+trial))
    summary = dict(source_eligible_groups={str(d):len(v) for d,v in eligible.items()},
        source_eligible_windows={str(d):sum(map(len,v.values())) for d,v in eligible.items()},
        right_eligible_units=len(right_eligible))
    return trials, summary


def plant(left, right, assignment, length):
    mapping = assignment['mapping']; direction = assignment['direction']
    assert sorted(mapping) == list(range(24)) and direction in (1,-1)
    coordinates = assignment['coordinates']
    assert len(coordinates) == 3
    assert len({left[c['left_unit']]['group'] for c in coordinates}) == 3
    assert len({right[c['right_unit']]['group'] for c in coordinates}) == 3
    modified = [dict(u,words=list(u['words'])) for u in right]
    for c in coordinates:
        lu,ls,ru,rs = (c[k] for k in ('left_unit','left_oriented_start','right_unit','right_start'))
        source = ''.join(left[lu]['words'])[::direction][ls:ls+length]
        assert len(source) == length and len(set(source)) >= 8
        original = ''.join(right[ru]['words'])
        assert 0 <= rs and rs+length <= len(original)
        mapped = ''.join(chr(65+mapping[ord(x)-65]) for x in source)
        altered = original[:rs]+mapped+original[rs+length:]
        lengths = [len(word) for word in right[ru]['words']]
        words = []; offset = 0
        for n in lengths:
            words.append(altered[offset:offset+n]); offset += n
        assert offset == len(altered) and [len(w) for w in words] == lengths
        modified[ru]['words'] = words
    return modified


def covers(result, assignment, length):
    return all(any(h['direction'] == assignment['direction']
                   and h['left_unit'] == c['left_unit'] and h['right_unit'] == c['right_unit']
                   and h['left_oriented_start'] <= c['left_oriented_start']
                   and h['left_oriented_start']+h['length'] >= c['left_oriented_start']+length
                   and c['left_oriented_start']-h['left_oriented_start'] == c['right_start']-h['right_start']
                   for h in result['witness']) for c in assignment['coordinates'])


def input_bytes(left, right):
    lines = [f'{len(left)} {len(right)}']
    lines.extend(str(u['group'])+' '+' '.join(u['words']) for u in left+right)
    return ('\n'.join(lines)+'\n').encode('ascii')


def summarize(records):
    detections = sum(r['detection'] for r in records)
    directions = {}
    for direction in (1,-1):
        rows = [r for r in records if r['assignment']['direction'] == direction]
        hits = sum(r['detection'] for r in rows)
        directions[str(direction)] = dict(trials=len(rows),detections=hits,wilson95=wilson(hits,len(rows)))
    return dict(trials=len(records),detections=detections,wilson95=wilson(detections,len(records)),
        directions=directions,gate_pass=detections >= 18 and all(d['detections'] >= 9 for d in directions.values())
            and all(r['reached_planted_length'] and r['literal_plants_valid'] for r in records),
        observed_score_histogram=dict(sorted(Counter(r['result']['score'] for r in records).items())),
        reference_score_histograms={mode:dict(sorted(Counter(s for r in records for s in r['result']['reference_scores'][mode]).items()))
                                   for mode in ('words','word_types')},
        maximizing_witnesses_covering_plants=sum(r['maximizing_witness_covers_implants'] for r in records))


def _run(root):
    spec, metadata, binary = setup(root,'shared-full-calibration-v1')
    base_path = root/'reports/shared-exploration-v1.json'
    assert digest(base_path.read_bytes()) == spec['base_report_sha256']
    base = json.loads(base_path.read_text())
    validation_path = root/'reports/shared-target-algorithm-check.json'
    validation = json.loads(validation_path.read_text())
    assert validation['target_report_sha256'] == spec['base_report_sha256']
    left, right, units, provenance = inputs(root)
    raw = input_bytes(left,right)
    assert digest(raw) == base['input_sha256']
    assert (root/base['input_path']).read_bytes() == raw
    metadata.update(base_report_sha256=spec['base_report_sha256'],base_input_sha256=digest(raw),
                    base_verification_sha256=digest(validation_path.read_bytes()),witness_provenance=provenance)
    plans, eligible = assignments(left,right,spec)
    folder = root/'data/derived/shared-full'
    assignment_path = folder/'assignments.json'
    assignment_data = dict(protocol_sha256=metadata['protocol_sha256'],base_input_sha256=metadata['base_input_sha256'],
                          eligible=eligible,assignments=plans)
    if assignment_path.exists():
        assert json.loads(assignment_path.read_text()) == assignment_data, 'Saved assignment changed'
    else:
        write_json(assignment_path,assignment_data)
    metadata['assignment_path'] = str(assignment_path.relative_to(root))
    metadata['assignment_sha256'] = digest(assignment_path.read_bytes())
    append(root/'registry/events.jsonl','shared_full_assignments_fixed',dict(id=spec['id'],
        sha256=metadata['assignment_sha256'],eligible=eligible,new_target_explorations=0))
    identity = dict(protocol_sha256=metadata['protocol_sha256'],base_input_sha256=metadata['base_input_sha256'],
                    native_binary_sha256=metadata['native']['binary_sha256'])

    def job(length, assignment):
        trial = assignment['trial']; modified = plant(left,right,assignment,length)
        path = folder/f'length-{length}-trial-{trial:02d}.txt'
        receipt_path = path.with_suffix('.receipt.json')
        expected_input_sha = digest(input_bytes(left,modified))
        execution_id = digest(canonical(dict(**identity,input_sha256=expected_input_sha,length=length,assignment=assignment)))
        reused = receipt_path.exists()
        if reused:
            envelope = json.loads(receipt_path.read_text())
            record = envelope['record']
            assert envelope['sha256'] == digest(canonical(record)) and record['execution_id'] == execution_id
            assert record['input_sha256'] == expected_input_sha == digest(path.read_bytes())
            for entry in record['reference_samples'].values():
                assert digest((root/entry['path']).read_bytes()) == entry['sha256']
            validate_witness(record['result'],left,modified)
            assert record['references'] == json.loads(json.dumps(reference_summary(record['result'])))
        else:
            core = execute(root,binary,path,left,modified,spec['references_per_model'],assignment['seed'])
            assert core['input_sha256'] == expected_input_sha
            reached = core['result']['score'] >= length
            record = dict(execution_id=execution_id,length=length,assignment=assignment,
                literal_plants_valid=True,reached_planted_length=reached,
                maximizing_witness_covers_implants=covers(core['result'],assignment,length),
                detection=reached and all(v['p'] <= .01 for v in core['references'].values()),**core)
            temporary = receipt_path.with_suffix('.tmp')
            write_json(temporary,dict(sha256=digest(canonical(record)),record=record)); temporary.replace(receipt_path)
        return record, reused, str(receipt_path.relative_to(root))

    jobs = [(length,a) for length in spec['lengths'] for a in plans]
    records = []; reused_count = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(job,length,a) for length,a in jobs]
        for future in futures:
            record, reused, receipt = future.result()
            records.append(record); reused_count += reused
            append(root/'registry/events.jsonl','shared_full_trial_completed',dict(id=spec['id'],
                length=record['length'],trial=record['assignment']['trial'],receipt_path=receipt,
                receipt_sha256=digest((root/receipt).read_bytes()),reused_identical_receipt=reused,new_target_explorations=0))
            print('CAL-008',record['length'],record['assignment']['trial'],
                  'score',record['result']['score'],'p',{m:v['p'] for m,v in record['references'].items()},
                  'reused',reused,flush=True)
    conditions = []
    for length in spec['lengths']:
        rows = [r for r in records if r['length'] == length]
        conditions.append(dict(length=length,**summarize(rows),injections=rows))
    gate = all(c['gate_pass'] for c in conditions)
    report = dict(id=spec['id'],family=spec['family'],protocol=spec,metadata=metadata,
        eligible=eligible,assignments=plans,conditions=conditions,calibration_gate_pass=gate,
        reused_identical_receipts=reused_count,total_paired_conditions=len(records),independent_backgrounds=1,
        new_target_explorations=0,independent_scientific_replication=False)
    sha = report_record(root,'shared-full-calibration-v1',report,'shared_full_calibration_finished',
        dict(id=spec['id'],gate_pass=gate,new_target_explorations=0))
    return dict(gate_pass=gate,detections_by_length={c['length']:c['detections'] for c in conditions},report_sha256=sha)


def run(root=ROOT):
    folder = root/'tmp'; folder.mkdir(parents=True,exist_ok=True)
    with (folder/'shared-full-calibration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            return _run(root)
        except Exception as exc:
            append(root/'registry/events.jsonl','shared_full_calibration_failed',dict(id='CAL-008',
                error=repr(exc),new_target_explorations=0,completed_calibration_claim=False))
            raise
