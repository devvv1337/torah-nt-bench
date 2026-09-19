"""Calibration of a single table across three distinct passage pairs; no NT input."""
from collections import Counter
import json
import math
import platform
import random
import shutil
import subprocess
import sys
from .sources import ROOT,digest,write_json,verify
from .registry import append,snapshot_code
from .editions import controls
from .local_search import calibration_units,human_units,tail,report_record
from .calibration import binomial_upper
from .statistics import wilson


def build_engine(root=ROOT):
    sources={name:digest((root/'native'/name).read_bytes()) for name in ('shared_match.cpp','local_match.cpp')}
    compiler=shutil.which('clang++')
    if not compiler:raise RuntimeError('C++17 compiler unavailable')
    flags=['-std=c++17','-O3','-Wall','-Wextra','-pedantic']
    identity=dict(sources=sources,compiler=compiler,compiler_version=subprocess.check_output([compiler,'--version'],text=True),flags=flags)
    folder=root/'tmp/native';folder.mkdir(parents=True,exist_ok=True);binary=folder/'shared_match';receipt=folder/'shared-build.json'
    previous=json.loads(receipt.read_text()) if receipt.exists() else {}
    if not binary.exists() or any(previous.get(k)!=v for k,v in identity.items()) or previous.get('binary_sha256')!=digest(binary.read_bytes()):
        p=subprocess.run([compiler,*flags,str(root/'native/shared_match.cpp'),'-o',str(binary)],capture_output=True,text=True,check=True)
        write_json(receipt,dict(**identity,binary_sha256=digest(binary.read_bytes()),compiler_stderr=p.stderr))
    key=digest(json.dumps(sources,sort_keys=True).encode());archive=root/'registry/native'/key;archive.mkdir(parents=True,exist_ok=True)
    for name in sources:(archive/name).write_bytes((root/'native'/name).read_bytes())
    return binary,json.loads(receipt.read_text())


def grouped(units,left=False):
    result=[]
    for i,u in enumerate(units):
        words=[u['encoded']] if left else list(u['encoded_words'])
        result.append(dict(id=u['id'],group=u.get('group',i),words=words))
    return result


def save_input(path,left,right):
    lines=[f'{len(left)} {len(right)}']
    lines += [str(u['group'])+' '+' '.join(u['words']) for u in left+right]
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines)+'\n',encoding='ascii')


def scan(binary,path,draws,seed,minimum=16,cap=32):
    p=subprocess.run([str(binary),str(path),str(minimum),str(cap),str(draws),str(seed)],stdout=subprocess.PIPE,text=True,check=True)
    return json.loads(p.stdout)


def validate_witness(result,left,right):
    if not result['score']:
        assert not result['witness'] and not result['mapping'];return
    assert len(result['witness'])==3
    assert len({left[h['left_unit']]['group'] for h in result['witness']})==3
    assert len({right[h['right_unit']]['group'] for h in result['witness']})==3
    assert len({h['direction'] for h in result['witness']})==1
    table={};alphabet=set(''.join(''.join(u['words']) for u in left))
    for hit in result['witness']:
        q=''.join(left[hit['left_unit']]['words'])[hit['left_start']:hit['left_end']]
        if hit['direction']==-1:q=q[::-1]
        r=''.join(right[hit['right_unit']]['words'])[hit['right_start']:hit['right_start']+hit['length']]
        assert len(q)==len(r)==result['score'] and len(set(q))>=min(8,len(alphabet))
        for x,y in zip(q,r,strict=True):
            assert x not in table or table[x]==y;table[x]=y
    assert len(set(table.values()))==len(table)
    assert result['mapping']==[[ord(x)-65,ord(y)-65] for x,y in sorted(table.items())]


def reference_summary(result):
    return {mode:dict(**tail(result['score'],values),draws=len(values),histogram=dict(sorted(Counter(values).items())),
                      distinct_scores=len(set(values))) for mode,values in result['reference_scores'].items()}


