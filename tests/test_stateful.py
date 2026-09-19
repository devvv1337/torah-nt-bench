from itertools import combinations,product
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from biblelab.stateful import decode,predict,build_engine,scan,validate,execute,plant,covers
from biblelab.shared_search import save_input
from biblelab.registry import canonical,read_events
from biblelab.sources import digest


def equation_output(text,rule):
    p=decode(rule);values=[ord(c)-65 for c in text]
    return ''.join(chr(65+(sum(p['a']*values[j]*pow(p['b'],i-j) for j in range(i+1))
        +p['c']*sum(pow(p['b'],j) for j in range(i+1)))%24) for i in range(len(values)))


def brute(left,right,minimum,cap):
    scores=[];seeds=0
    for rule in range(768):
        p=decode(rule);edges={}
        for l,u in enumerate(left):
            text=''.join(u['words'])[::p['direction']]
            for s in range(len(text)-minimum+1):
                predicted=equation_output(text[s:s+cap],rule)
                for r,v in enumerate(right):
                    greek=''.join(v['words'])
                    for t in range(len(greek)-minimum+1):
                        if predicted[:minimum]!=greek[t:t+minimum]:continue
                        seeds+=1;K=minimum
                        while K<len(predicted) and t+K<len(greek) and predicted[K]==greek[t+K]:K+=1
                        edge=u['group'],v['group'];edges[edge]=max(edges.get(edge,0),K)
        best=0
        for chosen in combinations(edges,3):
            if len({e[0] for e in chosen})==len({e[1] for e in chosen})==3:best=max(best,min(edges[e] for e in chosen))
        scores.append(best)
    return scores,seeds


class StatefulTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.binary,_=build_engine();cls.oracle,_=build_engine(oracle=True)

    def compare(self,left,right,minimum=8,cap=32,draws=0):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.txt';save_input(path,left,right)
            a=scan(self.binary,path,draws,2026111007,minimum,cap);validate(a,left,right,minimum,cap)
            b=json.loads(subprocess.check_output([str(self.oracle),str(path),str(minimum),str(cap)],text=True))
            for key in ('score','rule_scores','maximizing_rule_ids','compatible_seed_pairs'):self.assertEqual(a[key],b[key],key)
        return a

    def test_all_codes_closed_form_difference_identity_and_distinct_functions(self):
        signatures=[];sample='ABCVUDKL'
        for rule in range(768):
            p=decode(rule);out=predict(sample,rule);self.assertEqual(out,equation_output(sample,rule))
            prev=0
            for h,g in zip(sample,out):
                self.assertEqual((ord(g)-65-p['b']*prev)%24,(p['a']*(ord(h)-65)+p['c'])%24);prev=ord(g)-65
            signatures.append(tuple(predict(s[::p['direction']],rule) for s in ('AA','AB','BA')))
        self.assertEqual(len(set(signatures)),768)

    def test_weighted_keys_eliminate_only_the_single_fixed_intercept(self):
        h='ABVDCELK'
        for rule in range(768):
            p=decode(rule);g=predict(h,rule);z=predict(h,rule-rule%24);S=0
            for i in range(len(h)):
                S=(1+p['b']*S)%24
                self.assertEqual((ord(g[i])-65-S*(ord(g[0])-65))%24,(ord(z[i])-65-S*(ord(z[0])-65))%24)
            self.assertEqual((ord(g[0])-ord(z[0]))%24,p['c'])

    def test_state_is_reset_at_each_candidate_start(self):
        self.assertEqual(predict('BC',240),'BD')
        self.assertEqual(predict('C',240),'C')
        self.assertNotEqual(predict('BC',240)[1:],predict('C',240))
        left=[dict(group=i,words=['BCDEFGHIKL']) for i in range(3)]
        target=predict('CDEFGHIK',240);right=[dict(group=i,words=[target]) for i in range(3)]
        r=self.compare(left,right,cap=8);self.assertEqual(r['rule_scores'][240],8)

    def test_exhaustive_small_windows_match_full_parameter_and_triple_enumeration(self):
        texts=[''.join(x) for x in product('AB',repeat=3)]
        left=[dict(group=i//2,words=[s]) for i,s in enumerate(texts)]
        right=[dict(group=i//2,words=[s[:1],s[1:]]) for i,s in enumerate(reversed(texts))]
        result=self.compare(left,right,2,3);scores,seeds=brute(left,right,2,3)
        self.assertEqual(result['rule_scores'],scores);self.assertEqual(result['compatible_seed_pairs'],seeds)

    def test_random_offsets_directions_and_prefixes_match_other_scorer(self):
        rng=random.Random(2026111010)
        for case in range(16):
            alphabet='AB' if case%3==0 else 'ABCDEFGHIJKLMNOPQRSTUV'
            left=[dict(group=i,words=[''.join(rng.choice(alphabet) for _ in range(15))]) for i in range(4)]
            right=[dict(group=i,words=[''.join(rng.choice('ABCDEFGHIJKLMNOPQRSTUVWX') for _ in range(4)) for _ in range(4)]) for i in range(4)]
            rule=rng.randrange(768);p=decode(rule)
            if case%2:
                for i in range(3):
                    source=left[i]['words'][0][::p['direction']][i:i+8]
                    raw=''.join(right[i]['words']);raw=raw[:3]+predict(source,rule)+raw[11:]
                    right[i]['words']=[raw[j:j+4] for j in range(0,16,4)]
            result=self.compare(left,right,cap=12)
            if case%2:self.assertGreaterEqual(result['rule_scores'][rule],8)

    def test_same_group_occurrences_cannot_form_three_independent_group_pairs(self):
        left=[dict(group=0,words=['A'*16]) for _ in range(4)]
        right=[dict(group=i,words=['A'*16]) for i in range(4)]
        self.assertEqual(self.compare(left,right)['score'],0)

    def test_constant_and_periodic_outputs_keep_ties_and_unchanged_references(self):
        cases=[('A'*32,'A'*8),('A'+'B'*7+('R'+'B'*7)*3,'ABCDEFGH')]
        for source,word in cases:
            left=[dict(group=i,words=[source]) for i in range(3)];right=[dict(group=i,words=[word]*4) for i in range(3)]
            result=self.compare(left,right,draws=5);self.assertEqual(result['score'],32)
            self.assertTrue(all(values==[32]*5 for values in result['reference_scores'].values()))
            if source=='A'*32:self.assertEqual(result['maximizing_rule_ids'],list(range(0,768,24)))
            else:self.assertEqual(result['rule_scores'][240],32)

    def test_index_and_seed_guards_fail_without_truncated_results(self):
        cases=[([dict(group=0,words=['A'*160000])],[],'indexed start'),
               ([dict(group=i,words=['A'*200]) for i in range(3)],[dict(group=i,words=['A'*200]) for i in range(3)],'compatible seed')]
        for left,right,label in cases:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'guard.txt';save_input(path,left,right)
                p=subprocess.run([str(self.binary),str(path),'8','32','0','0'],capture_output=True,text=True)
                self.assertNotEqual(p.returncode,0);self.assertIn(label,p.stderr);self.assertEqual(p.stdout,'')

    def test_receipts_round_trip_and_resume_without_another_scan(self):
        left=[dict(group=i,words=['A'*16]) for i in range(3)];right=[dict(group=i,words=['A'*4]*4) for i in range(3)]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'data/fixture.txt';identity=dict(fixture=True)
            record=execute(root,self.binary,path,left,right,3,17,identity)
            envelope=json.loads(path.with_suffix('.receipt.json').read_text())
            self.assertEqual(envelope['sha256'],digest(canonical(envelope['record'])))
            events=read_events(root/'registry/events.jsonl')
            with patch('biblelab.stateful.scan',side_effect=AssertionError('must not rerun')):
                self.assertEqual(execute(root,self.binary,path,left,right,3,17,identity),record)
                with self.assertRaises(AssertionError):execute(root,self.binary,path,left,right,3,18,identity)
            self.assertEqual(events,read_events(root/'registry/events.jsonl'))

    def test_plant_consumes_exactly_K_letters_and_preserves_word_boundaries(self):
        left=[dict(group=i,words=['ABCDEFGHIJKLMNOPQRSTUV'*2]) for i in range(3)]
        right=[dict(group=i,words=['ABCD']*12) for i in range(3)]
        for rule in (0,240,383,384,624,767):
            plan=dict(decode(rule),coordinates=[dict(left_unit=i,left_oriented_start=2,right_unit=i,right_start=16) for i in range(3)])
            changed=plant(left,right,plan,32)
            for i in range(3):
                raw=''.join(changed[i]['words']);expected=equation_output(left[i]['words'][0][::plan['direction']][2:34],rule)
                self.assertEqual(raw[16:48],expected);self.assertEqual(raw[:16],''.join(right[i]['words'])[:16])
                self.assertEqual(list(map(len,changed[i]['words'])),list(map(len,right[i]['words'])))
        plan=dict(rule_id=240,coordinates=[dict(left_unit=i,left_oriented_start=1,right_unit=i,right_start=1) for i in range(3)])
        result=dict(witnesses=[dict(rule_id=240,hits=[dict(left_unit=i,right_unit=i,left_oriented_start=0,right_start=0,length=16) for i in range(3)])])
        self.assertFalse(covers(result,plan,8))


if __name__=='__main__':unittest.main()
