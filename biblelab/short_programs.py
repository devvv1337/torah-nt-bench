"""FAM-005 and CAL-011, a finite grammar calibrated without NT input."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import random
import shutil
import subprocess
import sys
from .sources import ROOT,digest,verify,write_json
from .registry import append,canonical,read_events,snapshot_code
from .contextual import base_input,null_units,read_input
from .shared_search import save_input,reference_summary,null_diagnostics
from .shared_full import input_bytes
from .statistics import wilson
from .local_search import report_record

KINDS=('pair','triple','product')
BOUNDS=((0,384,768),(768,2688,4608),(4608,5808,7008))


def decode(rule):
    assert 0<=rule<7008
    base=rule//24;c4=(-2,-1,1,2);c5=(-2,-1,0,1,2)
    if base<32:
        direction=1 if base<16 else -1;local=base%16
        return dict(rule_id=rule,kind='pair',span=2,direction=direction,linear=[c4[local//4],c4[local%4]],product=0,intercept=rule%24)
    if base<192:
        local=base-32;direction=1 if local<80 else -1;local%=80
        return dict(rule_id=rule,kind='triple',span=3,direction=direction,
            linear=[c4[local//20],c5[(local%20)//4],c4[local%4]],product=0,intercept=rule%24)
    local=base-192;direction=1 if local<50 else -1;local%=50
    return dict(rule_id=rule,kind='product',span=2,direction=direction,
        linear=[c5[(local%25)//5],c5[local%5]],product=(-1,1)[local//25],intercept=rule%24)


def predict(oriented,rule):
    p=decode(rule);ranks=[ord(c)-65 for c in oriented];out=[]
    for i in range(len(ranks)-p['span']+1):
        value=p['intercept']+sum(a*ranks[i+j] for j,a in enumerate(p['linear']))
        value+=p['product']*ranks[i]*ranks[i+1];out.append(chr(65+value%24))
    return ''.join(out)


def build_engine(root=ROOT):
    sources={n:digest((root/'native'/n).read_bytes()) for n in ('short_programs.cpp','contextual_match.cpp','local_match.cpp')}
    compiler=shutil.which('clang++')
    if not compiler:raise RuntimeError('C++17 compiler unavailable')
    identity=dict(sources=sources,compiler=compiler,compiler_version=subprocess.check_output([compiler,'--version'],text=True),
        flags=['-std=c++17','-O3','-Wall','-Wextra','-pedantic'])
    folder=root/'tmp/native';folder.mkdir(parents=True,exist_ok=True);binary=folder/'short_programs';receipt=folder/'short-programs-build.json'
    prior=json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(prior.get(k)!=v for k,v in identity.items()) or prior.get('binary_sha256')!=digest(binary.read_bytes()):
        p=subprocess.run([compiler,*identity['flags'],str(root/'native/short_programs.cpp'),'-o',str(binary)],capture_output=True,text=True,check=True)
        write_json(receipt,dict(**identity,binary_sha256=digest(binary.read_bytes()),compiler_stderr=p.stderr))
    archive=root/'registry/native'/digest(canonical(sources));archive.mkdir(parents=True,exist_ok=True)
    for name in sources:(archive/name).write_bytes((root/'native'/name).read_bytes())
    return binary,json.loads(receipt.read_text())


def scan(binary,path,draws,seed,minimum=8,cap=32):
    raw=path.with_suffix('.native.json')
    with raw.open('w') as stream:
        subprocess.run([str(binary),str(path),str(minimum),str(cap),str(draws),str(seed)],stdout=stream,text=True,check=True)
    return json.loads(raw.read_text())


def validate(result,left,right):
    scores=result['rule_scores'];assert len(scores)==7008 and max(scores)==result['score']
    ids=[i for i,s in enumerate(scores) if s==result['score'] and s>0]
    assert ids==result['maximizing_rule_ids']==[w['program']['rule_id'] for w in result['witnesses']]
    expected={k:max(scores[a:c]) for k,(a,b,c) in zip(KINDS,BOUNDS)}
    assert expected==result['opcode_maxima'] and max(expected.values())==result['score']
    for mode,values in result['reference_scores'].items():
        sub=result['reference_opcode_maxima'][mode];assert set(sub)==set(KINDS)
        assert all(len(v)==len(values) for v in sub.values())
        assert values==[max(sub[k][i] for k in KINDS) for i in range(len(values))]
    for witness in result['witnesses']:
        p=witness['program'];assert p==decode(p['rule_id']);hits=witness['hits'];assert len(hits)==3
        assert len({left[h['left_unit']]['group'] for h in hits})==3
        assert len({right[h['right_unit']]['group'] for h in hits})==3
        for h in hits:
            raw=''.join(left[h['left_unit']]['words']);K=h['length'];consumed=K+p['span']-1
            assert K==result['score'] and h['source_length']==consumed and h['direction']==p['direction']
            start=h['left_oriented_start'] if p['direction']==1 else len(raw)-h['left_oriented_start']-consumed
            assert h['left_start']==start and h['left_end']==start+consumed and 0<=start<start+consumed<=len(raw)
            text=raw[start:start+consumed][::p['direction']]
            target=''.join(right[h['right_unit']]['words'])[h['right_start']:h['right_start']+K]
            assert len(target)==K and predict(text,p['rule_id'])==target


def assignments(left,right,spec):
    def first(side,length):
        chosen=[];groups=set()
        for i,u in enumerate(side):
            if sum(map(len,u['words']))>=length and u['group'] not in groups:chosen.append(i);groups.add(u['group'])
            if len(chosen)==3:return chosen
        raise ValueError('Insufficient fixed-coordinate groups')
    li=first(left,34);ri=first(right,48)
    coords=[dict(left_unit=l,left_oriented_start=0,right_unit=r,right_start=16) for l,r in zip(li,ri,strict=True)]
    rng=random.Random(spec['rule_seed']);programs=[]
    for a,b,c in BOUNDS:
        forward=rng.sample(range(a,b),10);reverse=rng.sample(range(b,c),10)
        programs.extend(x for pair in zip(forward,reverse,strict=True) for x in pair)
    return [dict(trial=i,program=decode(rule),coordinates=coords,seed=spec['reference_seed_base']+i) for i,rule in enumerate(programs)]


def plant(left,right,assignment,K):
    p=assignment['program'];modified=[dict(u,words=list(u['words'])) for u in right]
    assert len({left[c['left_unit']]['group'] for c in assignment['coordinates']})==3
    assert len({right[c['right_unit']]['group'] for c in assignment['coordinates']})==3
    for c in assignment['coordinates']:
        l,ls,r,rs=(c[n] for n in ('left_unit','left_oriented_start','right_unit','right_start'))
        text=''.join(left[l]['words'])[::p['direction']][ls:ls+K+p['span']-1]
        assert len(text)==K+p['span']-1
        prediction=predict(text,p['rule_id']);raw=''.join(right[r]['words']);assert 0<=rs and rs+K<=len(raw)
        changed=raw[:rs]+prediction+raw[rs+K:];words=[];offset=0
        for w in right[r]['words']:words.append(changed[offset:offset+len(w)]);offset+=len(w)
        assert offset==len(changed) and list(map(len,words))==list(map(len,right[r]['words']))
        modified[r]['words']=words
    return modified


def covers(result,assignment,K):
    rule=assignment['program']['rule_id'];w=next((x for x in result['witnesses'] if x['program']['rule_id']==rule),None)
    if w is None:return False
    return all(any(h['left_unit']==c['left_unit'] and h['right_unit']==c['right_unit']
        and h['left_oriented_start']<=c['left_oriented_start']
        and h['left_oriented_start']+h['length']>=c['left_oriented_start']+K
        and c['left_oriented_start']-h['left_oriented_start']==c['right_start']-h['right_start']
        for h in w['hits']) for c in assignment['coordinates'])


def execute(root,binary,path,left,right,draws,seed,identity):
    raw=input_bytes(left,right);key=digest(canonical(dict(identity,input_sha256=digest(raw),draws=draws,seed=seed)))
    receipt=path.with_suffix('.receipt.json')
    if receipt.exists():
        envelope=json.loads(receipt.read_text());record=envelope['record']
        assert envelope['sha256']==digest(canonical(record)) and record['execution_id']==key
        assert path.read_bytes()==raw and record['input_sha256']==digest(raw)
        for entry in record['reference_samples'].values():assert digest((root/entry['path']).read_bytes())==entry['sha256']
        validate(record['result'],left,right)
        assert record['references']==json.loads(json.dumps(reference_summary(record['result'])))
        return record
    save_input(path,left,right);result=scan(binary,path,draws,seed);validate(result,left,right);samples={}
    for mode in ('words','word_types'):
        for label,index in [('first',0),('last',-1)]:
            sample=path.with_name(path.name+f'.{mode}.{label}.txt')
            samples[f'{mode}_{label}']=dict(path=str(sample.relative_to(root)),sha256=digest(sample.read_bytes()),
                score=result['reference_scores'][mode][index],opcode_maxima={k:result['reference_opcode_maxima'][mode][k][index] for k in KINDS},mode=mode)
    record=dict(execution_id=key,input_path=str(path.relative_to(root)),input_sha256=digest(raw),
        result=result,references=reference_summary(result),reference_samples=samples)
    temporary=receipt.with_suffix('.tmp');write_json(temporary,dict(sha256=digest(canonical(record)),record=record));temporary.replace(receipt)
    append(root/'registry/events.jsonl','program_calibration_input_completed',dict(id='CAL-011',
        receipt_path=str(receipt.relative_to(root)),receipt_sha256=digest(receipt.read_bytes()),new_target_explorations=0))
    return record


def summarize(rows):
    detected=sum(r['detection'] for r in rows);directions={}
    for direction in (1,-1):
        chosen=[r for r in rows if r['assignment']['program']['direction']==direction];n=sum(r['detection'] for r in chosen)
        directions[str(direction)]=dict(trials=len(chosen),detections=n,wilson95=wilson(n,len(chosen)))
    return dict(trials=len(rows),detections=detected,wilson95=wilson(detected,len(rows)),directions=directions,
        gate_pass=detected>=18 and all(x['detections']>=9 for x in directions.values())
            and all(r['planted_program_reaches_length'] and r['literal_plants_valid'] for r in rows),
        score_histogram=dict(sorted(Counter(r['result']['score'] for r in rows).items())),
        planted_program_maximizing=sum(r['planted_program_maximizing'] for r in rows),
        maximizing_witnesses_covering_plants=sum(r['maximizing_witness_covers_implants'] for r in rows))


def _run(root,stage):
    family_path=root/'protocol/short-programs-v1.json';spec_path=root/'protocol/short-programs-calibration-v1.json'
    family=json.loads(family_path.read_text());spec=json.loads(spec_path.read_text());events=read_events(root/'registry/events.jsonl')
    for p in (family_path,spec_path):assert any(e['kind']=='protocol_frozen' and e['payload'].get('sha256')==digest(p.read_bytes()) for e in events)
    assert (family['family_size'],family['minimum_length'],family['maximum_length'])==(7008,8,32)
    binary,native=build_engine(root);left,right,base=base_input(root)
    identity=dict(family_sha256=digest(family_path.read_bytes()),protocol_sha256=digest(spec_path.read_bytes()),
        native_binary_sha256=native['binary_sha256'],orchestrator_sha256=digest((root/'biblelab/short_programs.py').read_bytes()),base_input_sha256=base['input_sha256'])
    metadata=dict(identity=identity,native=native,base=base,source_integrity=verify(root),code_snapshot=snapshot_code(root),python_version=sys.version)
    append(root/'registry/events.jsonl','program_calibration_started',dict(id='CAL-011',stage=stage,metadata=metadata,new_target_explorations=0))
    folder=root/'data/derived/short-programs';folder.mkdir(parents=True,exist_ok=True)
    a,b=null_units(left,right);draws=spec['null_trials_per_model']*(1+spec['references_per_null_trial'])
    null=execute(root,binary,folder/'binary-null.txt',a,b,draws,spec['null_seed'],identity)
    diagnostics={m:null_diagnostics(v,spec) for m,v in null['result']['reference_scores'].items()}
    gate=all(not d['false_positive_alarm'] and d['distinct_scores']>=2 for d in diagnostics.values())
    null_path=root/'reports/short-programs-null-v1.json'
    if null_path.exists():
        previous=json.loads(null_path.read_text());assert previous['metadata']['identity']==identity
        assert previous['record']==json.loads(json.dumps(null)) and previous['diagnostics']==json.loads(json.dumps(diagnostics))
        assert previous['null_gate_pass']==gate;null_sha=digest(null_path.read_bytes())
    else:
        report=dict(id='CAL-011',family='FAM-005',stage='null',metadata=metadata,protocol=spec,record=null,diagnostics=diagnostics,
            opcode_histograms={m:{k:dict(sorted(Counter(v).items())) for k,v in rows.items()} for m,rows in null['result']['reference_opcode_maxima'].items()},
            null_gate_pass=gate,new_target_explorations=0,independent_scientific_replication=False)
        null_sha=report_record(root,'short-programs-null-v1',report,'program_null_finished',dict(id='CAL-011',gate_pass=gate,new_target_explorations=0))
    print('CAL-011 null', {m:dict(rejections=d['rejections'],distinct_scores=d['distinct_scores']) for m,d in diagnostics.items()},'gate',gate,flush=True)
    if not gate or stage=='null':return dict(null_gate_pass=gate,null_report_sha256=null_sha,power_executed=False)
    plans=assignments(left,right,spec);plan_path=folder/'assignments.json';plan_data=dict(identity=identity,assignments=plans)
    if plan_path.exists():assert json.loads(plan_path.read_text())==plan_data
    else:write_json(plan_path,plan_data)
    metadata['assignment_sha256']=digest(plan_path.read_bytes())
    append(root/'registry/events.jsonl','program_assignments_fixed',dict(id='CAL-011',path=str(plan_path.relative_to(root)),sha256=metadata['assignment_sha256'],new_target_explorations=0))
    def job(K,assignment):
        changed=plant(left,right,assignment,K);rule=assignment['program']['rule_id']
        core=execute(root,binary,folder/f'length-{K}-trial-{assignment["trial"]:02d}.txt',left,changed,spec['references_per_model'],assignment['seed'],identity)
        result=core['result'];reached=result['rule_scores'][rule]>=K
        return dict(length=K,assignment=assignment,literal_plants_valid=True,planted_program_reaches_length=reached,
            planted_program_maximizing=rule in result['maximizing_rule_ids'],maximizing_witness_covers_implants=covers(result,assignment,K),
            detection=result['score']>=K and all(v['p']<=.01 for v in core['references'].values()),**core)
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(job,K,a) for K in spec['lengths'] for a in plans]
        for future in futures:
            row=future.result();records.append(row)
            print('CAL-011',row['length'],row['assignment']['trial'],row['assignment']['program']['kind'],
                'score',row['result']['score'],'p',{m:v['p'] for m,v in row['references'].items()},flush=True)
    conditions=[]
    for K in spec['lengths']:
        for kind in KINDS:
            rows=[r for r in records if r['length']==K and r['assignment']['program']['kind']==kind]
            conditions.append(dict(length=K,kind=kind,diagnostic_only=K==8,**summarize(rows),injections=rows))
    repeats=[]
    for i,(name,source,word) in enumerate([('periodic','ABCDEFGH'*4+'AB','BDFHJLNH'),('constant','A'*34,'A'*8)]):
        a=[dict(group=j,words=[source]) for j in range(3)];b=[dict(group=j,words=[word]*4) for j in range(3)]
        r=execute(root,binary,folder/f'{name}.txt',a,b,199,2026101000+i,identity)
        ok=r['result']['score']==32 and all(v['p']==1 for v in r['references'].values())
        if name=='constant':ok=ok and r['result']['maximizing_rule_ids']==list(range(0,7008,24))
        repeats.append(dict(name=name,gate_pass=ok,**r))
    gate=all(c['gate_pass'] for c in conditions if not c['diagnostic_only']) and all(r['gate_pass'] for r in repeats)
    gate=gate and all(r['literal_plants_valid'] and r['planted_program_reaches_length'] for r in records)
    report=dict(id='CAL-011',family='FAM-005',protocol=spec,metadata=metadata,null_report_sha256=null_sha,assignments=plans,
        conditions=conditions,repetition_controls=repeats,calibration_gate_pass=gate,independent_backgrounds=1,paired_programs=60,
        new_target_explorations=0,independent_scientific_replication=False)
    sha=report_record(root,'short-programs-calibration-v1',report,'program_calibration_finished',dict(id='CAL-011',gate_pass=gate,new_target_explorations=0))
    return dict(calibration_gate_pass=gate,report_sha256=sha,detections={f'{c["kind"]}-{c["length"]}':c['detections'] for c in conditions})


def run(root=ROOT,stage='all'):
    assert stage in ('null','all')
    with (root/'tmp/short-programs-calibration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:return _run(root,stage)
        except Exception as exc:
            append(root/'registry/events.jsonl','program_calibration_failed',dict(id='CAL-011',stage=stage,error=repr(exc),new_target_explorations=0,completed_calibration_claim=False))
            raise


if __name__=='__main__':print(json.dumps(run(stage=sys.argv[1] if len(sys.argv)>1 else 'all'),indent=2))
