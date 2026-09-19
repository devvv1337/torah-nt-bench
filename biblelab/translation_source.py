"""Separate pinned intake for an explicitly dependent Hebrew-Greek control."""
import collections
import csv
import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from .letters import normalize
from .sources import ROOT, TORAH, digest, write_json
from .registry import append

REPO = 'eliranwong/LXX-Swete-1930'
REVISION = '1d3efc3c63bd384a4f3f07ed37eef54b0d45ac33'
FILES = ('README.md', 'LICENSE', '00-Swete_versification.csv',
         '01-Swete_word_with_punctuations.csv', 'info_non-Greek_characters.csv')
MARKS = frozenset('[]⸂⸃⸆')
BOOK_NAMES = {'Gen':'Gen', 'Exo':'Exod', 'Lev':'Lev', 'Num':'Num', 'Deu':'Deut'}


def verify_translation(root=ROOT):
    path = root/'data/translation-sources.lock.json'
    manifest = json.loads(path.read_text())
    records = manifest['files']
    if len(records) != len(FILES) or {r['name'] for r in records} != set(FILES):
        raise ValueError('Incomplete or duplicated translation manifest')
    for row in records:
        name = row['name']
        if (row['revision'] != REVISION or row['repository'] != REPO or
                row['path'] != f'data/raw/swete/{name}' or
                row['url'] != f'https://raw.githubusercontent.com/{REPO}/{REVISION}/{name}'):
            raise ValueError('Translation source identity mismatch')
        raw = (root/row['path']).read_bytes()
        if digest(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise ValueError('Translation source integrity failure: '+name)
    return dict(files=len(records), bytes=sum(r['bytes'] for r in records),
                manifest_sha256=digest(path.read_bytes()))


def fetch_translation(root=ROOT):
    lock = root/'data/translation-sources.lock.json'
    rows = json.loads(lock.read_text())['files'] if lock.exists() else []
    if len({r['name'] for r in rows}) != len(rows) or not {r['name'] for r in rows} <= set(FILES):
        raise ValueError('Unexpected prior manifest')
    for name in FILES:
        path = root/'data/raw/swete'/name
        url = f'https://raw.githubusercontent.com/{REPO}/{REVISION}/{name}'
        before = next((r for r in rows if r['name'] == name), None)
        if before and any(before[k] != v for k, v in dict(
                path=str(path.relative_to(root)), url=url, repository=REPO, revision=REVISION).items()):
            raise ValueError('Translation manifest identity changed')
        if path.exists():
            if not before:
                raise ValueError('Unregistered translation file exists')
            raw = path.read_bytes()
            headers = {}
        else:
            with urlopen(Request(url, headers={'User-Agent': 'BibleLab scholarly provenance/0.1'}), timeout=45) as r:
                raw = r.read()
                headers = {k:r.headers.get(k) for k in ('Content-Type', 'ETag', 'Last-Modified')}
        if before and digest(raw) != before['sha256']:
            raise ValueError('Translation source content changed')
        if not before:
            rows.append(dict(name=name, repository=REPO, revision=REVISION, url=url,
                path=str(path.relative_to(root)), bytes=len(raw), sha256=digest(raw),
                fetched_utc=datetime.now(timezone.utc).isoformat(), headers=headers,
                role='dependent_translation_control_not_independent_human_negative',
                license='Repository GPL-3.0; underlying Swete edition identified as public domain by upstream; preserve attribution'))
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        write_json(lock, dict(schema=1, files=rows))
    result = verify_translation(root)
    append(root/'registry/events.jsonl', 'translation_sources_verified', result)
    return result


def read_tsv(path, allow_empty=False):
    with path.open(encoding='utf8', newline='') as f:
        for lineno, row in enumerate(csv.reader(f, delimiter='\t'), 1):
            if len(row) != 2 or not row[0].isdigit() or (not row[1] and not allow_empty):
                raise ValueError(f'Invalid indexed source row {path.name}:{lineno}')
            yield int(row[0]), row[1]


def parse_swete(directory):
    """Source starts define verse spans; no segmentation inferred from Greek words."""
    starts = list(read_tsv(directory/'00-Swete_versification.csv'))
    if not starts or starts[0][0] != 1 or any(a[0] >= b[0] for a,b in zip(starts, starts[1:])):
        raise ValueError('Verse starts must strictly increase from one')
    if len({v for _,v in starts}) != len(starts):
        raise ValueError('Duplicated Swete reference')
    verses, words, pointer, last = [], [], 0, 0
    selected_tokens = 0
    def emit(index, entries):
        source_ref = starts[index][1]
        source_book = source_ref.split('.')[0]
        if source_book not in BOOK_NAMES:
            return
        match = re.fullmatch(r'([A-Za-z]+)\.(\d+):(\d+)', source_ref)
        if match is None:
            raise ValueError('Unsupported Torah reference: '+source_ref)
        book, ch, verse = match.groups()
        if not entries:
            raise ValueError('Missing token IDs for Swete verse: '+source_ref)
        verses.append(dict(ref=f'{BOOK_NAMES[book]}.{int(ch)}.{int(verse)}', source_ref=source_ref,
                           empty_letters=not any(w['letters'] for w in entries),
                           source_start_id=starts[index][0], words=entries))
    for word_id, raw in read_tsv(directory/'01-Swete_word_with_punctuations.csv', allow_empty=True):
        if word_id != last+1:
            raise ValueError('Nonconsecutive source token IDs')
        last = word_id
        while pointer+1 < len(starts) and word_id >= starts[pointer+1][0]:
            emit(pointer, words)
            words = []
            pointer += 1
        if starts[pointer][1].split('.')[0] in BOOK_NAMES:
            words.append(dict(source_word_id=word_id, raw=raw,
                              editorial_marks=[c for c in raw if c in MARKS], **normalize(raw, 'grc')))
            selected_tokens += 1
    emit(pointer, words)
    if pointer != len(starts)-1 or last < starts[-1][0]:
        raise ValueError('Verse start exceeds token file')
    if {v['ref'].split('.')[0] for v in verses} != set(TORAH):
        raise ValueError('Missing a Torah book in Swete source')
    if len({v['ref'] for v in verses}) != len(verses):
        raise ValueError('Normalization created duplicate references')
    return verses, dict(source_tokens_all_books=last, source_verse_starts_all_books=len(starts),
                       selected_tokens=selected_tokens)


def audit_translation(root=ROOT):
    verified = verify_translation(root)
    verses, source_counts = parse_swete(root/'data/raw/swete')
    from .editions import summarize
    derived = root/'data/derived/swete/torah.json'
    write_json(derived, dict(verses=verses, policy='protocol/translation-control-v1.json'))
    result = dict(verified=verified, source_counts=source_counts,
        by_book={book:summarize([v for v in verses if v['ref'].startswith(book+'.')]) for book in TORAH},
        marked_tokens=sum(bool(w['editorial_marks']) for v in verses for w in v['words']),
        empty_verses=[v['ref'] for v in verses if v['empty_letters']],
        editorial_marks=dict(collections.Counter(c for v in verses for w in v['words'] for c in w['editorial_marks'])),
        derived_sha256=digest(derived.read_bytes()),
        status='modern transcription of Swete edition, not a manuscript collation; same labels do not certify identical content')
    write_json(root/'reports/translation-intake.json', result)
    return verses, result
