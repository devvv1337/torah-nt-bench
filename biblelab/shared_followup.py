"""Prospectively registered short-signal and translation controls; no NT input."""
import json
import platform
import random
import sys

from .sources import ROOT, digest, verify, write_json
from .registry import append, read_events, snapshot_code
from .editions import controls
from .local_search import calibration_units, dss_units, greek_verses, report_record
from .shared_search import build_engine, grouped, save_input, scan, validate_witness, reference_summary
from .statistics import wilson
from .translation_source import verify_translation, parse_swete


def setup(root, protocol_name):
    path = root / f'protocol/{protocol_name}.json'
    spec = json.loads(path.read_text())
    sha = digest(path.read_bytes())
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha
               for e in read_events(root / 'registry/events.jsonl')), 'Protocol not registered'
    family_path = root / 'protocol/shared-substitution-v1.json'
    family = json.loads(family_path.read_text())
    assert (family['minimum_length'], family['maximum_length'], family['passage_pairs']) == (16, 32, 3)
    binary, native = build_engine(root)
    metadata = dict(protocol_sha256=sha, family_sha256=digest(family_path.read_bytes()),
                    source_integrity=verify(root), code_snapshot=snapshot_code(root), native=native,
                    python_version=sys.version, platform=platform.platform(),
                    independent_scientific_replication=False, new_target_explorations=0)
    append(root / 'registry/events.jsonl', 'shared_followup_started', dict(id=spec['id'], **metadata))
    return spec, metadata, binary


def execute(root, binary, path, left, right, draws, seed):
    save_input(path, left, right)
    result = scan(binary, path, draws, seed)
    validate_witness(result, left, right)
    samples = {}
    for mode in ('words', 'word_types'):
        for label, index in [('first', 0), ('last', -1)]:
            sample = path.with_name(path.name + f'.{mode}.{label}.txt')
            samples[f'{mode}_{label}'] = dict(path=str(sample.relative_to(root)),
                sha256=digest(sample.read_bytes()), score=result['reference_scores'][mode][index], mode=mode)
    return dict(input_path=str(path.relative_to(root)), input_sha256=digest(path.read_bytes()),
                draws_per_model=draws, seed=seed, result=result,
                references=reference_summary(result), reference_samples=samples)


def implant(left, right, mapping, coordinates, length):
    """Preserve every non-planted letter and all original four-letter token boundaries."""
    assert sorted(mapping) == list(range(24))
    assert len(coordinates) == 3
    assert len({left[lu]['group'] for lu, _, _, _ in coordinates}) == 3
    assert len({right[ru]['group'] for _, _, ru, _ in coordinates}) == 3
    modified = [dict(unit, words=list(unit['words'])) for unit in right]
    for lu, ls, ru, rs in coordinates:
        piece = ''.join(left[lu]['words'])[ls:ls + length]
        assert len(piece) == length and len(set(piece)) >= 8
        transformed = ''.join(chr(65 + mapping[ord(c) - 65]) for c in piece)
        original = ''.join(right[ru]['words'])
        assert len(original) == 64 and rs >= 0 and rs + length <= len(original)
        altered = original[:rs] + transformed + original[rs + length:]
        modified[ru]['words'] = [altered[i:i + 4] for i in range(0, len(altered), 4)]
    return modified


def covers_implants(result, coordinates, length):
    return all(any(h['direction'] == 1 and h['left_unit'] == lu and h['right_unit'] == ru
                   and h['left_start'] <= ls and h['left_end'] >= ls + length
                   and ls - h['left_start'] == rs - h['right_start']
                   for h in result['witness']) for lu, ls, ru, rs in coordinates)


