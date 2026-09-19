"""Local tamper-evident event chain, explicitly not an external timestamp."""
import json
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from .sources import digest


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def snapshot_code(root):
    files = sorted((root / 'biblelab').glob('*.py'))
    hashes = {p.name: digest(p.read_bytes()) for p in files}
    snapshot_id = digest(canonical(hashes))
    destination = root / 'registry/code' / snapshot_id / 'biblelab'
    destination.mkdir(parents=True, exist_ok=True)
    for p in files:
        target = destination / p.name
        if target.exists() and target.read_bytes() != p.read_bytes():
            raise ValueError('Code snapshot is inconsistent')
        target.write_bytes(p.read_bytes())
    return {'id':snapshot_id, 'directory':str(destination.parent.relative_to(root)), 'files':hashes}


def _parse_events(contents):
    events, prev = [], '0' * 64
    for line in contents.splitlines():
        row = json.loads(line)
        sha = row.pop('sha256')
        if row['previous_sha256'] != prev or digest(canonical(row)) != sha:
            raise ValueError('Registry chain is inconsistent')
        if row['sequence'] != len(events) + 1:
            raise ValueError('Registry sequence is inconsistent')
        row['sha256'] = sha
        events.append(row)
        prev = sha
    return events


def read_events(path):
    if not path.exists():
        return []
    with path.open(encoding='utf8') as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        return _parse_events(stream.read())


def append(path, kind, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Lock the read-modify-append operation, including readers, so concurrent
    # calibrations/verifiers cannot allocate the same sequence or read half a row.
    with path.open('a+', encoding='utf8') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        events = _parse_events(f.read())
        row = dict(sequence=len(events) + 1, kind=kind, payload=payload,
                   utc=datetime.now(timezone.utc).isoformat(),
                   previous_sha256=events[-1]['sha256'] if events else '0' * 64)
        row['sha256'] = digest(canonical(row))
        f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n')
        f.flush()
    return row
