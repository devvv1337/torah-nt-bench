"""Second implementation: literal table unions and full-prefix triple enumeration."""
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from biblelab.sources import digest,write_json
from biblelab.registry import append


def read_input(path):
    lines=path.read_text().splitlines();nl,nr=map(int,lines[0].split());assert len(lines)==1+nl+nr
    units=[]
    for line in lines[1:]:
        group,*words=line.split();assert all('A'<=c<='X' for w in words for c in w)
        units.append(dict(group=int(group),words=words))
    return units[:nl],units[nl:]


def pattern(text):
    seen={};code=[]
    for c in text:
        if c not in seen:seen[c]=len(seen)
        code.append(seen[c])
    return tuple(code)


def union_table(a,b):
    result=dict(a)
    for x,y in b.items():
        if x in result and result[x]!=y:return None
        result[x]=y
    return result if len(set(result.values()))==len(result) else None


def oracle(left,right,minimum=16,cap=32):
    index=defaultdict(list);alphabet=set(''.join(''.join(u['words']) for u in left));distinct=min(8,len(alphabet))
    for direction in (1,-1):
        for li,l in enumerate(left):
            text=''.join(l['words'])[::direction]
            for start in range(len(text)-minimum+1):index[pattern(text[start:start+minimum])].append((li,direction,start,text))
    levels=defaultdict(list);seeds=0
    for ri,r in enumerate(right):
        text=''.join(r['words'])
        for start in range(len(text)-minimum+1):
            for li,direction,qstart,q in index.get(pattern(text[start:start+minimum]),[]):
                seeds+=1;mapping={};inverse={}
                for k,(x,y) in enumerate(zip(q[qstart:qstart+cap],text[start:start+cap]),1):
                    if (x in mapping and mapping[x]!=y) or (y in inverse and inverse[y]!=x):break
                    mapping[x]=y;inverse[y]=x
                    if k>=minimum and len(mapping)>=distinct:
                        levels[k,direction].append((left[li]['group'],r['group'],mapping.copy()))
    for k in range(cap,minimum-1,-1):
        for direction in (1,-1):
            hits=levels[k,direction]
            if len({h[0] for h in hits})<3 or len({h[1] for h in hits})<3:continue
            for i,a in enumerate(hits):
                for j in range(i+1,len(hits)):
                    b=hits[j]
                    if a[0]==b[0] or a[1]==b[1]:continue
                    pair=union_table(a[2],b[2])
                    if pair is None:continue
                    for c in hits[j+1:]:
                        if c[0] in (a[0],b[0]) or c[1] in (a[1],b[1]):continue
                        if union_table(pair,c[2]) is not None:return dict(score=k,compatible_seed_pairs=seeds)
    return dict(score=0,compatible_seed_pairs=seeds)


def verify_witness(result,left,right):
    if not result['score']:assert result['witness']==[] and result['mapping']==[];return
    hit=result['witness'];assert len(hit)==3
    assert len({left[h['left_unit']]['group'] for h in hit})==3
    assert len({right[h['right_unit']]['group'] for h in hit})==3
    assert len({h['direction'] for h in hit})==1
    K=len(set(''.join(''.join(u['words']) for u in left)));total={}
    for h in hit:
        raw=''.join(left[h['left_unit']]['words']);native=raw[h['left_start']:h['left_end']]
        assert h['left_start']==(h['left_oriented_start'] if h['direction']==1 else len(raw)-h['left_oriented_start']-h['length'])
        q=native[::h['direction']];r=''.join(right[h['right_unit']]['words'])[h['right_start']:h['right_start']+h['length']]
        assert len(q)==len(r)==h['length']==result['score'] and len(set(q))>=min(8,K)
        pairs=list(zip(q,r));mapping=dict(pairs);assert all(mapping[x]==y for x,y in pairs)
        total=union_table(total,mapping);assert total is not None
    assert result['mapping']==[[ord(x)-65,ord(y)-65] for x,y in sorted(total.items())]


def verify_reference(base,sample,mode):
    assert len(base)==len(sample)
    for a,b in zip(base,sample,strict=True):
        assert a['group']==b['group'] and len(a['words'])==len(b['words'])
        if mode=='words':assert Counter(a['words'])==Counter(b['words'])
    if mode=='word_types':
        substitution={}
        for a,b in zip(base,sample,strict=True):
            for x,y in zip(a['words'],b['words'],strict=True):
                assert len(x)==len(y) and (x not in substitution or substitution[x]==y)
                substitution[x]=y
        assert len(set(substitution.values()))==len(substitution) and set(substitution)==set(substitution.values())


def verify_p(result,summary):
    for mode,values in result['reference_scores'].items():
        exceeds=sum(x>=result['score'] for x in values);expected=(1+exceeds)/(1+len(values))
        assert summary[mode]['p']==expected and summary[mode]['exceedances']==exceeds
        assert summary[mode]['histogram']=={str(k):v for k,v in sorted(Counter(values).items())}


