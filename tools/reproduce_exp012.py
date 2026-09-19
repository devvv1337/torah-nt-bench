"""Reproduce EXP-012 in a fresh copy of this release; compare all numerical outputs."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from biblelab.modern_local import source_check,prepare,run,check,sha,PROTOCOL,REPORT
from biblelab.registry import append
assert not (ROOT/'data/derived/modern-local-v1').exists(), 'Use a fresh release directory.'
source_check(ROOT,fetch=True)
actual=prepare(ROOT)
spec=json.loads((ROOT/PROTOCOL).read_text())
assert actual==spec['input']
append(ROOT/'registry/events.jsonl','protocol_frozen',{'sha256':sha(ROOT/PROTOCOL),'role':'reproduction of already exposed EXP-012; no new scientific trial'})
run(ROOT)
check(ROOT)
observed=json.loads((ROOT/REPORT).read_text())
expected=json.loads((ROOT/'expected/exp012/result.json').read_text())
for key in ('maximum','left_oriented_starts','right_starts','start_pairs','equal_seed_pairs','maximum_occurrences','reference_maxima','references','numerical_alert','verdict'):
    assert observed[key]==expected[key], key
print('All observed maxima and all 398 reference maxima agree with the released result.')
