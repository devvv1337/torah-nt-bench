# Torah–NT modern-edition benchmark — reproducible release V3.1

Exploratory numerical screening of nine frozen rule families. This package
contains completed full-modern results for FAM-001 through FAM-006. None
passed its fixed candidate screen. The remaining families are open in this
release. This is neither a divine-origin test nor a claim excluding all
human explanations. No current text is reserved confirmation data.

The historical manuscript branch is waiting for a numerical candidate and
is outside this package. There are no manuscript scans, contact records or
full private project history here. The public index is curated; local hashes
are not an external timestamp or independent scientific replication.

## Reproduce the new results

Python 3, a C++17 compiler named `clang++`, and network access to the pinned
GitHub source files are required. Run from a fresh extracted package:

```sh
python3 -m unittest tests.test_short_programs tests.test_modern_programs tests.test_stateful tests.test_modern_stateful
python3 tools/reproduce_modern_v3.py exp016
python3 tools/reproduce_modern_v3.py exp017
```

The scripts verify the package manifest, download and verify all 32 pinned
XML sources, reconstruct every word/unit, compile the original primary
engines, and repeat all 999 draws under each of two reference models. EXP-016
uses ten exact parameter partitions with at most two workers. Every batch's
raw output must be byte-identical to its original receipt; the maximum is
combined over the full family before calculating p. EXP-017 compares its
entire raw output byte-for-byte. Saved reference corpora and inclusive tails
are checked. Results go under `reproduction/`; reruns require a fresh extraction.

These are reproductions of already reported outcomes, not new trials or
independent evidence. The separate-algorithm checks are supplied in
`expected/exp016/check.json` and `expected/exp017/check.json`. They checked all
7,008 or 768 observed scores and four reference corpora each. The other
1,994 references in each experiment were not rescanned by a second algorithm.
The replay scripts above use the original primary engines for all draws.

## Scope and results

FAM-005 combines exactly 7,008 fixed pair, triple and product programs,
shared across three distinct source and three distinct destination verse
groups. Maximum: nine Greek letters; p=1.000 and0.988. FAM-006 uses exactly
768 reset-at-window first-order recurrences. Its complete scores, maxima
and p-values are in `expected/exp017/result.json`. The screen for both is at
least16letters AND p≤0.01 under each model. Constants, repetitions and all
tied parameter codes are retained. No unsuccessful family is expanded here.

The modern inputs contain5,853Hebrew verse groups (304,850letters) and
7,939Greek verse groups (679,879letters under COMMON-001). Hebrew final
forms and Greek final sigma are folded. Only iotas produced from U+0345
are omitted; written iotas remain. Every verse stays separate. EXP-012 used
its older explicitly declared iota convention (687,379Greek letters); it is
not silently renormalized in this release.

Every p is an exploratory conditional diagnostic. Whole-family maximization
accounts for the search within a declared family and its reference model;
it does not correct the entire adaptive history or cover all possible human
mechanisms. Earlier calibrations and human controls were measured on their
own declared backgrounds, not the expanded full modern corpus. Their complete
historical inputs are outside this archive. Some frozen protocol/code files
reference those absent inputs; use the public replay entry points above,
not the original project coordinators or calibration commands.

## Earlier results and provenance

V2 files are retained except the README, curated status and manifest. The
older commands remain available:

```sh
python3 tools/reproduce_exp012.py
python3 tools/reproduce_modern_full.py exp014
python3 tools/reproduce_modern_full.py exp015
```

EXP-001's separate same-system rewrite and comparison artifacts remain in
the package; consult their README. EXP-013's preserved failure and EXP-014's
resource-only recovery are not independent trials. Seventeen target runs
have begun through EXP-017: sixteen complete and one incomplete. Ten batches
within EXP-016 count as one target run, not ten tests or independent samples.
All earlier exposures, choices and failures stay in the research history.

`protocol/modern-edition-source-lock-v1.json` pins the sources and SHA-256
checksums: Open Scriptures Hebrew Bible / Westminster Leningrad Codex and
Michael W. Holmes's SBL Greek New Testament (2010, Society of Biblical
Literature and Logos Bible Software). License and attribution material from
V1/V2 is preserved. Raw text is fetched from the pinned revisions rather than
redistributed here. This local package is not itself a claim of publication;
publication requires an actual public repository URL.

V3.1 adds the original `tools/validate_contextual.py` helper omitted from V3.
V3 failed one test-module import during its clean package check (18 tests
passed; nine tests were not loaded). That failed archive is retained locally.
No scientific result, source corpus, engine or statistical protocol changes.
