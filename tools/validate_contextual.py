"""CAL-010: independent literal-program scores, raw human input and gates."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from biblelab.sources import digest,write_json,verify
from biblelab.registry import canonical,read_events,append
from biblelab.local_search import report_record
from validate_shared import read_input,verify_reference,verify_p


def build(name):
    compiler=shutil.which('clang++'); assert compiler
    source=ROOT/'native'/f'{name}.cpp'; binary=ROOT/'tmp/native'/name
    dependencies=[source]
    if name=='contextual_replay':dependencies += [ROOT/'native/contextual_match.cpp',ROOT/'native/local_match.cpp']
    identity=dict(sources={p.name:digest(p.read_bytes()) for p in dependencies},
        compiler=compiler,version=subprocess.check_output([compiler,'--version'],text=True),flags=['-std=c++17','-O3','-Wall','-Wextra','-pedantic'])
    receipt=binary.with_suffix('.build.json');old=json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(old.get(k)!=v for k,v in identity.items()) or old.get('binary_sha256')!=digest(binary.read_bytes()):
        p=subprocess.run([compiler,*identity['flags'],str(source),'-o',str(binary)],capture_output=True,text=True,check=True)
        write_json(receipt,dict(**identity,binary_sha256=digest(binary.read_bytes()),stderr=p.stderr))
    archive=ROOT/'registry/native'/digest(canonical(identity['sources']));archive.mkdir(parents=True,exist_ok=True)
    for p in dependencies:(archive/p.name).write_bytes(p.read_bytes())
    return binary,json.loads(receipt.read_text())


def oracle(binary,path,minimum=8,cap=32):
    return json.loads(subprocess.check_output([str(binary),str(path),str(minimum),str(cap)],text=True))


def human_input():
    path=ROOT/'data/derived/controls.json';previous=json.loads((ROOT/'reports/shared-calibration-v1.json').read_text())
    assert digest(path.read_bytes())==previous['metadata']['human_control_data_sha256']
    data=json.loads(path.read_text());he='אבגדהוזחטיכלמנסעפצקרשת';gr='αβγδεζηθικλμνξοπρστυφχψω'
    def hebrew(raw):
        folded=raw.translate(str.maketrans('ךםןףץ','כמנפצ'))
        return ''.join(chr(65+he.index(c)) for c in folded if c in he)
    def greek(raw):
        text=unicodedata.normalize('NFD',raw).lower().replace('ς','σ')
        return ''.join(chr(65+gr.index(c)) for c in text if c in gr)
    blocks=[hebrew(line) for line in data['berakhot']['raw'].splitlines() if line.strip()]
    left=[dict(group=i,words=[text]) for i,text in enumerate(blocks)]
    words=[greek(w) for w in data['xenophon']['raw'].split('\ufffc')[0].split() if greek(w)]
    right=[dict(group=i//16,words=words[i:i+16]) for i in range(0,len(words),16)]
    return left,right


def parameters(rule):
    return (1 if rule<384 else -1,(-2,-1,1,2)[(rule//96)%4],(-2,-1,1,2)[(rule//24)%4],rule%24)


def literal(source,rule):
    _,a,b,c=parameters(rule); h=[ord(x)-65 for x in source]
    return ''.join(chr(65+(a*h[j]+b*h[j+1]+c)%24) for j in range(len(h)-1))


def witness_check(result,left,right):
    ids=result['maximizing_rule_ids'];assert ids==[w['rule_id'] for w in result['witnesses']]
    for w in result['witnesses']:
        rule=w['rule_id'];d,a,b,c=parameters(rule)
        assert [w[k] for k in ('direction','a','b','c')]==[d,a,b,c]
        hits=w['hits'];assert len(hits)==3
        assert len({left[h['left_unit']]['group'] for h in hits})==len({right[h['right_unit']]['group'] for h in hits})==3
        for h in hits:
            K=result['score'];assert h['direction']==d and h['length']==K and h['source_length']==K+1
            raw=''.join(left[h['left_unit']]['words'])
            expected=h['left_oriented_start'] if d==1 else len(raw)-h['left_oriented_start']-K-1
            assert h['left_start']==expected and h['left_end']==expected+K+1
            assert 0<=expected<expected+K+1<=len(raw)
            q=raw[expected:expected+K+1][::d]
            g=''.join(right[h['right_unit']]['words'])[h['right_start']:h['right_start']+K]
            assert len(g)==K and literal(q,rule)==g


def record_check(binary,record,expected,draws):
    path=ROOT/record['input_path'];assert digest(path.read_bytes())==record['input_sha256']
    left,right=read_input(path);assert (left,right)==expected
    result=record['result'];primary=oracle(binary,path)
    for key in ('score','rule_scores','maximizing_rule_ids','compatible_seed_pairs'):assert result[key]==primary[key],(path,key)
    ls=2*sum(max(0,sum(map(len,u['words']))-8) for u in left)
    rs=sum(max(0,sum(map(len,u['words']))-7) for u in right)
    assert [result[k] for k in ('left_oriented_starts','indexed_source_starts','right_starts','start_pairs','formal_rule_start_pairs')]==[ls,ls*16,rs,ls*rs,ls*rs*384]
    witness_check(result,left,right);verify_p(result,record['references'])
    assert all(len(v)==draws for v in result['reference_scores'].values())
    samples=[]
    for label,entry in record['reference_samples'].items():
        path=ROOT/entry['path'];assert digest(path.read_bytes())==entry['sha256']
        a,b=read_input(path);assert a==left;verify_reference(right,b,entry['mode'])
        q=oracle(binary,path);index=0 if label.endswith('first') else -1
        assert q['score']==entry['score']==result['reference_scores'][entry['mode']][index]
        samples.append(dict(label=label,input_sha256=entry['sha256'],**q))
    assert len(samples)==4
    return dict(input_sha256=record['input_sha256'],primary=primary,samples=samples)


def metadata_check(report):
    family=ROOT/'protocol/contextual-affine-v1.json';cal=ROOT/'protocol/contextual-calibration-v1.json'
    assert report['metadata']['family_sha256']==digest(family.read_bytes())
    assert report['metadata']['protocol_sha256']==digest(cal.read_bytes())
    assert report['protocol']==json.loads(cal.read_text())
    events=read_events(ROOT/'registry/events.jsonl')
    start=min(e['sequence'] for e in events if e['kind']=='contextual_calibration_started')
    for path in (family,cal):
        freeze=next(e['sequence'] for e in events if e['kind']=='protocol_frozen' and e['payload'].get('sha256')==digest(path.read_bytes()))
        assert freeze<start
    for n,sha in report['metadata']['native']['sources'].items():assert digest((ROOT/'native'/n).read_bytes())==sha
    base=report['metadata']['base'];path=ROOT/base['input_path']
    assert digest(path.read_bytes())==base['input_sha256']
    assert digest((ROOT/'reports/shared-common-controls-v1.json').read_bytes())==base['report_sha256']
    assert read_input(path)==human_input()


def null_check(binary,report):
    metadata_check(report);left,right=human_input();sides=[]
    for side in (left,right):
        letters=''.join(''.join(u['words']) for u in side)[:1024]
        bits=''.join(chr(65+(ord(c)-65)%2) for c in letters)
        sides.append([dict(group=i,words=[bits[i*64+j:i*64+j+4] for j in range(0,64,4)]) for i in range(16)])
    check=record_check(binary,report['record'],tuple(sides),40000)
    diagnostics={}
    for mode,data in report['diagnostics'].items():
        all_scores=report['record']['result']['reference_scores'][mode];reject=0
        for i,trial in enumerate(data['trials']):
            values=all_scores[i*200:(i+1)*200];p=(1+sum(s>=values[0] for s in values[1:]))/200
            assert trial['observed']==values[0] and trial['references']==values[1:] and trial['p']==p
            reject+=p<=.05
        assert len(data['trials'])==200 and data['rejections']==reject
        upper=sum(math.comb(200,j)*.05**j*.95**(200-j) for j in range(reject,201))
        assert math.isclose(upper,data['binomial_upper_p'],rel_tol=1e-11)
        assert data['false_positive_alarm']==(upper<.01) and data['distinct_scores']==len(set(all_scores))
        assert data['score_histogram']=={str(k):v for k,v in sorted(Counter(all_scores).items())}
        diagnostics[mode]=dict(rejections=reject,upper_p=upper,distinct_scores=len(set(all_scores)))
    gate=all(d['upper_p']>=.01 and d['distinct_scores']>=2 for d in diagnostics.values())
    assert report['null_gate_pass']==gate
    # Every first member of a 200-score block is a null pseudo-observation.
    # Recreate those 400 inputs from the frozen RNG stream, then evaluate them
    # with the literal oracle. This does not share the production search algorithm.
    replay,build_meta=build('contextual_replay');folder=ROOT/'data/derived/contextual/null-observations';folder.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(replay),str(ROOT/report['record']['input_path']),str(folder)+'/',str(report['protocol']['null_seed'])],check=True)
    jobs=[]
    for mode in ('words','word_types'):
        for label,file in (('first',folder/f'{mode}.0.txt'),('last',folder/f'{mode}.last.txt')):
            original=ROOT/report['record']['reference_samples'][f'{mode}_{label}']['path']
            assert file.read_bytes()==original.read_bytes()
        for i in range(200):jobs.append((mode,i,folder/f'{mode}.{i}.txt'))
    def evaluate(item):
        mode,i,path=item;a,b=read_input(path);assert a==sides[0];verify_reference(sides[1],b,mode)
        result=oracle(binary,path)
        assert result['score']==report['record']['result']['reference_scores'][mode][i*200]
        return dict(mode=mode,trial=i,input_path=str(path.relative_to(ROOT)),input_sha256=digest(path.read_bytes()),**result)
    with ThreadPoolExecutor(max_workers=2) as pool:observations=list(pool.map(evaluate,jobs))
    return dict(record=check,diagnostics=diagnostics,null_gate_pass=gate,pseudo_observations=observations,replay_build=build_meta)


def expected_plans(left,right,spec):
    indices=[]
    for side,minimum in ((left,33),(right,48)):
        seen=set();selected=[]
        for i,u in enumerate(side):
            if sum(map(len,u['words']))>=minimum and u['group'] not in seen:
                selected.append(i);seen.add(u['group'])
            if len(selected)==3:break
        assert len(selected)==3;indices.append(selected)
    rng=random.Random(spec['rule_seed']);forward=rng.sample(range(384),10);backward=rng.sample(range(384,768),10)
    plans=[]
    for trial,rule in enumerate(x for pair in zip(forward,backward) for x in pair):
        d,a,b,c=parameters(rule)
        plans.append(dict(trial=trial,rule_id=rule,direction=d,a=a,b=b,c=c,seed=2026095000+trial,
            coordinates=[dict(left_unit=l,left_oriented_start=0,right_unit=r,right_start=16) for l,r in zip(*indices)]))
    return plans


def implanted(left,right,plan,K):
    copy=[dict(u,words=list(u['words'])) for u in right]
    for coord in plan['coordinates']:
        li,ri=coord['left_unit'],coord['right_unit'];raw=''.join(left[li]['words'])[::plan['direction']]
        plant=literal(raw[:K+1],plan['rule_id']);original=''.join(right[ri]['words'])
        text=original[:16]+plant+original[16+K:];assert len(text)==len(original)
        bounds=[0]
        for word in right[ri]['words']:bounds.append(bounds[-1]+len(word))
        copy[ri]['words']=[text[a:b] for a,b in zip(bounds,bounds[1:])]
    return copy


def covers_plants(result,plan,K):
    witnesses=[w for w in result['witnesses'] if w['rule_id']==plan['rule_id']]
    if not witnesses:return False
    return all(any(h['left_unit']==p['left_unit'] and h['right_unit']==p['right_unit']
        and h['left_oriented_start']<=0 and h['left_oriented_start']+h['length']>=K
        and -h['left_oriented_start']==16-h['right_start'] for h in witnesses[0]['hits']) for p in plan['coordinates'])


def calibration_check(binary,report,null_report):
    metadata_check(report);assert report['null_report_sha256']==digest((ROOT/'reports/contextual-null-v1.json').read_bytes())
    assert null_report['null_gate_pass'];left,right=human_input();plans=expected_plans(left,right,report['protocol'])
    assert report['assignments']==plans;checks=[];condition_checks=[]
    assert [c['length'] for c in report['conditions']]==[8,16,32]
    for condition in report['conditions']:
        K=condition['length'];assert len(condition['injections'])==20 and condition['diagnostic_only']==(K==8)
        jobs=[]
        for trial,record in enumerate(condition['injections']):
            plan=plans[trial];assert record['assignment']==plan and record['length']==K
            jobs.append((record,(left,implanted(left,right,plan,K))))
        def evaluate(item):
            r,pair=item;check=record_check(binary,r,pair,199);plan=r['assignment'];result=r['result']
            reached=result['rule_scores'][plan['rule_id']]>=K;assert r['literal_plants_valid'] and r['planted_rule_reaches_length']==reached
            assert r['planted_rule_maximizing']==(plan['rule_id'] in result['maximizing_rule_ids'])
            assert r['maximizing_witness_covers_implants']==covers_plants(result,plan,K)
            assert r['detection']==(result['score']>=K and all(v['p']<=.01 for v in r['references'].values()))
            print('checked implant',K,plan['trial'],flush=True)
            return dict(length=K,trial=plan['trial'],**check)
        with ThreadPoolExecutor(max_workers=2) as pool:checks.extend(pool.map(evaluate,jobs))
        records=condition['injections'];detections=sum(r['detection'] for r in records)
        assert condition['detections']==detections
        by_direction={str(d):sum(r['detection'] for r in records if r['assignment']['direction']==d) for d in (1,-1)}
        for d,v in by_direction.items():assert condition['directions'][d]['detections']==v and condition['directions'][d]['trials']==10
        gate=detections>=18 and min(by_direction.values())>=9 and all(r['literal_plants_valid'] and r['planted_rule_reaches_length'] for r in records)
        assert condition['gate_pass']==gate
        condition_checks.append(dict(length=K,detections=detections,directions=by_direction,gate_pass=gate))
    assert [r['name'] for r in report['repetition_controls']]==['periodic','constant']
    for record in report['repetition_controls']:
        name=record['name'];h='A'*33 if name=='constant' else 'ABCDEFGH'*4+'A';g='A'*8 if name=='constant' else 'BDFHJLNH'
        pair=([dict(group=i,words=[h]) for i in range(3)],[dict(group=i,words=[g]*4) for i in range(3)])
        check=record_check(binary,record,pair,199);assert record['result']['score']==32
        assert all(v['p']==1 for v in record['references'].values()) and record['gate_pass']
        if name=='constant':assert record['result']['maximizing_rule_ids']==list(range(0,768,24))
        checks.append(dict(name=name,**check))
    gate=all(c['gate_pass'] for c in condition_checks if c['length']!=8)
    gate=gate and all(r['planted_rule_reaches_length'] and r['literal_plants_valid'] for c in report['conditions'] for r in c['injections'])
    assert report['calibration_gate_pass']==gate
    return dict(records=checks,conditions=condition_checks,calibration_gate_pass=gate)


def main(stage):
    assert stage in ('null','all');integrity=verify(ROOT);binary,native=build('contextual_oracle')
    null_path=ROOT/'reports/contextual-null-v1.json';null=json.loads(null_path.read_text())
    check_path=ROOT/'reports/contextual-null-algorithm-check.json'
    if stage=='all' and check_path.exists():
        prior=json.loads(check_path.read_text())
        assert prior['null_report_sha256']==digest(null_path.read_bytes()) and prior['native']==native
        assert prior['validator_sha256']==digest(Path(__file__).read_bytes())
        null_checked=prior['null_check']
    else:null_checked=null_check(binary,null)
    report=dict(stage=stage,null_report_sha256=digest(null_path.read_bytes()),native=native,source_integrity=integrity,
        validator_sha256=digest(Path(__file__).read_bytes()),null_check=null_checked,
        algorithmically_independent_of_primary_search=True,independent_scientific_replication=False,
        references_fully_recomputed=False,new_target_explorations=0)
    if stage=='all':
        path=ROOT/'reports/contextual-calibration-v1.json';report['calibration_report_sha256']=digest(path.read_bytes())
        report['calibration_check']=calibration_check(binary,json.loads(path.read_text()),null)
    report['observations_recalculated']=401+(62 if stage=='all' else 0)
    report['reference_corpora_recalculated']=4+(248 if stage=='all' else 0)
    name='contextual-calibration-algorithm-check' if stage=='all' else 'contextual-null-algorithm-check'
    sha=report_record(ROOT,name,report,'contextual_algorithm_check_finished',dict(stage=stage,
        observations=report['observations_recalculated'],reference_corpora=report['reference_corpora_recalculated'],new_target_explorations=0))
    print(json.dumps(dict(stage=stage,report_sha256=sha,observations=report['observations_recalculated'],reference_corpora=report['reference_corpora_recalculated']),indent=2))


if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'all')