def main():
    cal_path=ROOT/'reports/shared-calibration-v1.json';cal=json.loads(cal_path.read_text())
    human_path=ROOT/'reports/shared-human-control-v1.json';human=json.loads(human_path.read_text())
    assert human['calibration_sha256']==digest(cal_path.read_bytes())
    for name,sha in cal['metadata']['native']['sources'].items():assert digest((ROOT/'native'/name).read_bytes())==sha
    checks=[];null_checks={}
    for mode,d in cal['null_diagnostics'].items():
        scores=[];reject=0
        for t in d['trials']:
            expected=(1+sum(x>=t['observed'] for x in t['references']))/(len(t['references'])+1)
            assert t['p']==expected and len(t['references'])==199
            reject+=expected<=.05;scores.extend([t['observed'],*t['references']])
        assert len(d['trials'])==200 and d['rejections']==reject
        upper=sum(math.comb(200,j)*.05**j*.95**(200-j) for j in range(reject,201))
        assert math.isclose(upper,d['binomial_upper_p'],rel_tol=1e-11)
        assert d['false_positive_alarm']==(upper<.01)
        assert d['score_histogram']=={str(k):v for k,v in sorted(Counter(scores).items())}
        null_checks[mode]=dict(trials=200,reference_and_observation_scores=len(scores),rejections=reject,
                               first=scores[0],last=scores[-1])
    records=[dict(name='binary_null',input_path=cal['null_input'],input_sha256=cal['null_input_sha256'],
                  result=cal['null_baseline_result'],reference_samples=cal['null_reference_samples'])]
    records += [dict(name=f'injection_{r["trial"]}',**r) for r in cal['injections']]
    records += [dict(name='repeated_formula',**cal['repetition_control']),dict(name='human_control',**human)]
    for record in records:
        path=ROOT/record['input_path'];assert digest(path.read_bytes())==record['input_sha256']
        left,right=read_input(path);verify_witness(record['result'],left,right)
        if record['result']['score']==32:
            primary=dict(score=32,proof='Literal valid triple attains the declared global upper bound')
        else:
            primary=oracle(left,right);assert primary['score']==record['result']['score']
            assert primary['compatible_seed_pairs']==record['result']['compatible_seed_pairs']
        if 'references' in record:verify_p(record['result'],record['references'])
        samples=[]
        for label,entry in record['reference_samples'].items():
            p=ROOT/entry['path'];assert digest(p.read_bytes())==entry['sha256']
            a,b=read_input(p);assert a==left;verify_reference(right,b,entry['mode'])
            observed=oracle(a,b);assert observed['score']==entry['score'],(record['name'],label,observed,entry['score'])
            if record['name']=='binary_null':assert entry['score']==null_checks[entry['mode']][label.rsplit('_',1)[1]]
            else:assert entry['score']==record['result']['reference_scores'][entry['mode']][0 if label.endswith('first') else -1]
            samples.append(dict(label=label,score=observed['score'],compatible_seed_pairs=observed['compatible_seed_pairs']))
        if record['name'].startswith('injection_'):
            mapping=record['mapping'];assert sorted(mapping)==list(range(24))
            for lu,ls,ru,rs in record['planted_coordinates']:
                a=''.join(left[lu]['words'])[ls:ls+32];b=''.join(right[ru]['words'])[rs:rs+32]
                assert len(a)==len(b)==32 and len(set(a))>=8
                assert ''.join(chr(65+mapping[ord(c)-65]) for c in a)==b
            expected=record['result']['score']==32 and all(x['p']<=.01 for x in record['references'].values())
            assert record['detection']==expected
        checks.append(dict(name=record['name'],primary=primary,samples=samples))
        print(record['name'],'verified',flush=True)
    assert cal['detections']==sum(r['detection'] for r in cal['injections'])==20
    assert cal['repetition_control']['result']['score']==32 and all(r['p']==1 for r in cal['repetition_control']['references'].values())
    assert cal['calibration_gate_pass'] and not any(d['false_positive_alarm'] for d in cal['null_diagnostics'].values())
    prior_path=ROOT/'reports/archive/shared-calibration-v1.b8783700780f.json'
    prior=json.loads(prior_path.read_text())
    for key in ('null_diagnostics','injections','detections','repetition_control','calibration_gate_pass'):assert prior[key]==cal[key]
    previous_human=json.loads((ROOT/'reports/archive/shared-human-control-v1.e88b1b37bf02.json').read_text())
    assert previous_human['result']==human['result'] and previous_human['references']==human['references']
    result=dict(calibration_sha256=digest(cal_path.read_bytes()),human_control_sha256=digest(human_path.read_bytes()),
        validator_sha256=digest(Path(__file__).read_bytes()),null_checks=null_checks,checks=checks,
        archived_implementation_revision_statistical_results_identical=True,new_independent_trials_from_rerun=0,
        independent_scientific_replication=False,new_target_explorations=0,
        scope='All p-values and gates; every observed witness; maximality by independent complete triple enumeration or a literal witness at the upper cap; first/last reference corpora for each model and each input, including global word-type preservation')
    out=ROOT/'reports/shared-algorithm-check.json';write_json(out,result);sha=digest(out.read_bytes())
    write_json(ROOT/f'reports/archive/shared-algorithm-check.{sha[:12]}.json',result)
    folder=ROOT/'registry/validation-code'/result['validator_sha256'];folder.mkdir(parents=True,exist_ok=True)
    (folder/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    append(ROOT/'registry/events.jsonl','shared_calibration_verification',dict(report_sha256=sha,new_target_explorations=0,independent_scientific_replication=False))
    print(json.dumps(dict(null_checks=null_checks,observed_inputs=len(checks),sampled_reference_corpora=sum(len(c['samples']) for c in checks))),flush=True)


if __name__=='__main__':main()
