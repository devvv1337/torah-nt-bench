"""Gap-respecting local bijections with complete reselection in both controls."""
import collections
import json
import math
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import unicodedata
from .sources import ROOT,TORAH,NT,verify,digest,write_json
from .letters import HEBREW,GREEK,HEBREW_FINAL,normalize
from .editions import controls,sbl
from .translation_source import audit_translation
from .registry import append,snapshot_code
from .statistics import wilson
from .calibration import binomial_upper


def encode(text,language):
    if language=='he': text=text.translate(HEBREW_FINAL)
    alphabet={'he':HEBREW,'grc':GREEK}[language]
    return ''.join(chr(65+alphabet.index(c)) for c in text)


def build_engine(root=ROOT):
    source=root/'native/local_match.cpp'
    source_sha=digest(source.read_bytes())
    compiler=shutil.which('clang++')
    if not compiler: raise RuntimeError('C++17 compiler clang++ unavailable')
    version=subprocess.check_output([compiler,'--version'],text=True)
    flags=['-std=c++17','-O3','-Wall','-Wextra','-pedantic']
    directory=root/'tmp/native';directory.mkdir(parents=True,exist_ok=True)
    binary=directory/'local_match'
    receipt=directory/'build.json'
    identity=dict(source_sha256=source_sha,compiler=compiler,compiler_version=version,flags=flags)
    prior=json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(prior.get(k)!=v for k,v in identity.items()) or prior.get('binary_sha256')!=digest(binary.read_bytes()):
        compiled=subprocess.run([compiler,*flags,str(source),'-o',str(binary)],text=True,capture_output=True,check=True)
        write_json(receipt,dict(**identity,binary_sha256=digest(binary.read_bytes()),compiler_stderr=compiled.stderr))
    metadata=json.loads(receipt.read_text())
    archive=root/'registry/native'/source_sha/'local_match.cpp'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if archive.exists() and archive.read_bytes()!=source.read_bytes():raise ValueError('Native archive collision')
    archive.write_bytes(source.read_bytes())
    return binary,metadata


def save_input(path,left,right):
    lines=[f'{len(left)} {len(right)}']
    lines += [u['encoded'] for u in left]
    lines += [' '.join(u['encoded_words']) for u in right]
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(lines)+'\n',encoding='ascii')


