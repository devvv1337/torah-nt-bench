"""EXP-004: first exposed-data target screen of the calibrated shared-table family."""
import json
import math
import platform
import sys

from .sources import ROOT, NT, digest, verify, write_json
from .registry import append, read_events, snapshot_code
from .editions import sbl
from .letters import HEBREW, GREEK
from .local_search import dss_units, greek_verses, report_record
from .shared_search import build_engine, grouped
from .shared_followup import execute


def inputs(root=ROOT):
    ancient, provenance = dss_units(root, {'minimum_length':16})
    provenance['selection'] = 'Simple physical group labels and >=16 letters; no new dating or photographic certification'
    labels = sorted({u['reference'] for u in ancient})
    assert all(isinstance(ref,str) and ref.strip() for ref in labels)
    groups = {ref:i for i,ref in enumerate(labels)}
    ancient = [dict(u,group=groups[u['reference']]) for u in ancient]
    verses = [v for book in NT for v in sbl(root/f'data/raw/sblgnt/data/sblgnt/xml/{book}.xml')[0]]
    assert len(verses) == len({v['ref'] for v in verses}) == 7939
    greek = greek_verses(verses)
    left, right = grouped(ancient,True), grouped(greek)
    # The comparison explicitly stays on the old letter inputs; no quiet normalization change.
    prior = json.loads((root/'data/derived/local/dss_nt-units.json').read_text())
    assert greek == prior['right']
    assert [dict(u,group=groups[u['reference']]) for u in prior['left'] if len(u['encoded']) >= 16] == ancient
    return left, right, dict(left=ancient,right=greek,left_group_labels=labels,
        right_group_labels=[v['ref'] for v in verses]), provenance


def contextualize(result, units):
    details = []
    for hit in result['witness']:
        a, b = units['left'][hit['left_unit']], units['right'][hit['right_unit']]
        native = a['encoded'][hit['left_start']:hit['left_end']]
        q = native[::hit['direction']]
        r = ''.join(b['encoded_words'])[hit['right_start']:hit['right_start']+hit['length']]
        details.append(dict(**hit,left_id=a['id'],left_group=a['group'],hebrew_reference=a['reference'],
            scroll=a['scroll'],fragment=a['fragment'],line=a['line'],right_reference=b['id'],
            hebrew_native=''.join(HEBREW[ord(c)-65] for c in native),
            hebrew_match_order=''.join(HEBREW[ord(c)-65] for c in q),
            greek_letters=''.join(GREEK[ord(c)-65] for c in r),
            letter_slots=a['letter_slots'][hit['left_start']:hit['left_end']],
            photographic_collation=False,chronology_verified_for_this_island=False))
    return details


def run(root=ROOT):
    protocol_path = root/'protocol/shared-exploration-v1.json'
    spec = json.loads(protocol_path.read_text()); protocol_sha = digest(protocol_path.read_bytes())
    assert any(e['kind']=='protocol_frozen' and e['payload'].get('sha256')==protocol_sha
               for e in read_events(root/'registry/events.jsonl'))
    family_path = root/'protocol/shared-substitution-v1.json'
    family = json.loads(family_path.read_text())
    assert (family['minimum_length'],family['maximum_length'],family['passage_pairs']) == (16,32,3)
    prerequisites = {}
    reports = {}
    for name in ('shared-calibration-v1','shared-short-calibration-v1','shared-translation-control-v1','shared-followup-algorithm-check'):
        path = root/f'reports/{name}.json'
        reports[name] = json.loads(path.read_text()); prerequisites[name] = digest(path.read_bytes())
    assert reports['shared-calibration-v1']['calibration_gate_pass']
    assert reports['shared-short-calibration-v1']['calibration_gate_pass']
    assert not reports['shared-translation-control-v1']['diagnostic_alert']
    validation = reports['shared-followup-algorithm-check']
    assert validation['short_calibration_sha256'] == prerequisites['shared-short-calibration-v1']
    assert validation['translation_control_sha256'] == prerequisites['shared-translation-control-v1']
    binary, native = build_engine(root)
    metadata = dict(protocol_sha256=protocol_sha,family_sha256=digest(family_path.read_bytes()),
        source_integrity=verify(root),code_snapshot=snapshot_code(root),native=native,
        prerequisite_report_hashes=prerequisites,python_version=sys.version,platform=platform.platform(),
        confirmation=False,independent_scientific_replication=False)
    left, right, units, provenance = inputs(root)
    folder = root/'data/derived/shared-target'; unit_path = folder/'units.json'; write_json(unit_path,units)
    append(root/'registry/events.jsonl','target_exploration_started',dict(id=spec['id'],family=spec['family'],
        **metadata,witness_provenance=provenance,prior_target_evaluations=3,exposed_data=True))
    try:
        record = execute(root,binary,folder/'dss-nt.txt',left,right,spec['references_per_model'],spec['seed'])
    except Exception as exc:
        append(root/'registry/events.jsonl','target_exploration_failed',dict(id=spec['id'],family=spec['family'],
            error=repr(exc),statistical_conclusion=False,attempt_remains_counted=True))
        raise
    score = record['result']['score']
    passed = score >= 16 and all(v['p'] <= .01 for v in record['references'].values())
    cost = dict(formal_partial_injective_tables=sum(math.comb(22,d)*math.perm(24,d) for d in range(8,23)),
        directions=2,common_lengths=17,grammar_bytes=len(family_path.read_bytes()),
        target_protocol_bytes=len(protocol_path.read_bytes()),
        shared_decoder_bytes=len((root/'native/shared_match.cpp').read_bytes()),
        dependency_decoder_bytes=len((root/'native/local_match.cpp').read_bytes()),
        note='Complete scan charges all tables, directions, prefix lengths, units/groups and starts; formal counts are not independent trials or absolute description complexity.')
    report = dict(id=spec['id'],family=spec['family'],protocol=spec,metadata=metadata,
        witness_provenance=provenance,description_scope=cost,
        unit_metadata_path=str(unit_path.relative_to(root)),unit_metadata_sha256=digest(unit_path.read_bytes()),
        left_units=len(left),left_groups=len({u['group'] for u in left}),
        right_units=len(right),right_groups=len({u['group'] for u in right}),
        left_letters=sum(sum(map(len,u['words'])) for u in left),
        right_letters=sum(sum(map(len,u['words'])) for u in right),
        witness_details=contextualize(record['result'],units),candidate_screen_pass=passed,
        refutation_work_required=passed,candidates_retained=0,external_confirmations=0,
        target_evaluation_index=4,families_explored_on_target=3,
        new_target_explorations=1,independent_scientific_replication=False,**record)
    sha = report_record(root,'shared-exploration-v1',report,'target_exploration_finished',
        dict(id=spec['id'],family=spec['family'],score=score,start_pairs=record['result']['start_pairs'],
             compatible_seed_pairs=record['result']['compatible_seed_pairs'],
             p_values={m:r['p'] for m,r in record['references'].items()},candidate_screen_pass=passed,
             confirmations=0,new_target_explorations=1))
    return dict(score=score,p_values={m:r['p'] for m,r in record['references'].items()},
                candidate_screen_pass=passed,confirmations=0,report_sha256=sha)
