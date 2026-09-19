"""FAM-006 reset-at-window recurrence and prospective CAL-012 calibration."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import random
import shutil
import subprocess
import sys
from .sources import ROOT,digest,verify,write_json
from .registry import canonical,append,read_events,snapshot_code
from .contextual import base_input,null_units,read_input,summarize
from .shared_search import save_input,reference_summary,null_diagnostics
from .shared_full import input_bytes
from .local_search import report_record

CO=(-2,-1,1,2)


def decode(rule):
    assert 0<=rule<768
    return dict(rule_id=rule,direction=1 if rule<384 else -1,a=CO[(rule//96)%4],b=CO[(rule//24)%4],c=rule%24,initial_state=0)


def predict(oriented,rule):
    p=decode(rule);state=0;out=[]
    for letter in oriented:
        rank=ord(letter)-65
        if not 0<=rank<22:raise ValueError('Hebrew rank outside0..21')
        state=(p['a']*rank+p['b']*state+p['c'])%24;out.append(chr(65+state))
    return ''.join(out)


def build_engine(root=ROOT,oracle=False):
    name='stateful_oracle' if oracle else 'stateful_match'
    names=[name+'.cpp','short_programs_oracle.cpp'] if oracle else [name+'.cpp','contextual_match.cpp','local_match.cpp']
    sources={n:digest((root/'native'/n).read_bytes()) for n in names};compiler=shutil.which('clang++')
    if not compiler:raise RuntimeError('C++17 compiler unavailable')
    identity=dict(sources=sources,compiler=compiler,compiler_version=subprocess.check_output([compiler,'--version'],text=True),
        flags=['-std=c++17','-O3','-Wall','-Wextra','-pedantic'])
    folder=root/'tmp/native';folder.mkdir(parents=True,exist_ok=True);binary=folder/name;receipt=folder/f'{name}.build.json'
    previous=json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(previous.get(k)!=v for k,v in identity.items()) or previous.get('binary_sha256')!=digest(binary.read_bytes()):
        process=subprocess.run([compiler,*identity['flags'],str(root/'native'/f'{name}.cpp'),'-o',str(binary)],capture_output=True,text=True,check=True)
        write_json(receipt,dict(identity,binary_sha256=digest(binary.read_bytes()),compiler_stderr=process.stderr))
    archive=root/'registry/native'/digest(canonical(sources));archive.mkdir(parents=True,exist_ok=True)
    for n in names:(archive/n).write_bytes((root/'native'/n).read_bytes())
    return binary,json.loads(receipt.read_text())


def scan(binary,path,draws=0,seed=0,minimum=8,cap=32):
    raw=path.with_suffix('.native.json')
    with raw.open('w') as stream:
        subprocess.run([str(binary),str(path),str(minimum),str(cap),str(draws),str(seed)],stdout=stream,text=True,check=True)
    return json.loads(raw.read_text())


def validate(result,left,right,minimum=8,cap=32):
    scores=result['rule_scores'];assert len(scores)==768 and all(s==0 or minimum<=s<=cap for s in scores)
    best=max(scores);assert result['score']==best
    assert result['maximizing_rule_ids']==[i for i,s in enumerate(scores) if s==best and s>0]==[w['rule_id'] for w in result['witnesses']]
    ls=2*sum(max(0,sum(map(len,u['words']))-minimum+1) for u in left);rs=sum(max(0,sum(map(len,u['words']))-minimum+1) for u in right)
    assert [result[k] for k in ('left_oriented_starts','indexed_source_starts','right_starts','right_seed_queries','start_pairs','formal_rule_start_pairs')]==[ls,ls*16,rs,4*rs,ls*rs,ls*rs*384]
    assert set(result['reference_scores'])=={'words','word_types'}
    for witness in result['witnesses']:
        p=decode(witness['rule_id']);assert all(witness[k]==v for k,v in p.items());hits=witness['hits'];assert len(hits)==3
        assert len({left[h['left_unit']]['group'] for h in hits})==len({right[h['right_unit']]['group'] for h in hits})==3
        for h in hits:
            source=''.join(left[h['left_unit']]['words']);K=h['length'];assert K==best and h['source_length']==K and h['direction']==p['direction']
            start=h['left_oriented_start'] if p['direction']==1 else len(source)-h['left_oriented_start']-K
            assert h['left_start']==start and h['left_end']==start+K and 0<=start<start+K<=len(source)
            target=''.join(right[h['right_unit']]['words'])[h['right_start']:h['right_start']+K]
            assert len(target)==K and predict(source[start:start+K][::p['direction']],p['rule_id'])==target


def assignments(left,right,spec):
    def first(side,length):
        used=set();out=[]
        for i,u in enumerate(side):
            if sum(map(len,u['words']))>=length and u['group'] not in used:out.append(i);used.add(u['group'])
            if len(out)==3:return out
        raise ValueError('Fewer than three eligible groups')
    coords=[dict(left_unit=l,left_oriented_start=0,right_unit=r,right_start=16) for l,r in zip(first(left,32),first(right,48),strict=True)]
    rng=random.Random(spec['rule_seed']);forward=rng.sample(range(384),10);reverse=rng.sample(range(384,768),10)
    rules=[r for pair in zip(forward,reverse,strict=True) for r in pair]
    return [dict(trial=i,**decode(rule),coordinates=coords,seed=spec['reference_seed_base']+i) for i,rule in enumerate(rules)]


def plant(left,right,plan,length):
    modified=[dict(u,words=list(u['words'])) for u in right]
    assert len({left[c['left_unit']]['group'] for c in plan['coordinates']})==len({right[c['right_unit']]['group'] for c in plan['coordinates']})==3
    for coord in plan['coordinates']:
        l,ls,r,rs=(coord[n] for n in ('left_unit','left_oriented_start','right_unit','right_start'))
        source=''.join(left[l]['words'])[::plan['direction']][ls:ls+length];assert len(source)==length
        prediction=predict(source,plan['rule_id']);original=''.join(right[r]['words']);assert rs+length<=len(original)
        changed=original[:rs]+prediction+original[rs+length:];offset=0;words=[]
        for w in right[r]['words']:words.append(changed[offset:offset+len(w)]);offset+=len(w)
        assert offset==len(changed) and list(map(len,words))==list(map(len,right[r]['words']))
        modified[r]['words']=words
    return modified


def covers(result,plan,length):
    rows=[w for w in result['witnesses'] if w['rule_id']==plan['rule_id']]
    if not rows:return False
    # An earlier start has another reset state; simple geometric overlap is not
    # sufficient to identify this planted recurrence occurrence.
    return all(any(h['left_unit']==c['left_unit'] and h['right_unit']==c['right_unit']
        and h['left_oriented_start']==c['left_oriented_start'] and h['right_start']==c['right_start']
        and h['length']>=length for h in rows[0]['hits']) for c in plan['coordinates'])


def execute(root,binary,path,left,right,draws,seed,identity):
    raw=input_bytes(left,right);key=digest(canonical(dict(identity,input_sha256=digest(raw),draws=draws,seed=seed,minimum=8,cap=32)))
    receipt=path.with_suffix('.receipt.json')
    if receipt.exists():
        envelope=json.loads(receipt.read_text());record=envelope['record']
        assert envelope['sha256']==digest(canonical(record)) and record['execution_id']==key and path.read_bytes()==raw
        assert record['input_sha256']==digest(raw)
        for entry in record['reference_samples'].values():assert digest((root/entry['path']).read_bytes())==entry['sha256']
        validate(record['result'],left,right)
        assert record['references']==json.loads(json.dumps(reference_summary(record['result'])))
        return record
    save_input(path,left,right);result=scan(binary,path,draws,seed);validate(result,left,right);samples={}
    for mode in ('words','word_types'):
        if not draws:continue
        for label,i in (('first',0),('last',-1)):
            sample=path.with_name(path.name+f'.{mode}.{label}.txt')
            samples[f'{mode}_{label}']=dict(path=str(sample.relative_to(root)),sha256=digest(sample.read_bytes()),score=result['reference_scores'][mode][i],mode=mode)
    record=dict(execution_id=key,input_path=str(path.relative_to(root)),input_sha256=digest(raw),result=result,
        references=json.loads(json.dumps(reference_summary(result))),reference_samples=samples)
    tmp=receipt.with_suffix('.tmp');write_json(tmp,dict(sha256=digest(canonical(record)),record=record));tmp.replace(receipt)
    append(root/'registry/events.jsonl','stateful_calibration_input_completed',dict(id='CAL-012',receipt_path=str(receipt.relative_to(root)),
        receipt_sha256=digest(receipt.read_bytes()),new_target_explorations=0))
    return record


def _run(root,stage):
    family_path=root/'protocol/stateful-v1.json';spec_path=root/'protocol/stateful-calibration-v1.json'
    family=json.loads(family_path.read_text());spec=json.loads(spec_path.read_text());events=read_events(root/'registry/events.jsonl')
    for p in (family_path,spec_path):assert any(e['kind']=='protocol_frozen' and e['payload'].get('sha256')==digest(p.read_bytes()) for e in events)
    assert (family['family_size'],family['minimum_length'],family['maximum_length'],family['initial_state'])==(768,8,32,0)
    binary,native=build_engine(root);left,right,base=base_input(root);assert base['input_sha256']==spec['base_input_sha256']
    identity=dict(family_sha256=digest(family_path.read_bytes()),protocol_sha256=digest(spec_path.read_bytes()),
        base_input_sha256=base['input_sha256'],native_binary_sha256=native['binary_sha256'],
        code_sources={n:digest((root/'biblelab'/n).read_bytes()) for n in ('stateful.py','contextual.py','shared_search.py','shared_full.py','statistics.py')})
    metadata=dict(identity=identity,native=native,base=base,source_integrity=verify(root),code_snapshot=snapshot_code(root),python_version=sys.version)
    append(root/'registry/events.jsonl','stateful_calibration_started',dict(id='CAL-012',stage=stage,metadata=metadata,new_target_explorations=0))
    folder=root/'data/derived/stateful';folder.mkdir(parents=True,exist_ok=True)
    a,b=null_units(left,right);draws=spec['null_trials_per_model']*(1+spec['references_per_null_trial'])
    core=execute(root,binary,folder/'binary-null.txt',a,b,draws,spec['null_seed'],identity)
    diagnostics={m:null_diagnostics(v,spec) for m,v in core['result']['reference_scores'].items()}
    gate=all(not d['false_positive_alarm'] and d['distinct_scores']>=2 for d in diagnostics.values())
    null=dict(id='CAL-012',family='FAM-006',stage='null',protocol=spec,metadata=metadata,record=core,
        diagnostics=diagnostics,null_gate_pass=gate,independent_scientific_replication=False,new_target_explorations=0)
    null_path=root/'reports/stateful-null-v1.json'
    if null_path.exists():
        previous=json.loads(null_path.read_text());assert previous['metadata']['identity']==identity
        assert previous['record']==core and previous['diagnostics']==json.loads(json.dumps(diagnostics)) and previous['null_gate_pass']==gate
        null_sha=digest(null_path.read_bytes())
    else:null_sha=report_record(root,'stateful-null-v1',null,'stateful_null_finished',dict(id='CAL-012',gate_pass=gate,new_target_explorations=0))
    print('CAL-012 null',{m:dict(rejections=d['rejections'],distinct_scores=d['distinct_scores']) for m,d in diagnostics.items()},'gate',gate,flush=True)
    if not gate or stage=='null':return dict(null_gate_pass=gate,null_report_sha256=null_sha,power_executed=False)
    plans=assignments(left,right,spec);plan_path=folder/'assignments.json';data=dict(identity=identity,assignments=plans)
    if plan_path.exists():assert json.loads(plan_path.read_text())==data
    else:write_json(plan_path,data)
    metadata['assignment_sha256']=digest(plan_path.read_bytes())
    append(root/'registry/events.jsonl','stateful_assignments_fixed',dict(id='CAL-012',path=str(plan_path.relative_to(root)),sha256=metadata['assignment_sha256'],new_target_explorations=0))
    def job(K,plan):
        changed=plant(left,right,plan,K);record=execute(root,binary,folder/f'length-{K}-trial-{plan["trial"]:02d}.txt',left,changed,
            spec['references_per_model'],plan['seed'],identity)
        result=record['result'];return dict(length=K,assignment=plan,literal_plants_valid=True,
            planted_rule_reaches_length=result['rule_scores'][plan['rule_id']]>=K,
            planted_rule_maximizing=plan['rule_id'] in result['maximizing_rule_ids'],maximizing_witness_covers_implants=covers(result,plan,K),
            detection=result['score']>=K and all(v['p']<=.01 for v in record['references'].values()),**record)
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(job,K,p) for K in spec['lengths'] for p in plans]
        for future in futures:
            row=future.result();rows.append(row)
            print('CAL-012 implant',row['length'],row['assignment']['trial'],'score',row['result']['score'],
                'p',{m:v['p'] for m,v in row['references'].items()},flush=True)
    conditions=[dict(length=K,diagnostic_only=K==8,**summarize([r for r in rows if r['length']==K]),
        injections=[r for r in rows if r['length']==K]) for K in spec['lengths']]
    repeats=[]
    for i,(name,source,word) in enumerate([('periodic','A'+'B'*7+('R'+'B'*7)*3,'ABCDEFGH'),('constant','A'*32,'A'*8)]):
        a=[dict(group=j,words=[source]) for j in range(3)];b=[dict(group=j,words=[word]*4) for j in range(3)]
        record=execute(root,binary,folder/f'{name}.txt',a,b,199,2026113000+i,identity)
        ok=record['result']['score']==32 and all(v['p']==1 for v in record['references'].values())
        if name=='constant':ok=ok and record['result']['maximizing_rule_ids']==list(range(0,768,24))
        repeats.append(dict(name=name,gate_pass=ok,**record))
    gate=all(c['gate_pass'] for c in conditions if not c['diagnostic_only']) and all(r['gate_pass'] for r in repeats)
    gate=gate and all(r['literal_plants_valid'] and r['planted_rule_reaches_length'] for r in rows)
    report=dict(id='CAL-012',family='FAM-006',protocol=spec,metadata=metadata,null_report_sha256=null_sha,assignments=plans,
        conditions=conditions,repetition_controls=repeats,calibration_gate_pass=gate,paired_trials=20,independent_backgrounds=1,
        independent_scientific_replication=False,new_target_explorations=0)
    sha=report_record(root,'stateful-calibration-v1',report,'stateful_calibration_finished',dict(id='CAL-012',gate_pass=gate,new_target_explorations=0))
    return dict(calibration_gate_pass=gate,report_sha256=sha,detections_by_length={c['length']:c['detections'] for c in conditions})


def run(root=ROOT,stage='all'):
    assert stage in ('null','all');(root/'tmp').mkdir(exist_ok=True)
    with (root/'tmp/stateful-calibration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        completed=root/'reports/stateful-calibration-v1.json'
        if completed.exists():
            r=json.loads(completed.read_text());identity=r['metadata']['identity']
            assert identity['protocol_sha256']==digest((root/'protocol/stateful-calibration-v1.json').read_bytes())
            for n,sha in identity['code_sources'].items():assert digest((root/'biblelab'/n).read_bytes())==sha
            return dict(existing_report=str(completed.relative_to(root)),report_sha256=digest(completed.read_bytes()),new_target_explorations=0)
        try:return _run(root,stage)
        except Exception as exc:
            append(root/'registry/events.jsonl','stateful_calibration_failed',dict(id='CAL-012',stage=stage,error=repr(exc),
                completed_calibration_claim=False,new_target_explorations=0))
            raise


if __name__=='__main__':print(json.dumps(run(stage=sys.argv[1] if len(sys.argv)>1 else 'all'),indent=2))
