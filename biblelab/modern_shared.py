"""Complete modern editions, unchanged FAM-003 and COMMON-001 normalization."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import unicodedata as ud
import xml.etree.ElementTree as ET

from .sources import ROOT, TORAH, NT, write_json
from .letters import GREEK, HEBREW_FINAL, normalize
from .editions import oshb, sbl, OSIS
from .modern_local import sha, encode, source_check, independent_letters
from .registry import append, read_events

DIRECTORY = 'data/derived/modern-shared-v1'
PROTOCOL = 'protocol/modern-editions-fam003-v1.json'
REPORT = 'reports/modern-shared-exp013-v1.json'


def common_deletion(raw):
    """Build old coordinates directly; remove only U+0345-derived letters."""
    old, common, offsets, kept, removed = [], [], [], [], []
    for position, original in enumerate(raw):
        for decomposed in ud.normalize('NFD', original):
            letter = 'ι' if decomposed == '\u0345' else decomposed.lower().replace('ς', 'σ')
            if letter in GREEK:
                old_index = len(old)
                old.append(letter)
                if decomposed == '\u0345':
                    removed.append(old_index)
                else:
                    kept.append(old_index)
                    common.append(letter)
                    offsets.append(position)
    if old and not common:
        raise ValueError('An old nonempty word disappeared under common normalization')
    return dict(old=''.join(old), common=''.join(common), common_to_old=kept,
                removed_old_positions=removed, common_source_codepoint_offsets=offsets)


def serialize(left, right):
    lines = [f'{len(left)} {len(right)}']
    for side in (left, right):
        assert len({u['id'] for u in side}) == len(side)
        for group, unit in enumerate(side):
            assert unit['group'] == group and unit['words'] and all(unit['words'])
            lines.append(' '.join([str(group), *unit['words']]))
    return '\n'.join(lines) + '\n'


def prepare(root=ROOT):
    source_hashes = source_check(root)
    directory = root / DIRECTORY
    assert not (directory / 'preparation.json').exists(), 'Preserve completed preparation'
    assert not (directory / 'input.txt').exists(), 'Inspect existing partial preparation'
    left, right, crosswalk = [], [], []
    for book in TORAH:
        path = root / f'data/raw/oshb/wlc/{book}.xml'
        verses, _ = oshb(path)
        independent = {}
        for verse in ET.parse(path).getroot().iter(OSIS + 'verse'):
            independent[verse.attrib['osisID']] = [independent_letters(''.join(w.itertext()), 'he')
                for w in list(verse) if w.tag == OSIS + 'w']
        assert len(independent) == len(verses)
        for verse in verses:
            words = [w['letters'].translate(HEBREW_FINAL) for w in verse['words']]
            assert words == independent[verse['ref']] and all(words)
            left.append(dict(id=verse['ref'], group=len(left), words=[encode(w, 'he') for w in words]))
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
                independent[current].append(''.join(element.itertext()))
        assert len(independent) == len(verses)
        for verse in verses:
            assert [w['raw'] for w in verse['words']] == independent[verse['ref']]
            words, entries = [], []
            old_start = common_start = 0
            for number, word in enumerate(verse['words']):
                raw = word['raw']
                primary = normalize(ud.normalize('NFD', raw).replace('\u0345', ''), 'grc')['letters']
                entry = common_deletion(raw)
                assert entry['old'] == word['letters'] and entry['common'] == primary
                assert primary, 'No silent word exclusion'
                words.append(encode(primary, 'grc'))
                entries.append(dict(raw=raw, word_index=number, old_start=old_start,
                                    common_start=common_start, **entry))
                old_start += len(entry['old'])
                common_start += len(primary)
            right.append(dict(id=verse['ref'], group=len(right), words=words))
            crosswalk.append(dict(id=verse['ref'], words=entries))
    directory.mkdir(parents=True, exist_ok=True)
    units_path, input_path = directory / 'units.json', directory / 'input.txt'
    crosswalk_path = directory / 'greek-crosswalk.json'
    write_json(units_path, dict(left=left, right=right))
    write_json(crosswalk_path, crosswalk)
    input_path.write_text(serialize(left, right), encoding='ascii')
    counts = dict(left_units=len(left), right_units=len(right), left_groups=len(left), right_groups=len(right),
        left_letters=sum(len(w) for u in left for w in u['words']),
        right_letters=sum(len(w) for u in right for w in u['words']),
        old_right_letters=sum(len(w['old']) for u in crosswalk for w in u['words']),
        removed_subscript_iotas=sum(len(w['removed_old_positions']) for u in crosswalk for w in u['words']))
    assert counts['left_letters'] == 304850 and counts['right_letters'] == 679879
    assert counts['old_right_letters'] - counts['right_letters'] == counts['removed_subscript_iotas'] == 7500
    receipt = dict(source_hashes=source_hashes, counts=counts, all_verses_independently_reextracted=True,
        no_dss_files_read=True, normalization='COMMON-001: only U+0345-derived iotas removed; written iotas preserved; Hebrew finals and Greek final sigma folded.',
        boundaries='Every complete modern verse is one unique group; no verse concatenation, selection or historical filter.')
    for label, path in [('input', input_path), ('units', units_path), ('crosswalk', crosswalk_path)]:
        receipt[label + '_path'] = str(path.relative_to(root))
        receipt[label + '_sha256'] = sha(path)
    write_json(directory / 'preparation.json', receipt)
    return {k: v for k, v in receipt.items() if k != 'source_hashes'}


def verify_frozen(root):
    spec = json.loads((root / PROTOCOL).read_text())
    assert source_check(root) == spec['input']['source_hashes']
    for path, expected in spec['code_hashes'].items():
        assert sha(root / path) == expected, path
    for label in ('input', 'units', 'crosswalk'):
        assert sha(root / spec['input'][label + '_path']) == spec['input'][label + '_sha256']
    for item in spec['existing_diagnostics'].values():
        assert sha(root / item['path']) == item['sha256']
    return spec


def run(root=ROOT):
    spec = verify_frozen(root)
    events = read_events(root / 'registry/events.jsonl')
    assert any(e['kind'] == 'protocol_frozen' and e['payload'].get('sha256') == sha(root / PROTOCOL) for e in events)
    assert not any(e['kind'] == 'modern_target_started' and e['payload'].get('id') == spec['id'] for e in events), 'Never silently restart a target'
    assert not (root / REPORT).exists()
    compiler = shutil.which('clang++')
    assert compiler, 'C++17 compiler required'
    directory = root / DIRECTORY
    binary = directory / 'shared_match'
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-pedantic']
    subprocess.run([compiler, *flags, str(root / 'native/shared_match.cpp'), '-o', str(binary)], check=True)
    append(root / 'registry/events.jsonl', 'modern_target_started', dict(id=spec['id'], family='FAM-003',
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'],
        new_target_evaluations=1, cumulative_started=13, compiler=subprocess.check_output([compiler, '--version'], text=True),
        flags=flags, binary_sha256=sha(binary)))
    raw_path, error_path = directory / 'raw-result.json', directory / 'stderr.txt'
    print('EXP-013 started: full modern verses, unchanged shared substitution, 199 draws per model.', flush=True)
    with raw_path.open('w') as output, error_path.open('w') as error:
        result = subprocess.run([str(binary), str(root / spec['input']['input_path']), str(spec['minimum_length']),
            str(spec['maximum_length']), str(spec['reference_draws_per_model']), str(spec['seed'])], stdout=output, stderr=error)
    if result.returncode:
        append(root / 'registry/events.jsonl', 'modern_target_failed', dict(id=spec['id'], exit_code=result.returncode,
            partial_output_sha256=sha(raw_path), stderr_sha256=sha(error_path), verdict='ouverte; execution incomplete'))
        raise RuntimeError('Native execution failed; preserve partial output and do not claim a negative')
    raw = json.loads(raw_path.read_text())
    references, samples = {}, {}
    for mode, values in raw['reference_scores'].items():
        assert len(values) == spec['reference_draws_per_model']
        exceeds = sum(v >= raw['score'] for v in values)
        references[mode] = dict(draws=len(values), exceedances=exceeds, p=(1 + exceeds) / (1 + len(values)),
                               histogram=dict(sorted(Counter(values).items())))
        for label, index in [('first', 0), ('last', -1)]:
            path = root / (spec['input']['input_path'] + f'.{mode}.{label}.txt')
            samples[f'{mode}_{label}'] = dict(path=str(path.relative_to(root)), sha256=sha(path),
                                            mode=mode, score=values[index])
    alert = raw['score'] >= spec['candidate_screen']['minimum_length'] and all(
        r['p'] <= spec['candidate_screen']['p_each_model_max'] for r in references.values())
    report = dict(id=spec['id'], family='FAM-003', completed_utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=sha(root / PROTOCOL), input_sha256=spec['input']['input_sha256'], counts=spec['input']['counts'],
        raw_result_path=str(raw_path.relative_to(root)), raw_result_sha256=sha(raw_path), runtime=platform.platform(),
        **raw, references=references, reference_samples=samples, numerical_alert=alert, candidate_retained=False,
        internal_verification_pending=True, verdict='ouverte' if alert else 'rien', verdict_pending_internal_check=True,
        historical_certification_required_to_compute=False, confirmatory_p=False, independent_scientific_replication=False,
        scope='Complete modern editions; FAM-003 maximum shared length16..32; no claim about other rules or power on every background.')
    write_json(root / REPORT, report)
    append(root / 'registry/events.jsonl', 'modern_target_completed', dict(id=spec['id'], report=REPORT,
        report_sha256=sha(root / REPORT), score=raw['score'], numerical_alert=alert, cumulative_completed=13))
    return {k: report[k] for k in ('id', 'score', 'references', 'numerical_alert', 'verdict')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'run'))
    args = parser.parse_args()
    print(json.dumps(globals()[args.command](), ensure_ascii=False, indent=2), flush=True)
