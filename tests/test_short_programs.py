import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from biblelab.sources import ROOT
from biblelab.short_programs import decode,predict,build_engine,scan,validate,assignments,plant,BOUNDS,KINDS
from biblelab.contextual import build_engine as old_build,scan as old_scan
from biblelab.shared_search import save_input
sys.path.insert(0,str(ROOT/'tools'))
from validate_contextual import build as oracle_build


class ShortProgramsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=build_engine()[0];cls.old=old_build()[0]
        # The checked build cache avoids overwriting a running verifier binary.
        cls.oracle=oracle_build('short_programs_oracle')[0]

    def compare(self,left,right,minimum=4,cap=10,draws=0):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.txt';save_input(path,left,right)
            result=scan(self.binary,path,draws,91,minimum,cap);validate(result,left,right)
            checked=json.loads(subprocess.check_output([str(self.oracle),str(path),str(minimum),str(cap)],text=True))
            for key in ('score','compatible_seed_pairs','rule_scores','maximizing_rule_ids','opcode_maxima'):
                self.assertEqual(result[key],checked[key],key)
            original=old_scan(self.old,path,draws,91,minimum,cap)
            self.assertEqual(original['rule_scores'],result['rule_scores'][:768])
            for mode in ('words','word_types'):
                self.assertEqual(original['reference_scores'][mode],result['reference_opcode_maxima'][mode]['pair'])
        return result

    def test_all_7008_catalog_entries_and_declared_strata(self):
        native=json.loads(subprocess.check_output([str(self.binary),'--catalog'],text=True))
        self.assertEqual(native,[decode(r) for r in range(7008)])
        self.assertEqual([sum(p['kind']==kind for p in native) for kind in KINDS],[768,3840,2400])
        for a,b,c in BOUNDS:
            self.assertTrue(all(p['direction']==1 for p in native[a:b]))
            self.assertTrue(all(p['direction']==-1 for p in native[b:c]))

    def test_all_rule_scores_match_literal_oracle_and_old_baseline(self):
        rng=random.Random(1115)
        for rule in (0,455,768,1680,3125,4607,4608,5303,6200,7007):
            size=4 if rule%2 else 22
            left=[dict(group=i,words=[''.join(chr(65+rng.randrange(size)) for _ in range(15))]) for i in range(4)]
            p=decode(rule);right=[dict(group=i,words=[predict(u['words'][0][::p['direction']],rule)]) for i,u in enumerate(left)]
            result=self.compare(left,right)
            self.assertEqual(result['rule_scores'][rule],10)

    def test_reference_stream_baseline_is_paired_not_a_new_replication(self):
        rng=random.Random(77)
        left=[dict(group=i,words=[''.join(rng.choice('AB') for _ in range(17))]) for i in range(4)]
        right=[dict(group=i,words=[''.join(rng.choice('AB') for _ in range(4)) for _ in range(4)]) for i in range(4)]
        self.compare(left,right,minimum=4,cap=10,draws=9)

    def test_constants_keep_292_tied_codes_and_fit_prospective_guard(self):
        left=[dict(group=i,words=['A'*34]) for i in range(3)];right=[dict(group=i,words=['A'*8]*4) for i in range(3)]
        result=self.compare(left,right,minimum=8,cap=32,draws=2)
        self.assertEqual(result['maximizing_rule_ids'],list(range(0,7008,24)))
        self.assertEqual(result['indexed_source_starts'],22296)
        self.assertEqual(result['compatible_seed_pairs'],1672200)
        self.assertEqual(result['reference_scores'],dict(words=[32,32],word_types=[32,32]))

    def test_third_letter_is_consumed_even_with_zero_middle_coefficient(self):
        # forward triple a=-2,b=0,t=-2, intercept0
        rule=768+2*4*24;p=decode(rule);self.assertEqual(p['linear'],[-2,0,-2])
        left=[dict(group=i,words=['A'*9]) for i in range(3)];right=[dict(group=i,words=['A'*8]) for i in range(3)]
        result=self.compare(left,right,minimum=8,cap=8)
        self.assertEqual(result['rule_scores'][rule],0);self.assertEqual(result['opcode_maxima']['pair'],8)
        for u in left:u['words']=['A'*10]
        self.assertEqual(self.compare(left,right,minimum=8,cap=8)['rule_scores'][rule],8)

    def test_repeated_group_labels_never_supply_three_independent_passages(self):
        left=[dict(group=0,words=['A'*12]) for _ in range(3)];right=[dict(group=i,words=['A'*10]) for i in range(3)]
        self.assertEqual(self.compare(left,right)['score'],0)

    def test_planting_uses_span_and_preserves_word_boundaries_in_both_directions(self):
        left=[dict(group=i,words=['ABCDEFGHIJKLMNOPQRSTUV'*2]) for i in range(4)]
        right=[dict(group=i,words=['ABCDE','FGHIJKL','MNOPQRST','UVWX'*9]) for i in range(4)]
        plans=assignments(left,right,dict(rule_seed=2026099001,reference_seed_base=2026100000))
        self.assertEqual(len(plans),60)
        for kind in KINDS:
            selected=[a for a in plans if a['program']['kind']==kind]
            self.assertEqual([a['program']['direction'] for a in selected],[1,-1]*10)
        for a in plans:
            modified=plant(left,right,a,32);p=a['program']
            for before,after in zip(right,modified):self.assertEqual(list(map(len,before['words'])),list(map(len,after['words'])))
            for c in a['coordinates']:
                q=left[c['left_unit']]['words'][0][::p['direction']][:32+p['span']-1]
                self.assertEqual(predict(q,p['rule_id']),''.join(modified[c['right_unit']]['words'])[16:48])

    def test_explicit_failure_does_not_return_a_truncated_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'guard.txt';save_input(path,[dict(group=i,words=['A'*60]) for i in range(3)],
                                                       [dict(group=i,words=['A'*59]) for i in range(3)])
            p=subprocess.run([str(self.binary),str(path),'8','32','0','1'],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertIn('compatible seed resource guard exceeded',p.stderr)
            self.assertEqual(p.stdout,'')

    def test_independent_matching_count_matches_all_small_graphs(self):
        code='''#define SHORT_PROGRAM_ORACLE_NO_MAIN
#include "short_programs_oracle.cpp"
int main(){for(int mask=0;mask<512;++mask){std::vector<OracleEdge> e;
for(int x=0;x<9;++x)if(mask&(1<<x))e.push_back({x/3,x%3,8});
bool expected=false;for(auto a:e)for(auto b:e)for(auto c:e)
if(a.left!=b.left&&a.left!=c.left&&b.left!=c.left&&a.right!=b.right&&a.right!=c.right&&b.right!=c.right)expected=true;
if(three_edges(e,8)!=expected||three_edges(e,9))return 1;}return 0;}
'''
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'test.cpp';source.write_text(code);binary=Path(d)/'check'
            subprocess.run([shutil.which('clang++'),'-std=c++17','-O1','-I',str(ROOT/'native'),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)


if __name__=='__main__':unittest.main()