def run_short(root=ROOT):
    spec, metadata, binary = setup(root, 'shared-short-calibration-v1')
    prior_path = root / 'reports/shared-calibration-v1.json'
    prior = json.loads(prior_path.read_text())
    assert prior['calibration_gate_pass']
    metadata['paired_cal006_sha256'] = digest(prior_path.read_bytes())
    controls(root)
    control_path = root / 'data/derived/controls.json'
    data = json.loads(control_path.read_text())
    metadata['control_data_sha256'] = digest(control_path.read_bytes())
    assert metadata['control_data_sha256'] == prior['metadata']['human_control_data_sha256']
    l, r = calibration_units(data)
    left, right = grouped(l, True), grouped(r)
    rng = random.Random(spec['mapping_seed'])
    mappings = []
    for trial in range(spec['trials_per_length']):
        mapping = list(range(24))
        rng.shuffle(mapping)
        assert mapping == prior['injections'][trial]['mapping']
        mappings.append(mapping)
    conditions = []
    for length in spec['lengths']:
        injections = []
        for trial, mapping in enumerate(mappings):
            modified = implant(left, right, mapping, spec['planted_coordinates'], length)
            path = root / f'data/derived/shared-short/length-{length}-trial-{trial:02d}.txt'
            record = execute(root, binary, path, left, modified, spec['references_per_model'],
                             spec['mapping_seed'] + 1000 + trial)
            reached = record['result']['score'] >= length
            detection = reached and all(r['p'] <= .01 for r in record['references'].values())
            injections.append(dict(trial=trial, length=length, mapping=mapping,
                planted_coordinates=spec['planted_coordinates'], literal_plants_valid=True,
                reached_planted_length=reached,
                maximizing_witness_covers_implants=covers_implants(record['result'], spec['planted_coordinates'], length),
                detection=detection, **record))
        detected = sum(r['detection'] for r in injections)
        condition = dict(length=length, trials=len(injections), detections=detected,
            wilson95=wilson(detected, len(injections)),
            gate_pass=detected >= 18 and all(r['reached_planted_length'] for r in injections), injections=injections)
        conditions.append(condition)
        print('CAL-007', length, dict(detections=detected, gate_pass=condition['gate_pass']), flush=True)
    gate = all(c['gate_pass'] for c in conditions)
    report = dict(id=spec['id'], family=spec['family'], protocol=spec, metadata=metadata,
        conditions=conditions, calibration_gate_pass=gate,
        total_paired_conditions=sum(c['trials'] for c in conditions), independent_backgrounds=1,
        new_target_explorations=0, independent_scientific_replication=False)
    sha = report_record(root, 'shared-short-calibration-v1', report, 'shared_short_calibration_finished',
        dict(id=spec['id'], gate_pass=gate, new_target_explorations=0))
    return dict(gate_pass=gate, detections_by_length={c['length']:c['detections'] for c in conditions}, report_sha256=sha)


def translation_inputs(root=ROOT):
    ancient, provenance = dss_units(root, {'minimum_length':16})
    provenance['selection'] = 'Unreviewed composite groups excluded; >=16 letters; same audited islands as FAM-002'
    labels = sorted({u['reference'] for u in ancient})
    assert all(isinstance(ref, str) and ref.strip() for ref in labels)
    label_to_group = {ref:i for i, ref in enumerate(labels)}
    left = grouped([dict(u, group=label_to_group[u['reference']]) for u in ancient], True)
    verses, counts = parse_swete(root / 'data/raw/swete')
    assert len({v['ref'] for v in verses}) == len(verses)
    right = grouped(greek_verses(verses))
    units = dict(left=[dict(u, group=label_to_group[u['reference']]) for u in ancient],
                 right=greek_verses(verses), left_group_labels=labels,
                 right_group_labels=[v['ref'] for v in verses])
    return left, right, units, dict(witness_provenance=provenance, translation_source_counts=counts)


def run_translation(root=ROOT):
    spec, metadata, binary = setup(root, 'shared-translation-control-v1')
    metadata['translation_integrity'] = verify_translation(root)
    left, right, units, provenance = translation_inputs(root)
    folder = root / 'data/derived/shared-translation'
    unit_path = folder / 'units.json'
    write_json(unit_path, units)
    record = execute(root, binary, folder / 'dss-swete.txt', left, right,
                     spec['references_per_model'], spec['seed'])
    alert = record['result']['score'] >= 16 and all(r['p'] <= .01 for r in record['references'].values())
    report = dict(id=spec['id'], family=spec['family'], protocol=spec, metadata=metadata, **provenance,
        unit_metadata_path=str(unit_path.relative_to(root)), unit_metadata_sha256=digest(unit_path.read_bytes()),
        left_units=len(left), left_groups=len({u['group'] for u in left}),
        right_units=len(right), right_groups=len({u['group'] for u in right}),
        left_letters=sum(sum(map(len, u['words'])) for u in left),
        right_letters=sum(sum(map(len, u['words'])) for u in right),
        diagnostic_alert=alert, new_target_explorations=0, independent_scientific_replication=False, **record)
    sha = report_record(root, 'shared-translation-control-v1', report, 'shared_translation_control_finished',
        dict(id=spec['id'], score=record['result']['score'], diagnostic_alert=alert, new_target_explorations=0))
    return dict(score=record['result']['score'], p_values={m:v['p'] for m,v in record['references'].items()},
                diagnostic_alert=alert, report_sha256=sha)
