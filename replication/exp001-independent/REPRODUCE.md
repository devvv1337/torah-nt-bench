# Reproduce the independent implementation

The permitted input packet is the sibling directory `exp001-inputs`. No other
project file or module is read. Python standard library and a C++17 compiler
are sufficient. Exact compiler and Python versions are captured in
`environment.json`; all invoked commands are captured in `execution.log`.

Original invocation, from this directory:

```sh
python3 run.py
```

The runner refuses to overwrite sealed outputs. For a fresh reproduction,
place just `run.py`, `engine.cpp` and this instruction file into a fresh
directory alongside the same `exp001-inputs` directory, then run the same
command. Do not remove or alter the existing seal to rerun in place.

`prepared-input.bin` is a fully specified intermediate representation:

1. ASCII magic `FAM001I1` (8 bytes).
2. Three little-endian uint32 values: Hebrew length, covered Greek length,
   reference count.
3. For each parameter list in order direction, offset, multiplier, intercept:
   little-endian uint32 count, followed by that many little-endian int32 values.
4. One byte per Hebrew rank, then one byte per covered Greek rank.
5. One byte per permutation entry, draw order then unit index (16 per draw).

`observed-matrices.bin` stores uint32 little-endian counts, rule index then
predicted unit then Greek unit. Every matrix has 256 entries. Indices in the
CSV outputs are zero-based. Rule enumeration follows the declarative nested
list order. Reference winners retain all tied rule indices separated by `;`.

The runner validates all supplied SHA-256 commitments, lengths, alphabets,
parameter counts and permutations. It reproduces every permutation from the
declared Python PRNG schedule. The C++ engine constructs all matrices from
integer bigram/target histograms, then independently recomputes every observed
rule count by literal letter-by-letter comparison. Python directly constructs
all matrix cells for two synthetic cases, checking both relative stream length
orderings, every observed count, and reference maxima including all ties.

The synthetic cases validate the implementation, not new empirical hypotheses;
they use exactly the same 3 072 rules. No new real-text rule or family is tried.

Verify the sealed outputs without changing them:

```sh
python3 - <<'PY'
import hashlib, json, pathlib
p = pathlib.Path('.')
m = json.loads((p/'OUTPUT-SHA256.json').read_text())
for name, e in m['files'].items():
    data = (p/name).read_bytes()
    assert len(data) == e['bytes']
    assert hashlib.sha256(data).hexdigest() == e['sha256'], name
print('All', len(m['files']), 'sealed files verified')
print('Manifest SHA256:', hashlib.sha256((p/'OUTPUT-SHA256.json').read_bytes()).hexdigest())
PY
```

The manifest cannot include its own digest. Its SHA-256 is therefore printed
only after sealing and communicated separately. This is a local content freeze,
not an independent trusted timestamp or a signature by a third party.
