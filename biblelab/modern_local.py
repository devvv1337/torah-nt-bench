"""Edition-only adapter for unchanged FAM-002; no manuscript eligibility gate."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

from .sources import ROOT, TORAH, NT, digest, write_json
from .letters import HEBREW, GREEK, HEBREW_FINAL, normalize
from .editions import oshb, sbl, OSIS
from .registry import append, read_events

DIRECTORY = 'data/derived/modern-local-v1'
PROTOCOL = 'protocol/modern-editions-fam002-v1.json'
REPORT = 'reports/modern-local-exp012-v1.json'
FIELDS = ('left_unit', 'direction', 'left_start', 'left_end', 'right_unit', 'right_start', 'length')


def sha(path):
    return digest(Path(path).read_bytes())


def encode(text, language):
    alphabet = HEBREW if language == 'he' else GREEK
    if language == 'he':
        text = text.translate(HEBREW_FINAL)
    return ''.join(chr(65 + alphabet.index(c)) for c in text)


def independent_letters(raw, language):
    """Separate direct normalization used to cross-check each extracted verse."""
    decomposed = unicodedata.normalize('NFD', raw)
    if language == 'he':
        text = ''.join(c for c in decomposed if '\u05d0' <= c <= '\u05ea')
        return text.translate(str.maketrans('ךםןףץ', 'כמנפצ'))
    return ''.join(c for c in decomposed.replace('\u0345', 'ι').lower().replace('ς', 'σ') if c in GREEK)


def source_check(root, fetch=False):
    lock = json.loads((root / 'protocol/modern-edition-source-lock-v1.json').read_text())
    expected = {f'data/raw/oshb/wlc/{b}.xml' for b in TORAH}
    expected |= {f'data/raw/sblgnt/data/sblgnt/xml/{b}.xml' for b in NT}
    assert len(lock['files']) == 32 and {r['path'] for r in lock['files']} == expected
    for row in lock['files']:
        path = root / row['path']
        if not path.exists() and fetch:
            with urllib.request.urlopen(row['url'], timeout=60) as response:
                data = response.read()
            assert digest(data) == row['sha256'], row['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        assert sha(path) == row['sha256'], row['path']
    return {r['path']: r['sha256'] for r in lock['files']}


def prepare(root=ROOT):
    source_hashes = source_check(root)
    left, right = [], []
    for book in TORAH:
        path = root / f'data/raw/oshb/wlc/{book}.xml'
        verses, _ = oshb(path)
        independent = {}
        for verse in ET.parse(path).getroot().iter(OSIS + 'verse'):
            raw = ''.join(''.join(w.itertext()) for w in list(verse) if w.tag == OSIS + 'w')
            independent[verse.attrib['osisID']] = independent_letters(raw, 'he')
        assert len(independent) == len(verses)
        for verse in verses:
            text = ''.join(w['letters'] for w in verse['words']).translate(HEBREW_FINAL)
            assert text == independent[verse['ref']]
            left.append({'id': verse['ref'], 'group': verse['ref'], 'encoded': encode(text, 'he')})
    for book in NT:
        path = root / f'data/raw/sblgnt/data/sblgnt/xml/{book}.xml'
        verses, _ = sbl(path)
        independent, current = {}, None
        for element in ET.parse(path).getroot().iter():
            if element.tag == 'verse-number':
                current = element.attrib['id']
                assert current not in independent
                independent[current] = []
            elif element.tag == 'w':
                assert current is not None
                independent[current].append(independent_letters(''.join(element.itertext()), 'grc'))
        assert len(independent) == len(verses)
        for verse in verses:
            words = [w['letters'] for w in verse['words'] if w['letters']]
            assert words == [w for w in independent[verse['ref']] if w]
            right.append({'id': verse['ref'], 'group': verse['ref'], 'encoded_words': [encode(w, 'grc') for w in words]})
    assert len({u['id'] for u in left}) == len(left)
    assert len({u['id'] for u in right}) == len(right)
    directory = root / DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    units = directory / 'units.json'
    input_path = directory / 'input.txt'
    assert not units.exists() and not input_path.exists(), 'Preparation is immutable; inspect existing files instead.'
    write_json(units, {'left': left, 'right': right})
    lines = [f'{len(left)} {len(right)}'] + [u['encoded'] for u in left]
    lines += [' '.join(u['encoded_words']) for u in right]
    input_path.write_text('\n'.join(lines) + '\n', encoding='ascii')
    counts = {'left_units': len(left), 'left_letters': sum(len(u['encoded']) for u in left),
              'right_units': len(right), 'right_letters': sum(sum(map(len, u['encoded_words'])) for u in right)}
    receipt = {'source_hashes': source_hashes, 'counts': counts, 'input_path': str(input_path.relative_to(root)),
               'input_sha256': sha(input_path), 'units_path': str(units.relative_to(root)), 'units_sha256': sha(units),
               'all_verses_independently_reextracted': True, 'no_dss_files_read': True,
               'normalization': 'FAM-002 original: Hebrew finals folded; Greek U+0345 retained as iota, final sigma folded.',
               'boundaries': 'All verses retained individually in original book order; no cross-verse match, no chronological filter.'}
    write_json(directory / 'preparation.json', receipt)
    return receipt


def run(root=ROOT):
    protocol_path = root / PROTOCOL
    spec = json.loads(protocol_path.read_text())
    events = read_events(root / 'registry/events.jsonl')
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha(protocol_path) for e in events)
    assert not any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == spec['id'] for e in events), 'Do not restart a begun evaluation.'
    assert not (root / REPORT).exists()
    assert source_check(root) == spec['input']['source_hashes']
    for path, expected in spec['code_hashes'].items():
        assert sha(root / path) == expected, path
    input_path = root / spec['input']['input_path']
    assert sha(input_path) == spec['input']['input_sha256']
    assert sha(root / spec['input']['units_path']) == spec['input']['units_sha256']
    compiler = shutil.which('clang++')
    assert compiler, 'C++17 compiler required'
    directory = root / DIRECTORY
    binary = directory / 'local_match'
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic']
    subprocess.run([compiler, *flags, str(root / 'native/local_match.cpp'), '-o', str(binary)], check=True)
    append(root / 'registry/events.jsonl', 'modern_target_started', {
        'id': spec['id'], 'family': 'FAM-002', 'protocol_sha256': sha(protocol_path),
        'input_sha256': sha(input_path), 'new_target_evaluations': 1, 'cumulative_started': 12,
        'compiler': subprocess.check_output([compiler, '--version'], text=True), 'binary_sha256': sha(binary)})
    raw_path = directory / 'raw-result.json'
    error_path = directory / 'stderr.txt'
    print('EXP-012 started: complete modern Torah/NT, frozen FAM-002, 199 draws per model.', flush=True)
    with raw_path.open('w') as output, error_path.open('w') as error:
        result = subprocess.run([str(binary), str(input_path), str(spec['minimum_length']), str(spec['maximum_length']),
                                 str(spec['reference_draws_per_model']), str(spec['seed'])], stdout=output, stderr=error)
    if result.returncode:
        append(root / 'registry/events.jsonl', 'modern_target_failed', {'id': spec['id'], 'exit_code': result.returncode,
            'partial_output_sha256': sha(raw_path), 'stderr_sha256': sha(error_path), 'verdict': 'ouverte; incomplete execution'})
        raise RuntimeError('Native evaluation failed; partial output preserved.')
    raw = json.loads(raw_path.read_text())
    references = {}
    for name, values in raw['reference_maxima'].items():
        assert len(values) == spec['reference_draws_per_model']
        exceedances = sum(v >= raw['maximum'] for v in values)
        references[name] = {'draws': len(values), 'exceedances': exceedances, 'p': (1 + exceedances) / (1 + len(values))}
    alert = raw['maximum'] >= spec['candidate_screen']['minimum_length'] and all(
        r['p'] <= spec['candidate_screen']['p_each_model_max'] for r in references.values())
    report = {'id': spec['id'], 'family': 'FAM-002', 'completed_utc': datetime.now(timezone.utc).isoformat(),
              'protocol_sha256': sha(protocol_path), 'input_sha256': sha(input_path), 'counts': spec['input']['counts'],
              'raw_result_path': str(raw_path.relative_to(root)), 'raw_result_sha256': sha(raw_path),
              'runtime': platform.platform(), **raw, 'references': references, 'numerical_alert': alert,
              'candidate_retained': False, 'internal_verification_pending': True,
              'historical_certification_required_to_compute': False,
              'verdict': 'ouverte' if alert else 'rien', 'verdict_pending_internal_check': True,
              'scope': 'Complete modern editions, within-verse windows, unchanged FAM-002; no universal absence claim.',
              'confirmatory_p': False, 'independent_scientific_replication': False}
    write_json(root / REPORT, report)
    append(root / 'registry/events.jsonl', 'modern_target_completed', {'id': spec['id'], 'report': REPORT,
        'report_sha256': sha(root / REPORT), 'maximum': raw['maximum'], 'numerical_alert': alert, 'cumulative_completed': 12})
    return {k: report[k] for k in ('id', 'maximum', 'references', 'numerical_alert', 'verdict')}


def predecessor_pattern(text):
    previous, output = {}, []
    for i, character in enumerate(text):
        output.append(i - previous[character] if character in previous else 0)
        previous[character] = i
    return tuple(output)


def all_matches(left, right, length):
    indexed = defaultdict(list)
    for li, unit in enumerate(left):
        original = unit['encoded']
        for direction in (1, -1):
            text = original if direction == 1 else original[::-1]
            for start in range(max(0, len(text) - length + 1)):
                native = start if direction == 1 else len(text) - start - length
                indexed[predecessor_pattern(text[start:start + length])].append((li, direction, native, native + length))
    hits = set()
    for ri, unit in enumerate(right):
        text = ''.join(unit['encoded_words'])
        for start in range(max(0, len(text) - length + 1)):
            for location in indexed.get(predecessor_pattern(text[start:start + length]), ()):
                hits.add((*location, ri, start, length))
    return hits


def check(root=ROOT):
    spec = json.loads((root / PROTOCOL).read_text())
    report = json.loads((root / REPORT).read_text())
    assert source_check(root) == spec['input']['source_hashes']
    assert report['protocol_sha256'] == sha(root / PROTOCOL)
    for path, expected in spec['code_hashes'].items():
        assert sha(root / path) == expected
    assert sha(root / spec['input']['input_path']) == spec['input']['input_sha256']
    units_path = root / spec['input']['units_path']
    assert sha(units_path) == spec['input']['units_sha256']
    units = json.loads(units_path.read_text())
    left, right = units['left'], units['right']
    lines = (root / spec['input']['input_path']).read_text().splitlines()
    assert lines[0] == f'{len(left)} {len(right)}'
    assert lines[1:1 + len(left)] == [u['encoded'] for u in left]
    assert [line.split() for line in lines[1 + len(left):]] == [u['encoded_words'] for u in right]
    expected_left = 2 * sum(max(0, len(u['encoded']) - spec['minimum_length'] + 1) for u in left)
    expected_right = sum(max(0, sum(map(len, u['encoded_words'])) - spec['minimum_length'] + 1) for u in right)
    assert (expected_left, expected_right, expected_left * expected_right) == (report['left_oriented_starts'], report['right_starts'], report['start_pairs'])
    k = report['maximum']
    actual = all_matches(left, right, k or spec['minimum_length'])
    expected = {tuple(hit[f] for f in FIELDS) for hit in report['maximum_occurrences']}
    assert actual == expected
    longer = None
    if 0 < k < spec['maximum_length']:
        longer = all_matches(left, right, k + 1)
        assert not longer, 'Omitted longer match'
    for name, values in report['reference_maxima'].items():
        assert len(values) == spec['reference_draws_per_model']
        exceedances = sum(value >= k for value in values)
        assert report['references'][name] == {'draws': len(values), 'exceedances': exceedances, 'p': (1 + exceedances) / (1 + len(values))}
    output = {'id': 'CHECK-EXP-012', 'report_sha256': sha(root / REPORT), 'maximum': k,
              'maximum_occurrences_checked': len(actual), 'longer_length_checked': k + 1 if longer is not None else None,
              'source_files_verified': 32, 'all_input_units_roundtrip_checked': True,
              'saved_reference_tails_checked': 2, 'reference_scans_independently_reexecuted': 0,
              'method': 'Python full-length predecessor-distance index, distinct from C++ canonical seed/extension; all observed maxima and absence at max+1.',
              'independent_scientific_replication': False, 'pass': True,
              'candidate_retained': report['numerical_alert'], 'verdict': report['verdict']}
    destination = root / 'reports/modern-local-exp012-check-v1.json'
    assert not destination.exists(), 'Preserve completed check'
    write_json(destination, output)
    append(root / 'registry/events.jsonl', 'modern_target_checked', {'id': 'EXP-012', 'report_sha256': sha(destination),
        'pass': True, 'candidate_retained': output['candidate_retained'], 'verdict': output['verdict']})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['fetch', 'prepare', 'run', 'check'])
    args = parser.parse_args()
    if args.action == 'fetch':
        print(json.dumps({'verified_files': len(source_check(ROOT, fetch=True))}))
    else:
        print(json.dumps(globals()[args.action](ROOT), ensure_ascii=False))
