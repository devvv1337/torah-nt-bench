#!/usr/bin/env python3
"""Independent EXP-001 reconstruction. Reads only the supplied input packet.

No project module, original implementation, original scores or external source
is imported. This file and engine.cpp were authored from the input definition.
"""
from __future__ import annotations
import array
import csv
import hashlib
import itertools
import json
import math
import os
import pathlib
import platform
import random
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
INPUTS = HERE.parent / 'exp001-inputs'
LOG = HERE / 'execution.log'
PARAMS = ([1,-1], list(range(8)), [1,5,7,11,13,17,19,23], list(range(24)))

def sha(b): return hashlib.sha256(b).hexdigest()
def save(name, obj): (HERE/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def log(s):
    with LOG.open('a', encoding='utf-8') as f: f.write(s+'\n')
    print(s, flush=True)
def command(args):
    log('COMMAND: '+repr([str(a) for a in args]))
    p = subprocess.run([str(a) for a in args], cwd=HERE, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log(p.stdout.rstrip())
    if p.returncode: raise RuntimeError(f'Command exited {p.returncode}')
    return p.stdout
def payload(path, h, g, refs):
    assert len(g)%16 == 0
    with path.open('wb') as f:
        f.write(b'FAM001I1'+struct.pack('<III',len(h),len(g),len(refs)))
        for group in PARAMS:
            f.write(struct.pack('<I',len(group)))
            for x in group: f.write(struct.pack('<i',x))
        f.write(bytes(h)); f.write(bytes(g))
        for p in refs: f.write(bytes(p))
def matrices(path):
    a=array.array('I'); a.frombytes(path.read_bytes())
    assert a.itemsize == 4
    if sys.byteorder != 'little': a.byteswap()
    return a
def read_csv(name):
    with (HERE/name).open(newline='') as f:
        return list(csv.DictReader(f))
def rule_parameters(): return list(itertools.product(*PARAMS))

def regenerate_references():
    rng=random.Random(2026091803)
    def perm():
        p=list(range(16)); rng.shuffle(p); return p
    for _ in range(40000): perm()
    for _ in range(199): perm()
    for rate in (0.25,0.5,1.0):
        for _ in range(20):
            for _ in range(1024):
                if rng.random() < rate: rng.randrange(24)
            for _ in range(199): perm()
    for _ in range(1999): perm()
    for _ in range(1999): perm()
    return [perm() for _ in range(4999)]

def synthetic_check(engine, h_length, unit_length, seed):
    # All 786,432 matrix cells are checked by a direct Python implementation
    # on each miniature stream. Check both Hebrew/Greek length orderings.
    rng=random.Random(seed); n=16*unit_length
    h=[rng.randrange(22) for _ in range(h_length)]
    g=[rng.randrange(24) for _ in range(n)]
    refs=[list(range(16)),list(reversed(range(16))),list(range(1,16))+[0]]
    for _ in range(5):
        p=list(range(16)); rng.shuffle(p); refs.append(p)
    prefix=f'synthetic-{seed}'
    payload(HERE/(prefix+'.bin'),h,g,refs)
    command([engine,HERE/(prefix+'.bin'),HERE/prefix])
    got=matrices(HERE/(prefix+'-matrices.bin'))
    rows=read_csv(prefix+'-rules.csv')
    reference_rows=read_csv(prefix+'-reference-maxima.csv')
    ref_scores=[[] for _ in refs]
    parameters=rule_parameters()
    for r,(direction,offset,a,b) in enumerate(parameters):
        predicted=[]
        for j in range(n):
            t=(j*h_length)//n
            u=t if direction==1 else h_length-1-t
            v=(u+offset)%h_length
            q=(22*h[v]+h[(v+1)%h_length])%24
            predicted.append((a*q+b)%24)
        matrix=[sum(predicted[i*unit_length+s]==g[k*unit_length+s] for s in range(unit_length)) for i in range(16) for k in range(16)]
        assert list(got[r*256:(r+1)*256])==matrix, (prefix,'matrix',r)
        total=sum(matrix); observed=sum(predicted[j]==g[j] for j in range(n))
        assert int(rows[r]['matches'])==observed
        assert int(rows[r]['centered_score'])==16*observed-total
        for index,p in enumerate(refs):
            ref_scores[index].append(16*sum(matrix[i*16+p[i]] for i in range(16))-total)
    for index,scores in enumerate(ref_scores):
        maximum=max(scores); ties=[i for i,x in enumerate(scores) if x==maximum]
        row=reference_rows[index]
        assert int(row['maximum_centered_score'])==maximum
        assert int(row['tie_count'])==len(ties)
        assert row['winning_rule_indices']==';'.join(map(str,ties))
    return {'hebrew_length':h_length,'covered_greek_length':n,'reference_count':len(refs),'all_matrix_cells_checked':len(got),'all_rule_observed_counts_checked':len(rows),'passed':True}

def main():
    if (HERE/'OUTPUT-SHA256.json').exists():
        raise RuntimeError('Outputs already sealed; refusing to overwrite the sealed replication')
    LOG.write_text('',encoding='utf-8')
    started=datetime.now(timezone.utc).isoformat()
    log('Independent reconstruction started UTC '+started)
    supplied=json.loads((INPUTS/'manifest.json').read_bytes())
    allowed=set(supplied['files'])|{'manifest.json'}
    assert allowed=={'manifest.json','README.md','FAM-001-definition.json','provenance.json','torah.txt','nt.txt','reference-orders.json'}
    packet={name:(INPUTS/name).read_bytes() for name in sorted(allowed)}
    ledger={name:{'sha256':sha(content),'bytes':len(content)} for name,content in packet.items()}
    for name,expected in supplied['files'].items(): assert ledger[name]['sha256']==expected,(name,'sha256')
    d=json.loads(packet['FAM-001-definition.json']); provenance=json.loads(packet['provenance.json'])
    assert provenance['definition_sha256']==ledger['FAM-001-definition.json']['sha256']
    assert [d['directions'],d['offsets'],d['multipliers'],d['intercepts']]==list(PARAMS)
    assert d['family_size']==supplied['rule_count']==math.prod(map(len,PARAMS))==3072
    assert d['unit_count']==16 and d['rank_origin']==0
    assert d['hebrew_alphabet']=='אבגדהוזחטיכלמנסעפצקרשת'
    assert d['greek_alphabet']=='αβγδεζηθικλμνξοπρστυφχψω'
    ht=packet['torah.txt'].decode('utf-8'); gt=packet['nt.txt'].decode('utf-8')
    for name,text,key in [('torah.txt',ht,'torah'),('nt.txt',gt,'nt')]:
        assert len(text)==provenance['texts'][key]['letters']
        assert ledger[name]['sha256']==provenance['texts'][key]['sha256']
    final_forms=dict(zip('ךםןףץ','כמנפצ'))
    assert set(ht)<=set(d['hebrew_alphabet'])|set(final_forms)
    assert set(gt)==set(d['greek_alphabet'])
    folded=ht.translate(str.maketrans(final_forms))
    assert len(folded)==len(ht) and set(folded)==set(d['hebrew_alphabet'])
    h=[d['hebrew_alphabet'].index(c) for c in folded]
    N=len(gt)//16*16; g=[d['greek_alphabet'].index(c) for c in gt[:N]]
    refs=json.loads(packet['reference-orders.json'])
    assert len(refs)==supplied['reference_count']==4999
    assert all(len(p)==16 and all(type(v) is int for v in p) and sorted(p)==list(range(16)) for p in refs)
    regenerated=regenerate_references()
    assert regenerated==refs, 'Supplied generator schedule does not reproduce reference orders'
    log('Input digests, lengths, alphabets, parameter grid, all permutations and generator schedule verified.')
    validation={
        'all_declared_sha256_match':True,'input_manifest_itself_sha256':ledger['manifest.json']['sha256'],
        'hebrew_letters':len(ht),'greek_letters':len(gt),'covered_greek_letters':N,'unit_length':N//16,
        'omitted_greek_letters':gt[N:],'omitted_greek_count':len(gt)-N,
        'hebrew_alphabet_before_folding':''.join(sorted(set(ht))),'hebrew_final_form_counts':{c:ht.count(c) for c in final_forms},
        'folded_hebrew_alphabet':d['hebrew_alphabet'],'greek_alphabet':d['greek_alphabet'],
        'all_references_are_permutations':True,'reference_count':len(refs),
        'distinct_reference_orders':len(set(map(tuple,refs))),
        'identity_reference_orders':sum(p==list(range(16)) for p in refs),
        'generator_schedule_matches_every_order':True,'generator_seed':2026091803,
        'reference_order_packed_sha256':sha(bytes(v for p in refs for v in p)),
        'upstream_files_not_read':True,'upstream_provenance_entries':len(provenance['source_entries']),
        'upstream_source_manifest_declared_sha256':provenance['source_manifest_sha256'],
        'limitation':'Raw upstream editions and upstream source manifest were not independently audited: only the supplied packet was read.'}
    save('input-files-read.json',{'directory':str(INPUTS),'files':ledger})
    save('input-validation.json',validation)
    cxx=shutil.which('clang++') or shutil.which('g++')
    if cxx is None: raise RuntimeError('No C++ compiler found')
    compiler_version=command([cxx,'--version'])
    environment={'started_utc':started,'python_version':sys.version,'python_executable':sys.executable,'platform':platform.platform(),
                 'machine':platform.machine(),'byte_order':sys.byteorder,'compiler_path':cxx,'compiler_version':compiler_version,
                 'third_party_python_dependencies':[], 'environment_variables_used':{'PATH':os.environ.get('PATH','')},
                 'working_directory':str(HERE)}
    save('environment.json',environment)
    engine=HERE/'engine'
    command([cxx,'-std=c++17','-O3','-Wall','-Wextra','-Wpedantic',HERE/'engine.cpp','-o',engine])
    tests=[synthetic_check(engine,37,7,901),synthetic_check(engine,173,3,902)]
    save('consistency-checks.json',{'synthetic_exhaustive_python_checks':tests,'real_exhaustive_literal_observed_check':'The C++ engine recomputes all 3072 observed counts directly and checks equality.',
                                  'intercept_conservation':'All 24 intercepts sum to N observed matches, zero centered score, and unit length in every matrix cell.'})
    log('Both synthetic datasets passed complete matrix, observed-count, reference-maximum and tie checks.')
    payload(HERE/'prepared-input.bin',h,g,refs)
    command([engine,HERE/'prepared-input.bin',HERE/'observed'])
    rows=read_csv('observed-rules.csv'); reference_rows=read_csv('observed-reference-maxima.csv')
    assert len(rows)==3072 and len(reference_rows)==4999
    integer_rows=[{k:int(v) for k,v in row.items()} for row in rows]
    best_score=max(row['centered_score'] for row in integer_rows)
    best_raw=max(row['matches'] for row in integer_rows)
    score_ties=[row for row in integer_rows if row['centered_score']==best_score]
    raw_ties=[row for row in integer_rows if row['matches']==best_raw]
    ref_maxima=[int(row['maximum_centered_score']) for row in reference_rows]
    inclusive=sum(v>=best_score for v in ref_maxima)
    greater=sum(v>best_score for v in ref_maxima); equal=sum(v==best_score for v in ref_maxima)
    p_num=inclusive+1; p_den=len(refs)+1
    unique=len(score_ties)==1
    zero_errors=unique and score_ties[0]['incorrect']==0
    parameters=rule_parameters()
    rule_json=[]
    for row,params in zip(integer_rows,parameters):
        assert tuple(row[k] for k in ('direction','offset','multiplier','intercept'))==params
        canonical=json.dumps({k:row[k] for k in ('direction','offset','multiplier','intercept')},sort_keys=True,separators=(',',':'))
        rule_json.append(canonical)
    (HERE/'canonical-rules.jsonl').write_text('\n'.join(rule_json)+'\n',encoding='utf-8')
    summary={
        'experiment':'EXP-001','family':'FAM-001','definition_version':d['version'],'independence':'Authored from the input packet only; original results were not requested or read before sealing.',
        'rule_count':len(rows),'reference_count':len(refs),'hebrew_length':len(h),'greek_full_length':len(gt),'covered_greek_length':N,'unit_length':N//16,
        'omitted_greek_count':len(gt)-N,'omitted_greek_letters':gt[N:],
        'maximum_centered_score':best_score,'all_maximum_score_rules':score_ties,
        'best_raw_match_count':best_raw,'all_best_raw_match_rules':raw_ties,
        'inclusive_exceedances':inclusive,'strict_exceedances':greater,'equal_reference_maxima':equal,
        'family_p_fraction':f'{p_num}/{p_den}','family_p':p_num/p_den,
        'reference_maximum_min':min(ref_maxima),'reference_maximum_max':max(ref_maxima),
        'exact_candidate_screen':{'family_p_at_most_0_01':100*p_num<=p_den,'exactly_one_best_scoring_rule':unique,'zero_incorrect_predictions':zero_errors,
                                  'passes':100*p_num<=p_den and unique and zero_errors},
        'description_cost':{'conditional_parameter_bits':d['conditional_parameter_code_bits'],
                            'canonical_rule_json_format':'UTF-8, sorted keys direction/intercept/multiplier/offset, compact separators, no trailing newline per record; parameter object conditional on supplied grammar.',
                            'maximum_score_rule_json':[{'rule_index':r['rule_index'],'json':rule_json[r['rule_index']],'bytes':len(rule_json[r['rule_index']].encode())} for r in score_ties],
                            'grammar_file_bytes':len(packet['FAM-001-definition.json']),'decoder_cpp_source_bytes':(HERE/'engine.cpp').stat().st_size,
                            'runner_python_source_bytes':(HERE/'run.py').stat().st_size,
                            'input_selection_normalization_protocol_readme_bytes':len(packet['README.md']),
                            'provided_provenance_bytes':len(packet['provenance.json']),'provided_input_manifest_bytes':len(packet['manifest.json']),
                            'upstream_source_manifest_bytes':'unavailable in permitted input packet; only its declared SHA-256 is present',
                            'not_absolute_kolmogorov_complexity':True},
        'limits':[
            'Computational replication on the same supplied transcriptions, not validation on held-out data or a palaeographic audit.',
            'Source provenance and historical normalization are supplied declarations; their raw upstream files were outside permitted input scope.',
            'The 4999 permutations reproduce a historical PRNG stream schedule and are not a newly independent random sample.',
            'The null conditions on the observed 16 Greek units and predictions; it is not a universal model of human authorship.',
            'No alternative normalization, boundary, target selection or rule family was tried.',
            'No operational ambiguity remained in the supplied formulas. Rule indices and reference indices are reported zero-based; ties are retained.',
            'The supplied definition does not prescribe a canonical rule-object schema; the compact four-parameter encoding reported here is explicit and conditional on that grammar.'
        ]}
    save('summary.json',summary)
    report=f'''# Réplication indépendante EXP-001 / FAM-001

Implémentation neuve écrite exclusivement à partir du dossier d’entrée. Aucun ancien code, module `biblelab`, test, rapport, score ou historique du projet n’a été consulté. Les résultats sont figés avec leurs empreintes avant communication.

## Entrées et calcul

- Les six empreintes déclarées et les deux longueurs déclarées concordent. Le manifeste d’entrée lui-même possède une empreinte consignée séparément.
- Hébreu : {len(h):,} lettres ; cinq formes finales rabattues. Grec : {len(gt):,} lettres ; alphabet complet de 24 lettres.
- Couverture : {N:,} lettres, soit 16 unités de {N//16:,} lettres. Les {len(gt)-N} lettres finales `{gt[N:]}` sont omises conformément au protocole.
- Les 4 999 listes sont des permutations valides. La reconstruction exacte du calendrier `random.Random(2026091803)` reproduit chaque liste.
- Les 3 072 règles suivent exactement l’ordre direction, décalage, multiplicateur, intercept. Le voisin hébreu reste v+1 dans l’ordre original, y compris en parcours inverse.
- Les matrices de comptes sont calculées par histogrammes entiers. Les 3 072 comptes observés sont ensuite recomptés directement lettre par lettre. Deux corpus synthétiques contrôlent également toutes les cellules de matrice avec une implémentation Python directe ; les maxima et les ex aequo sont comparés intégralement.

## Résultats

- Maximum du score centré entier : **{best_score}**.
- Règles ex aequo au maximum : **{len(score_ties)}**, indices {', '.join(str(r['rule_index']) for r in score_ties)}.
- Meilleur nombre brut de correspondances : **{best_raw} / {N}**, soit {best_raw/N:.8%}. Tous ses ex aequo figurent dans `summary.json`.
- Dépassements inclusifs parmi les 4 999 maxima : **{inclusive}** ({greater} stricts ; {equal} égaux).
- Probabilité de famille Monte-Carlo : **({inclusive}+1)/(4999+1) = {p_num}/{p_den} = {p_num/p_den:.10g}**.
- Filtre exact déclaré : **{'PASSÉ' if summary['exact_candidate_screen']['passes'] else 'NON PASSÉ'}**. Détail dans `summary.json` ; aucune autre règle n’est sélectionnée par le compte brut.

Le fichier `observed-rules.csv` contient les 3 072 scores, comptes corrects et incorrects et sommes matricielles. `observed-reference-maxima.csv` contient chacun des 4 999 maxima et tous ses indices ex aequo. `observed-matrices.bin` contient les 3 072 matrices 16 × 16, uint32 little-endian, ordre règle puis unité prédite puis unité grecque. Les indices sont à base zéro.

## Description et limites

Le coût annoncé de 12 bits est conditionnel à la grammaire fixée. Les objets canoniques des règles, les tailles de grammaire, code de décodage, protocole et provenance sont consignés dans `summary.json` et `canonical-rules.jsonl`. Aucun schéma canonique d’objet de règle n’était imposé : nous utilisons explicitement les quatre paramètres triés, en JSON compact. Le manifeste des sources original n’est pas inclus dans les entrées autorisées : son empreinte est fournie mais sa taille et son contenu ne sont pas vérifiés ici.

Il s’agit d’une réplication informatique des mêmes transcriptions, sans données réservées ni audit paléographique. Les sources amont et la normalisation historique sont des déclarations du dossier ; seuls les corpus fournis sont vérifiés. Les permutations reconstituent un flux historique, pas un nouvel échantillon indépendant. Le modèle nul permute uniquement les unités grecques observées et ne représente pas tous les procédés de rédaction humains. Aucune autre normalisation, frontière, cible ou famille n’a été essayée. Aucune ambiguïté opérationnelle ne subsiste dans la formule fournie.

## Reproduction et scellement

Voir `REPRODUCE.md`, `environment.json`, `execution.log` et `input-files-read.json`. Le fichier `OUTPUT-SHA256.json` couvre chaque fichier de ce répertoire sauf lui-même ; son empreinte doit être communiquée hors du manifeste. Le programme refuse d’écraser des sorties déjà scellées.
'''
    (HERE/'REPORT.md').write_text(report,encoding='utf-8')
    finished=datetime.now(timezone.utc).isoformat()
    log('Independent execution and all consistency checks completed UTC '+finished)
    log('Final action: freeze every output file in OUTPUT-SHA256.json; no original results consulted.')
    files={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='OUTPUT-SHA256.json'}
    save('OUTPUT-SHA256.json',{'schema':'independent-output-seal-v1','sealed_utc':finished,'excludes_only':'OUTPUT-SHA256.json','files':files})
    # Do not append to the frozen log or modify any other output after sealing.
    print('SEALED OUTPUT-SHA256.json SHA256 '+sha((HERE/'OUTPUT-SHA256.json').read_bytes()),flush=True)

if __name__=='__main__': main()
