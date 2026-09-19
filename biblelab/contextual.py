"""FAM-004 software and CAL-010; no unmodified Torah-NT experiment."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import platform
import random
import shutil
import subprocess
import sys

from .sources import ROOT, digest, write_json, verify
from .registry import append, canonical, snapshot_code
from .local_search import report_record
from .shared_search import save_input, reference_summary, null_diagnostics
from .shared_full import input_bytes
from .statistics import wilson

COEFFICIENTS = (-2, -1, 1, 2)


def decode(rule):
    assert 0 <= rule < 768
    return dict(rule_id=rule, direction=1 if rule < 384 else -1,
                a=COEFFICIENTS[(rule//96)%4], b=COEFFICIENTS[(rule//24)%4], c=rule%24)


def predict(text, rule):
    r = decode(rule)
    return ''.join(chr(65+(r['a']*(ord(x)-65)+r['b']*(ord(y)-65)+r['c'])%24)
                   for x,y in zip(text,text[1:]))


def read_input(path):
    lines = path.read_text().splitlines(); nl,nr = map(int,lines[0].split())
    assert len(lines) == 1+nl+nr
    units = []
    for line in lines[1:]:
        group,*words = line.split()
        assert int(group) >= 0 and all('A' <= c <= 'X' for w in words for c in w)
        units.append(dict(group=int(group),words=words))
    assert all('A' <= c <= 'V' for u in units[:nl] for w in u['words'] for c in w)
    return units[:nl],units[nl:]


def build_engine(root=ROOT):
    sources = {n:digest((root/'native'/n).read_bytes()) for n in ('contextual_match.cpp','local_match.cpp')}
    compiler = shutil.which('clang++')
    if not compiler: raise RuntimeError('C++17 compiler unavailable')
    flags = ['-std=c++17','-O3','-Wall','-Wextra','-pedantic']
    identity = dict(sources=sources,compiler=compiler,
        compiler_version=subprocess.check_output([compiler,'--version'],text=True),flags=flags)
    folder = root/'tmp/native'; folder.mkdir(parents=True,exist_ok=True)
    binary = folder/'contextual_match'; receipt = folder/'contextual-build.json'
    previous = json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(previous.get(k)!=v for k,v in identity.items()) or previous.get('binary_sha256')!=digest(binary.read_bytes()):
        p = subprocess.run([compiler,*flags,str(root/'native/contextual_match.cpp'),'-o',str(binary)],capture_output=True,text=True,check=True)
        write_json(receipt,dict(**identity,binary_sha256=digest(binary.read_bytes()),compiler_stderr=p.stderr))
    key = digest(canonical(sources)); archive = root/'registry/native'/key; archive.mkdir(parents=True,exist_ok=True)
    for name in sources: (archive/name).write_bytes((root/'native'/name).read_bytes())
    return binary,json.loads(receipt.read_text())


def scan(binary,path,draws,seed,minimum=8,cap=32):
    process = subprocess.run([str(binary),str(path),str(minimum),str(cap),str(draws),str(seed)],
                             stdout=subprocess.PIPE,text=True,check=True)
    return json.loads(process.stdout)


def validate_witness(result,left,right):
    scores = result['rule_scores']; best = max(scores)
    assert len(scores)==768 and best==result['score']
    ids = [r for r,s in enumerate(scores) if s==best and s>0]
    assert ids == result['maximizing_rule_ids'] == [w['rule_id'] for w in result['witnesses']]
    for witness in result['witnesses']:
        rule = decode(witness['rule_id'])
        assert all(witness[k]==v for k,v in rule.items())
        hits = witness['hits']; assert len(hits)==3
        assert len({left[h['left_unit']]['group'] for h in hits})==3
        assert len({right[h['right_unit']]['group'] for h in hits})==3
        for h in hits:
            raw = ''.join(left[h['left_unit']]['words']); K = h['length']
            assert K==best and h['source_length']==K+1 and h['direction']==rule['direction']
            assert h['left_start']==(h['left_oriented_start'] if rule['direction']==1 else len(raw)-h['left_oriented_start']-K-1)
            assert h['left_end']==h['left_start']+K+1 and 0<=h['left_start']<h['left_end']<=len(raw)
            source = raw[h['left_start']:h['left_end']][::rule['direction']]
            dest = ''.join(right[h['right_unit']]['words'])[h['right_start']:h['right_start']+K]
            assert len(dest)==K and predict(source,witness['rule_id'])==dest


def base_input(root=ROOT):
    path = root/'reports/shared-common-controls-v1.json'
    assert digest(path.read_bytes())=='fbca5a1601678a9a16b261635e00f64db4e5f9f390667e65e628b75f4ec7c0be'
    report = json.loads(path.read_text())
    rows = [r for r in report['results'] if 'Berakhot' in r.get('name','')]
    assert len(rows)==1
    row = rows[0]; inp = root/row['input_path']
    assert digest(inp.read_bytes())==row['input_sha256']
    left,right = read_input(inp)
    assert (len(left),len(right))==(57,2380)
    return left,right,dict(report_sha256=digest(path.read_bytes()),input_path=row['input_path'],input_sha256=row['input_sha256'])


def null_units(left,right):
    sides=[]
    for side in (left,right):
        text=''.join(''.join(u['words']) for u in side)[:1024]; assert len(text)==1024
        text=''.join(chr(65+(ord(c)-65)%2) for c in text)
        sides.append([dict(group=i,words=[text[i*64+j:i*64+j+4] for j in range(0,64,4)]) for i in range(16)])
    return tuple(sides)


def assignments(left,right,spec):
    def first_three(side,size):
        groups=set(); eligible=[]
        for i,u in enumerate(side):
            if sum(map(len,u['words']))>=size and u['group'] not in groups:
                groups.add(u['group']); eligible.append(i)
                if len(eligible)==3: return eligible
        raise ValueError('Fewer than three eligible groups')
    li=first_three(left,33); ri=first_three(right,48)
    coordinates=[dict(left_unit=l,left_oriented_start=0,right_unit=r,right_start=16) for l,r in zip(li,ri,strict=True)]
    rng=random.Random(spec['rule_seed']); forward=rng.sample(range(384),10); backward=rng.sample(range(384,768),10)
    rules=[r for pair in zip(forward,backward,strict=True) for r in pair]
    return [dict(trial=i,**decode(r),coordinates=coordinates,seed=spec['reference_seed_base']+i) for i,r in enumerate(rules)]


def plant(left,right,assignment,length):
    result=[dict(u,words=list(u['words'])) for u in right]
    assert len({left[c['left_unit']]['group'] for c in assignment['coordinates']})==3
    assert len({right[c['right_unit']]['group'] for c in assignment['coordinates']})==3
    for coord in assignment['coordinates']:
        l,ls,r,rs=(coord[k] for k in ('left_unit','left_oriented_start','right_unit','right_start'))
        source=''.join(left[l]['words'])[::assignment['direction']][ls:ls+length+1]
        assert len(source)==length+1
        mapped=predict(source,assignment['rule_id']); original=''.join(right[r]['words'])
        assert rs+length<=len(original)
        altered=original[:rs]+mapped+original[rs+length:]
        words=[]; p=0
        for word in right[r]['words']:
            words.append(altered[p:p+len(word)]); p+=len(word)
        assert p==len(altered) and [len(w) for w in words]==[len(w) for w in right[r]['words']]
        result[r]['words']=words
    return result


def covers(result,assignment,length):
    witness=next((w for w in result['witnesses'] if w['rule_id']==assignment['rule_id']),None)
    if witness is None:return False
    return all(any(h['left_unit']==c['left_unit'] and h['right_unit']==c['right_unit']
        and h['left_oriented_start']<=c['left_oriented_start']
        and h['left_oriented_start']+h['length']>=c['left_oriented_start']+length
        and c['left_oriented_start']-h['left_oriented_start']==c['right_start']-h['right_start']
        for h in witness['hits']) for c in assignment['coordinates'])


def execute(root,binary,path,left,right,draws,seed,identity):
    raw=input_bytes(left,right)
    execution_id=digest(canonical(dict(**identity,input_sha256=digest(raw),draws=draws,seed=seed,minimum=8,cap=32)))
    receipt=path.with_suffix('.receipt.json')
    if receipt.exists():
        envelope=json.loads(receipt.read_text()); record=envelope['record']
        assert envelope['sha256']==digest(canonical(record)) and record['execution_id']==execution_id
        assert path.read_bytes()==raw and record['input_sha256']==digest(raw)
        for entry in record['reference_samples'].values():assert digest((root/entry['path']).read_bytes())==entry['sha256']
        validate_witness(record['result'],left,right)
        assert record['references']==json.loads(json.dumps(reference_summary(record['result'])))
        return record
    save_input(path,left,right); result=scan(binary,path,draws,seed); validate_witness(result,left,right)
    samples={}
    if draws:
        for mode in ('words','word_types'):
            for label,index in [('first',0),('last',-1)]:
                sample=path.with_name(path.name+f'.{mode}.{label}.txt')
                samples[f'{mode}_{label}']=dict(path=str(sample.relative_to(root)),sha256=digest(sample.read_bytes()),
                    score=result['reference_scores'][mode][index],mode=mode)
    record=dict(execution_id=execution_id,input_path=str(path.relative_to(root)),input_sha256=digest(raw),
        reference_samples=samples,result=result,references=reference_summary(result))
    temporary=receipt.with_suffix('.tmp'); write_json(temporary,dict(sha256=digest(canonical(record)),record=record)); temporary.replace(receipt)
    append(root/'registry/events.jsonl','contextual_calibration_input_completed',dict(id='CAL-010',
        receipt_path=str(receipt.relative_to(root)),receipt_sha256=digest(receipt.read_bytes()),new_target_explorations=0))
    return record


def summarize(records):
    n=len(records); detected=sum(r['detection'] for r in records); directions={}
    for direction in (1,-1):
        rows=[r for r in records if r['assignment']['direction']==direction]; d=sum(r['detection'] for r in rows)
        directions[str(direction)]=dict(trials=len(rows),detections=d,wilson95=wilson(d,len(rows)))
    return dict(trials=n,detections=detected,wilson95=wilson(detected,n),directions=directions,
        gate_pass=detected>=18 and all(v['detections']>=9 for v in directions.values())
            and all(r['literal_plants_valid'] and r['planted_rule_reaches_length'] for r in records),
        score_histogram=dict(sorted(Counter(r['result']['score'] for r in records).items())),
        planted_rule_maximizing=sum(r['planted_rule_maximizing'] for r in records),
        maximizing_witnesses_covering_plants=sum(r['maximizing_witness_covers_implants'] for r in records))


def _run(root,stage):
    family_path=root/'protocol/contextual-affine-v1.json'; path=root/'protocol/contextual-calibration-v1.json'
    family=json.loads(family_path.read_text()); spec=json.loads(path.read_text())
    assert (family['minimum_length'],family['maximum_length'],family['family_size'])==(8,32,768)
    binary,native=build_engine(root); left,right,base=base_input(root)
    metadata=dict(family_sha256=digest(family_path.read_bytes()),protocol_sha256=digest(path.read_bytes()),
        native=native,code_snapshot=snapshot_code(root),source_integrity=verify(root),base=base,
        python_version=sys.version,platform=platform.platform())
    identity=dict(protocol_sha256=metadata['protocol_sha256'],family_sha256=metadata['family_sha256'],
                  base_input_sha256=base['input_sha256'],native_binary_sha256=native['binary_sha256'])
    append(root/'registry/events.jsonl','contextual_calibration_started',dict(id='CAL-010',stage=stage,metadata=metadata,new_target_explorations=0))
    folder=root/'data/derived/contextual'; folder.mkdir(parents=True,exist_ok=True)
    a,b=null_units(left,right); draws=spec['null_trials_per_model']*(1+spec['references_per_null_trial'])
    null=execute(root,binary,folder/'binary-null.txt',a,b,draws,spec['null_seed'],identity)
    diagnostics={m:null_diagnostics(v,spec) for m,v in null['result']['reference_scores'].items()}
    gate=all(not v['false_positive_alarm'] and v['distinct_scores']>=2 for v in diagnostics.values())
    report=dict(id='CAL-010',family='FAM-004',stage='null',metadata=metadata,protocol=spec,record=null,
        diagnostics=diagnostics,null_gate_pass=gate,new_target_explorations=0,independent_scientific_replication=False)
    null_sha=report_record(root,'contextual-null-v1',report,'contextual_null_finished',
        dict(id='CAL-010',gate_pass=gate,new_target_explorations=0))
    print('CAL-010 null', {m:dict(rejections=v['rejections'],distinct_scores=v['distinct_scores']) for m,v in diagnostics.items()},'gate',gate,flush=True)
    if not gate or stage=='null':return dict(null_gate_pass=gate,null_report_sha256=null_sha,power_executed=False)
    plans=assignments(left,right,spec); assignment_path=folder/'assignments.json'
    assignment_data=dict(identity=identity,assignments=plans)
    if assignment_path.exists():assert json.loads(assignment_path.read_text())==assignment_data
    else:write_json(assignment_path,assignment_data)
    metadata['assignment_sha256']=digest(assignment_path.read_bytes())
    append(root/'registry/events.jsonl','contextual_assignments_fixed',dict(id='CAL-010',
        path=str(assignment_path.relative_to(root)),sha256=metadata['assignment_sha256'],new_target_explorations=0))
    def job(length,assignment):
        modified=plant(left,right,assignment,length)
        core=execute(root,binary,folder/f'length-{length}-trial-{assignment["trial"]:02d}.txt',left,modified,
                     spec['references_per_model'],assignment['seed'],identity)
        result=core['result']; reached=result['rule_scores'][assignment['rule_id']]>=length
        return dict(length=length,assignment=assignment,literal_plants_valid=True,planted_rule_reaches_length=reached,
            planted_rule_maximizing=assignment['rule_id'] in result['maximizing_rule_ids'],
            maximizing_witness_covers_implants=covers(result,assignment,length),
            detection=result['score']>=length and all(v['p']<=.01 for v in core['references'].values()),**core)
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(job,k,a) for k in spec['lengths'] for a in plans]
        for future in futures:
            r=future.result(); rows.append(r)
            print('CAL-010 implant',r['length'],r['assignment']['trial'],'score',r['result']['score'],
                  'p',{m:v['p'] for m,v in r['references'].items()},flush=True)
    conditions=[dict(length=k,diagnostic_only=k==8,**summarize([r for r in rows if r['length']==k]),
                     injections=[r for r in rows if r['length']==k]) for k in spec['lengths']]
    repeats=[]
    for index,(name,source,word) in enumerate([('periodic','ABCDEFGH'*4+'A','BDFHJLNH'),('constant','A'*33,'A'*8)]):
        a=[dict(group=i,words=[source]) for i in range(3)]; b=[dict(group=i,words=[word]*4) for i in range(3)]
        record=execute(root,binary,folder/f'{name}.txt',a,b,199,2026096000+index,identity)
        ok=record['result']['score']==32 and all(v['p']==1 for v in record['references'].values())
        if name=='constant':ok=ok and len(record['result']['maximizing_rule_ids'])==32
        repeats.append(dict(name=name,gate_pass=ok,**record))
    gate=gate and all(c['gate_pass'] for c in conditions if not c['diagnostic_only']) and all(r['gate_pass'] for r in repeats)
    gate=gate and all(r['literal_plants_valid'] and r['planted_rule_reaches_length'] for r in rows)
    report=dict(id='CAL-010',family='FAM-004',metadata=metadata,protocol=spec,null_report_sha256=null_sha,
        assignments=plans,conditions=conditions,repetition_controls=repeats,calibration_gate_pass=gate,
        paired_trials=20,independent_backgrounds=1,new_target_explorations=0,independent_scientific_replication=False)
    sha=report_record(root,'contextual-calibration-v1',report,'contextual_calibration_finished',
        dict(id='CAL-010',gate_pass=gate,new_target_explorations=0))
    return dict(calibration_gate_pass=gate,detections_by_length={c['length']:c['detections'] for c in conditions},report_sha256=sha)


def run(root=ROOT,stage='all'):
    assert stage in ('null','all')
    folder=root/'tmp'; folder.mkdir(parents=True,exist_ok=True)
    with (folder/'contextual-calibration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:return _run(root,stage)
        except Exception as exc:
            append(root/'registry/events.jsonl','contextual_calibration_failed',dict(id='CAL-010',
                error=repr(exc),new_target_explorations=0,completed_calibration_claim=False))
            raise


if __name__=='__main__':print(json.dumps(run(stage=sys.argv[1] if len(sys.argv)>1 else 'all'),indent=2))