def null_diagnostics(values,spec):
    size=spec['references_per_null_trial']+1
    assert len(values)==spec['null_trials_per_model']*size
    trials=[dict(observed=values[i],references=values[i+1:i+size],**tail(values[i],values[i+1:i+size])) for i in range(0,len(values),size)]
    rejections=sum(t['p']<=spec['alpha'] for t in trials);n=len(trials);upper=binomial_upper(rejections,n,spec['alpha'])
    return dict(trials=trials,rejections=rejections,repetitions=n,wilson95=wilson(rejections,n),binomial_upper_p=upper,
                false_positive_alarm=upper<.01,score_histogram=dict(sorted(Counter(values).items())),distinct_scores=len(set(values)))


def run(root=ROOT):
    integrity=verify(root)
    family_path=root/'protocol/shared-substitution-v1.json';cal_path=root/'protocol/shared-calibration-v1.json'
    family=json.loads(family_path.read_text());spec=json.loads(cal_path.read_text())
    assert (family['minimum_length'],family['maximum_length'],family['passage_pairs'])==(16,32,3)
    binary,native=build_engine(root)
    metadata=dict(family_sha256=digest(family_path.read_bytes()),calibration_protocol_sha256=digest(cal_path.read_bytes()),
                  code_snapshot=snapshot_code(root),native=native,source_integrity=integrity,python_version=sys.version,platform=platform.platform())
    append(root/'registry/events.jsonl','shared_calibration_started',dict(id=spec['id'],family=family['id'],**metadata))
    controls(root)
    control_path=root/'data/derived/controls.json';data=json.loads(control_path.read_text());metadata['human_control_data_sha256']=digest(control_path.read_bytes())
    l,r=calibration_units(data);left,right=grouped(l,True),grouped(r)
    folder=root/'data/derived/shared';folder.mkdir(parents=True,exist_ok=True)
    def execute(name,a,b,draws,seed):
        path=folder/f'{name}.txt';save_input(path,a,b)
        result=scan(binary,path,draws,seed);validate_witness(result,a,b)
        samples={}
        if draws:
            for mode in ('words','word_types'):
                for label,index in [('first',0),('last',-1)]:
                    sample=path.with_name(path.name+f'.{mode}.{label}.txt')
                    samples[f'{mode}_{label}']=dict(path=str(sample.relative_to(root)),sha256=digest(sample.read_bytes()),
                        score=result['reference_scores'][mode][index],mode=mode)
        return dict(input_path=str(path.relative_to(root)),input_sha256=digest(path.read_bytes()),reference_samples=samples,result=result)
    def binary_units(units):
        return [dict(u,words=[''.join(chr(65+(ord(c)-65)%2) for c in w) for w in u['words']]) for u in units]
    draws=spec['null_trials_per_model']*(1+spec['references_per_null_trial'])
    null=execute('binary-null',binary_units(left),binary_units(right),draws,spec['seed'])
    diagnostics={mode:null_diagnostics(values,spec) for mode,values in null['result']['reference_scores'].items()}
    print('CAL-006 null', {m:dict(rejections=v['rejections'],distinct_scores=v['distinct_scores']) for m,v in diagnostics.items()},flush=True)
    rng=random.Random(spec['seed']);injections=[]
    planted=[(3,8,2,16),(7,10,5,16),(11,12,9,16)]
    for trial in range(spec['injections']):
        mapping=list(range(24));rng.shuffle(mapping);modified=[dict(u,words=list(u['words'])) for u in right]
        for lu,ls,ru,rs in planted:
            piece=''.join(left[lu]['words'])[ls:ls+32];assert len(piece)==32 and len(set(piece))>=8
            transformed=''.join(chr(65+mapping[ord(c)-65]) for c in piece)
            original=''.join(modified[ru]['words']);altered=original[:rs]+transformed+original[rs+32:]
            modified[ru]['words']=[altered[i:i+4] for i in range(0,len(altered),4)]
        record=execute(f'injection-{trial:02d}',left,modified,spec['injection_references_per_model'],spec['seed']+1000+trial)
        references=reference_summary(record['result']);recovered=record['result']['score']==32
        injections.append(dict(trial=trial,mapping=mapping,planted_coordinates=planted,all_planted_pairs_admissible=True,
            shared_signal_recovered=recovered,detection=recovered and all(v['p']<=.01 for v in references.values()),references=references,**record))
        print('CAL-006 injection',trial,'score',record['result']['score'],{m:v['p'] for m,v in references.items()},flush=True)
    a=[dict(id=f'repeat-left-{i}',group=i,words=['ABCDEFGH'*4]) for i in range(3)]
    b=[dict(id=f'repeat-right-{i}',group=i,words=['IJKLMNOP']*4) for i in range(3)]
    repetition=execute('repeated-formula',a,b,199,spec['seed']+5000);repetition['references']=reference_summary(repetition['result'])
    repetition['gate_pass']=repetition['result']['score']==32 and all(v['p']==1 for v in repetition['references'].values())
    detected=sum(i['detection'] for i in injections)
    gate=(not any(v['false_positive_alarm'] for v in diagnostics.values()) and detected>=18
          and all(i['shared_signal_recovered'] for i in injections) and repetition['gate_pass'])
    cost=dict(formal_partial_injective_tables=sum(math.comb(22,d)*math.perm(24,d) for d in range(8,23)),
              directions=2,common_lengths=17,grammar_bytes=len(family_path.read_bytes()),
              shared_decoder_bytes=len((root/'native/shared_match.cpp').read_bytes()),
              dependency_decoder_bytes=len((root/'native/local_match.cpp').read_bytes()),
              note='Formal table count is not an independent-trial count; each complete scan repeats position, length, direction and compatible-table selection')
    report=dict(id=spec['id'],family=family['id'],metadata=metadata,protocol=spec,
        null_baseline_result={k:v for k,v in null['result'].items() if k!='reference_scores'},null_input=null['input_path'],
        null_input_sha256=null['input_sha256'],null_reference_samples=null['reference_samples'],null_diagnostics=diagnostics,injections=injections,detections=detected,
        repetition_control=repetition,calibration_gate_pass=gate,description_scope=cost,
        new_target_explorations=0,independent_replication=False)
    cal_sha=report_record(root,'shared-calibration-v1',report,'shared_calibration_finished',dict(id=spec['id'],gate_pass=gate,new_target_explorations=0))
    if not gate:return dict(calibration_gate_pass=False,report_sha256=cal_sha,target_exploration_executed=False)
    hleft,hright=human_units(data);hleft,hright=grouped(hleft,True),grouped(hright)
    human=execute('berakhot-xenophon',hleft,hright,199,2026091869);human['references']=reference_summary(human['result'])
    human.update(left_units=len(hleft),right_units=len(hright),left_letters=sum(sum(map(len,u['words'])) for u in hleft),
                 right_letters=sum(sum(map(len,u['words'])) for u in hright),
                 candidate_screen_pass=human['result']['score']>=24 and all(v['p']<=.01 for v in human['references'].values()))
    human_sha=report_record(root,'shared-human-control-v1',dict(metadata=metadata,calibration_sha256=cal_sha,**human,
        status='Unmatched human-language negative control; not an independent Hebrew-Greek translation pair',new_target_explorations=0),
        'shared_human_control_finished',dict(family=family['id'],score=human['result']['score'],new_target_explorations=0))
    return dict(calibration_gate_pass=gate,detections=detected,human_score=human['result']['score'],
                human_p_values={m:v['p'] for m,v in human['references'].items()},calibration_sha256=cal_sha,
                human_report_sha256=human_sha,target_exploration_executed=False)