def native_scan(binary,path,minimum,cap,draws,seed):
    result=subprocess.run([str(binary),str(path),str(minimum),str(cap),str(draws),str(seed)],
        text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def tail(observed,reference):
    if not reference:raise ValueError('Reference draws required')
    count=sum(x>=observed for x in reference)
    return dict(exceedances=count,p=(1+count)/(1+len(reference)))


def summarize_references(result):
    return {mode:dict(**tail(result['maximum'],values),draws=len(values),
        histogram=dict(sorted(collections.Counter(values).items()))) for mode,values in result['reference_maxima'].items()}


def greek_verses(verses):
    return [dict(id=v['ref'],encoded_words=[encode(w['letters'],'grc') for w in v['words'] if w['letters']],
                 source_word_count=len(v['words'])) for v in verses]


def calibration_units(control_data):
    left=encode(control_data['berakhot']['letters'][:1024],'he')
    right=encode(control_data['xenophon']['contiguous_prefix_letters'][:1024],'grc')
    if min(len(left),len(right))<1024:raise ValueError('Insufficient calibration prefix')
    return ([dict(id=str(i),encoded=left[64*i:64*(i+1)]) for i in range(16)],
            [dict(id=str(i),encoded_words=[right[64*i+j:64*i+j+4] for j in range(0,64,4)]) for i in range(16)])


def null_trials(values,spec):
    size=spec['references_per_null_trial']+1
    if len(values)!=spec['null_trials_per_model']*size:raise ValueError('Incorrect null trial count')
    trials=[dict(observed=values[i],reference_maxima=values[i+1:i+size],**tail(values[i],values[i+1:i+size]))
            for i in range(0,len(values),size)]
    k=sum(t['p']<=spec['alpha'] for t in trials);n=len(trials)
    upper=binomial_upper(k,n,spec['alpha'])
    return dict(trials=trials,rejections=k,repetitions=n,fraction=k/n,wilson95=wilson(k,n),
                binomial_upper_p=upper,false_positive_alarm=upper<.01)


def calibrate(root,binary,family,spec,data):
    left,right=calibration_units(data)
    path=root/'data/derived/local/calibration.txt';save_input(path,left,right)
    sample_count=spec['null_trials_per_model']*(1+spec['references_per_null_trial'])
    null=native_scan(binary,path,family['minimum_length'],family['maximum_length'],sample_count,spec['seed'])
    diagnostics={mode:null_trials(values,spec) for mode,values in null['reference_maxima'].items()}
    print('CAL-004 null:',{m:d['rejections'] for m,d in diagnostics.items()},flush=True)
    rng=random.Random(spec['seed']);injections=[]
    for trial in range(spec['injections']):
        mapping=list(range(24));rng.shuffle(mapping)
        right_copy=[dict(u,encoded_words=list(u['encoded_words'])) for u in right]
        inserted=''.join(chr(65+mapping[ord(c)-65]) for c in left[7]['encoded'][10:42])
        original=''.join(right_copy[5]['encoded_words'])
        altered=original[:16]+inserted+original[48:]
        right_copy[5]['encoded_words']=[altered[j:j+4] for j in range(0,64,4)]
        path=root/f'data/derived/local/injection-{trial:02d}.txt';save_input(path,left,right_copy)
        result=native_scan(binary,path,family['minimum_length'],family['maximum_length'],
            spec['injection_references_per_model'],spec['seed']+1000+trial)
        p=summarize_references(result)
        recovered=any(h['left_unit']==7 and h['direction']==1 and h['left_start']<=10 and h['left_end']>=42
            and h['right_unit']==5 and h['right_start']<=16 and h['right_start']+h['length']>=48
            and 10-h['left_start']==16-h['right_start'] for h in result['maximum_occurrences'])
        injections.append(dict(trial=trial,mapping=mapping,input_sha256=digest(path.read_bytes()),
            result=result,references=p,implanted_match_recovered=recovered,
            detection=result['maximum']>=32 and all(v['p']<=.01 for v in p.values())))
    detected=sum(r['detection'] for r in injections)
    gate=(not any(v['false_positive_alarm'] for v in diagnostics.values()) and detected>=18
          and all(r['implanted_match_recovered'] for r in injections))
    print(f'CAL-004 injected: {detected}/{len(injections)}, gate={gate}',flush=True)
    return dict(null_diagnostics=diagnostics,injections=injections,detections=detected,
        calibration_gate_pass=gate,baseline_input_sha256=digest((root/'data/derived/local/calibration.txt').read_bytes()),
        limitation='Artificial conditional permutation experiment only; sample power is not universal detectability or evidence of a divine source')


def dss_units(root,family):
    report=json.loads((root/'reports/witness-islands-v1.json').read_text())
    entry=report['outputs']['islands'];path=root/entry['path']
    if digest(path.read_bytes())!=entry['sha256']:raise ValueError('DSS derived islands do not match verified audit')
    if report['source_integrity']['manifest_sha256']!=digest((root/'data/sources.lock.json').read_bytes()):
        raise ValueError('DSS source manifest changed')
    with path.open() as f:rows=[json.loads(line) for line in f]
    chosen=[r for r in rows if not r['source_grouping_requires_review'] and len(r['letters'])>=family['minimum_length']]
    return [dict(r,encoded=encode(r['letters'],'he')) for r in chosen],dict(
        audit_sha256=digest((root/'reports/witness-islands-v1.json').read_bytes()),islands_sha256=entry['sha256'],
        selected_units=len(chosen),selected_letters=sum(len(r['letters']) for r in chosen),
        selection='simple physical group labels and >=12 letters; no additional dating or photographic certification')


def human_units(data):
    left=[dict(id=f'Berakhot-block-{i}',encoded=encode(normalize(raw,'he')['letters'],'he'))
          for i,raw in enumerate(data['berakhot']['raw'].splitlines()) if raw.strip()]
    prefix=data['xenophon']['raw'].split('\ufffc')[0]
    words=[normalize(raw,'grc')['letters'] for raw in prefix.split()]
    words=[encode(w,'grc') for w in words if w]
    right=[dict(id=f'Xenophon-words-{i}:{min(i+16,len(words))}',encoded_words=words[i:i+16])
           for i in range(0,len(words),16)]
    return left,right


def contextualize(result,left,right):
    detailed=[]
    for hit in result['maximum_occurrences']:
        l,r=left[hit['left_unit']],right[hit['right_unit']]
        native=l['encoded'][hit['left_start']:hit['left_end']]
        selected=native if hit['direction']==1 else native[::-1]
        greek=''.join(r['encoded_words'])[hit['right_start']:hit['right_start']+hit['length']]
        mapping={}
        for a,b in zip(selected,greek,strict=True):
            if a in mapping and mapping[a]!=b:raise ValueError('Nonfunctional reported substitution')
            mapping[a]=b
        if len(set(mapping.values()))!=len(mapping):raise ValueError('Noninjective reported substitution')
        d=len(mapping)
        indices=math.ceil(math.log2(max(1,result['left_oriented_starts'])))+math.ceil(math.log2(max(1,result['right_starts'])))+6
        bits=sum(math.log2(24-i) for i in range(d))
        row=dict(hit,left_id=l['id'],right_id=r['id'],
            source_letters_native=''.join(HEBREW[ord(c)-65] for c in native),
            source_letters_in_match_order=''.join(HEBREW[ord(c)-65] for c in selected),
            greek_letters=''.join(GREEK[ord(c)-65] for c in greek),
            mapping={HEBREW[ord(a)-65]:GREEK[ord(b)-65] for a,b in sorted(mapping.items())},
            distinct_source_symbols=d,ideal_partial_mapping_bits=bits,position_and_length_bits=indices,
            ideal_conditional_description_bits=indices+bits)
        if 'letter_slots' in l:
            row.update(scroll=l['scroll'],fragment=l['fragment'],line=l['line'],reference=l['reference'],
                letter_slots=l['letter_slots'][hit['left_start']:hit['left_end']],
                photographic_collation=False,chronology_verified_for_this_island=False)
        detailed.append(row)
    return detailed


def report_record(root,name,report,kind,payload):
    path=root/f'reports/{name}.json';write_json(path,report)
    sha=digest(path.read_bytes());write_json(root/f'reports/archive/{name}.{sha[:12]}.json',report)
    append(root/'registry/events.jsonl',kind,dict(report_sha256=sha,**payload))
    return sha


def run(root=ROOT):
    integrity=verify(root)
    family_path=root/'protocol/local-substitution-v1.json';cal_path=root/'protocol/local-calibration-v1.json'
    family=json.loads(family_path.read_text());cal=json.loads(cal_path.read_text())
    if (family['minimum_length'],family['maximum_length'],family['directions'])!=(12,64,[1,-1]):
        raise ValueError('Protocol differs from this calibrated workflow')
    binary,engine=build_engine(root)
    metadata=dict(family_sha256=digest(family_path.read_bytes()),calibration_protocol_sha256=digest(cal_path.read_bytes()),
        code_snapshot=snapshot_code(root),native=engine,source_integrity=integrity,
        runtime=dict(python=sys.version,platform=platform.platform(),unicode=unicodedata.unidata_version),
        confirmation=False,independent_replication=False)
    controls(root);data=json.loads((root/'data/derived/controls.json').read_text())
    append(root/'registry/events.jsonl','local_calibration_started',dict(id='CAL-004',**metadata))
    calibration=calibrate(root,binary,family,cal,data)
    cal_sha=report_record(root,'local-calibration-v1',dict(metadata=metadata,protocol=cal,**calibration),
        'local_calibration_finished',dict(id='CAL-004',gate_pass=calibration['calibration_gate_pass']))
    if not calibration['calibration_gate_pass']:
        return dict(calibration_gate_pass=False,target_exploration_executed=False)
    ancient,provenance=dss_units(root,family)
    swete,swete_audit=audit_translation(root)
    human_left,human_right=human_units(data)
    inputs=[('berakhot_xenophon',human_left,human_right),('dss_swete',ancient,greek_verses(swete))]
    human=[]
    def scan_pair(name,left,right):
        file=root/f'data/derived/local/{name}.txt';save_input(file,left,right)
        metadata_path=root/f'data/derived/local/{name}-units.json'
        write_json(metadata_path,dict(left=left,right=right))
        observed=native_scan(binary,file,12,64,family['full_reference_draws_per_model'],family['full_seeds'][name])
        refs=summarize_references(observed)
        matches=contextualize(observed,left,right)
        result=dict(name=name,input_sha256=digest(file.read_bytes()),unit_metadata_sha256=digest(metadata_path.read_bytes()),
            left_units=len(left),right_units=len(right),left_letters=sum(len(l['encoded']) for l in left),
            right_letters=sum(sum(map(len,r['encoded_words'])) for r in right),
            **observed,references=refs,maximum_details=matches,censored_at_cap=observed['maximum']==64,
            candidate_screen_pass=observed['maximum']>=24 and all(r['p']<=.01 for r in refs.values()))
        print(name,'maximum',observed['maximum'],'p',{m:v['p'] for m,v in refs.items()},flush=True)
        return result
    for name,left,right in inputs:human.append(scan_pair(name,left,right))
    human_sha=report_record(root,'local-human-controls-v1',dict(metadata=metadata,witness_provenance=provenance,
        translation_manifest=swete_audit['verified'],results=human),'local_human_controls_finished',dict(family='FAM-002',pairs=2))
    nt=greek_verses([v for book in NT for v in sbl(root/f'data/raw/sblgnt/data/sblgnt/xml/{book}.xml')[0]])
    append(root/'registry/events.jsonl','target_exploration_started',dict(id='EXP-002',family='FAM-002',
        family_sha256=metadata['family_sha256'],calibration_report_sha256=cal_sha,
        human_controls_report_sha256=human_sha,witness_provenance=provenance,
        enumerated_rule_count=None,rule_count_note='Implicit partial bijections and all local starts; exact start counts recorded after scan'))
    target=scan_pair('dss_nt',ancient,nt)
    cost=dict(grammar_bytes=len(family_path.read_bytes()),decoder_cpp_bytes=len((root/'native/local_match.cpp').read_bytes()),
        orchestrator_python_bytes=len((root/'biblelab/local_search.py').read_bytes()),
        normalization_bytes=len((root/'biblelab/letters.py').read_bytes()),
        calibration_and_selection_protocol_bytes=len(cal_path.read_bytes()),
        source_manifest_bytes=len((root/'data/sources.lock.json').read_bytes()),
        note='Ideal conditional map and position bits do not include these shared dependencies; no absolute-complexity or origin probability claim')
    sha=report_record(root,'local-exploration-v1',dict(id='EXP-002',family='FAM-002',metadata=metadata,
        calibration_report_sha256=cal_sha,human_controls_report_sha256=human_sha,witness_provenance=provenance,
        description_cost=cost,**target),'target_exploration_finished',dict(id='EXP-002',family='FAM-002',
        start_pairs=target['start_pairs'],equal_seed_pairs=target['equal_seed_pairs'],maximum=target['maximum'],
        p_values={m:v['p'] for m,v in target['references'].items()},candidate_screen_pass=target['candidate_screen_pass'],confirmations=0))
    return dict(calibration_gate_pass=True,target_maximum=target['maximum'],
        p_values={m:v['p'] for m,v in target['references'].items()},candidate_screen_pass=target['candidate_screen_pass'],
        confirmations=0,report_sha256=sha)
