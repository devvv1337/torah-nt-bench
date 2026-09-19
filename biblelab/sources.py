"""Pinned upstream objects, byte-preserving acquisition, and verification."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
TORAH = ('Gen', 'Exod', 'Lev', 'Num', 'Deut')
NT = ('Matt', 'Mark', 'Luke', 'John', 'Acts', 'Rom', '1Cor', '2Cor', 'Gal',
      'Eph', 'Phil', 'Col', '1Thess', '2Thess', '1Tim', '2Tim', 'Titus',
      'Phlm', 'Heb', 'Jas', '1Pet', '2Pet', '1John', '2John', '3John', 'Jude', 'Rev')
PINS = {
    'oshb': ('openscriptures/morphhb', '3d15126fb1ef74867fc1434be1942e837932691f'),
    'sblgnt': ('Faithlife/SBLGNT', 'c4d241a9c1c479a55b989ba35a4976c1d0b8052c'),
    'dss': ('ETCBC/dss', '47ecc1738fad6e67df7d40a3e84d73e4a125e265'),
    'perseus': ('PerseusDL/canonical-greekLit', 'b24e9e25aff4586498568f1baacba0c68ca6c829'),
}
DSS_FEATURES = ('otype', 'oslots', 'glyph', 'type', 'book', 'chapter', 'verse',
                'scroll', 'fragment', 'line', 'rec', 'unc', 'cor', 'rem', 'alt',
                'vac', 'lang', 'biblical', 'script', 'srcLn')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def catalog() -> list[dict]:
    out = []
    def github(group, paths, role, license_name):
        repo, commit = PINS[group]
        for path in paths:
            out.append(dict(id=f'{group}/{path}', path=f'data/raw/{group}/{path}',
                            url=f'https://raw.githubusercontent.com/{repo}/{commit}/{path}',
                            repository=repo, revision=commit, role=role, license=license_name))
    github('oshb', ['README.md', 'LICENSE.md'] + [f'wlc/{b}.xml' for b in TORAH],
           'target_edition_not_sealed', 'CC-BY-4.0; base WLC public domain')
    github('sblgnt', ['README.md', 'About.md', 'LICENSE'] +
           [f'data/{part}/xml/{b}.xml' for part in ('sblgnt', 'sblgntapp') for b in NT],
           'target_edition_and_editorial_apparatus_not_sealed', 'CC-BY-4.0')
    github('dss', ['README.md', 'LICENSE', 'docs/about.md', 'docs/feature_documentation.md'] +
           [f'tf/2.0.1/{f}.tf' for f in DSS_FEATURES],
           'witness_transcription_with_critical_flags_not_sealed', 'CC-BY-NC-4.0')
    github('perseus', ['README.md', 'license.md',
           'data/tlg0032/tlg006/tlg0032.tlg006.perseus-grc2.xml'],
           'human_prose_control_not_matched', 'CC-BY-SA-4.0')
    obj = 'json/Mishnah/Seder Zeraim/Mishnah Berakhot/Hebrew/Mishnah, ed. Romm, Vilna 1913.json'
    generation = '1788233765460455'
    out.append(dict(id='sefaria/mishnah_berakhot', path='data/raw/sefaria/berakhot.json',
                    url='https://storage.googleapis.com/sefaria-export/' +
                    urllib.parse.quote(obj, safe='/') + '?generation=' + generation,
                    repository='Sefaria/sefaria-export GCS', revision=generation,
                    role='human_prose_control_not_matched', license='see source JSON metadata'))
    return out


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf8')
    tmp.replace(path)


def fetch(root=ROOT):
    lock = root / 'data/sources.lock.json'
    previous = json.loads(lock.read_text()) if lock.exists() else {'files': []}
    known = {r['id']: r for r in previous['files']}
    entries = catalog()
    if not set(known) <= {x['id'] for x in entries}:
        raise ValueError('Catalog changed: explicit versioned intake amendment required')
    def acquire(item):
        path = root / item['path']
        before = known.get(item['id'])
        if before and any(before[k] != item[k] for k in item):
            raise ValueError('Pinned metadata changed: ' + item['id'])
        if path.exists():
            data = path.read_bytes()
            headers = {}
            if not before:
                raise ValueError('Unregistered raw file exists: ' + item['id'])
        else:
            req = urllib.request.Request(item['url'], headers={'User-Agent': 'BibleLab/0.1 provenance research'})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
                headers = {k: response.headers.get(k) for k in ('ETag', 'Last-Modified', 'Content-Type')}
        sha = digest(data)
        if before and sha != before['sha256']:
            raise ValueError('Source integrity failure: ' + item['id'])
        record = before or dict(item, sha256=sha, bytes=len(data),
                                fetched_utc=datetime.now(timezone.utc).isoformat(), headers=headers)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return record
    # Persist each successful receipt; a later network error does not erase provenance.
    records = dict(known)
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(acquire, e): e for e in entries}
        for future in concurrent.futures.as_completed(futures):
            try:
                rec = future.result()
                records[rec['id']] = rec
                write_json(lock, {'schema': 1, 'files': sorted(records.values(), key=lambda r: r['id'])})
            except Exception as exc:
                errors.append(str(exc))
    if errors:
        raise RuntimeError('\n'.join(errors))
    return verify(root)


def verify(root=ROOT):
    lock = json.loads((root / 'data/sources.lock.json').read_text())
    entries = catalog()
    if len(lock['files']) != len(entries) or {r['id'] for r in lock['files']} != {r['id'] for r in entries}:
        raise ValueError('Incomplete or duplicated source manifest')
    expected = {r['id']: r for r in entries}
    for r in lock['files']:
        if any(r[k] != v for k, v in expected[r['id']].items()):
            raise ValueError('Manifest/catalog disagreement: ' + r['id'])
        data = (root / r['path']).read_bytes()
        if len(data) != r['bytes'] or digest(data) != r['sha256']:
            raise ValueError('Source integrity failure: ' + r['id'])
    return {'verified_files': len(lock['files']), 'bytes': sum(r['bytes'] for r in lock['files']),
            'manifest_sha256': digest((root / 'data/sources.lock.json').read_bytes())}
