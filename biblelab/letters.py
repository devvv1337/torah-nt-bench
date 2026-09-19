"""Named normalizations with per-letter source-codepoint offsets."""
import unicodedata as ud

HEBREW = 'אבגדהוזחטיכלמנסעפצקרשת'
HEBREW_FINAL = str.maketrans('ךםןףץ', 'כמנפצ')
GREEK = 'αβγδεζηθικλμνξοπρστυφχψω'


def normalize(raw: str, language: str, fold_finals=False):
    if language not in ('he', 'grc'):
        raise ValueError('Unsupported language')
    letters, offsets, discarded = [], [], []
    for index, original in enumerate(raw):
        # Decompose before lowercasing: casefold would silently expand iota subscript.
        for ch in ud.normalize('NFD', original):
            if language == 'he':
                if '\u05d0' <= ch <= '\u05ea':
                    letters.append(ch.translate(HEBREW_FINAL) if fold_finals else ch)
                    offsets.append(index)
                elif ud.category(ch).startswith('L'):
                    raise ValueError(f'Unexpected letter in Hebrew: U+{ord(ch):04X}')
                else:
                    discarded.append(ch)
            else:
                ch = 'ι' if ch == '\u0345' else ch.lower()
                if ch == 'ς':
                    ch = 'σ'
                if ch in GREEK:
                    letters.append(ch)
                    offsets.append(index)
                elif ud.category(ch).startswith('L') and ch not in ('\u02bc', '\u1fbd'):
                    raise ValueError(f'Unexpected letter in Greek: U+{ord(ch):04X}')
                else:
                    discarded.append(ch)
    return {'letters': ''.join(letters), 'source_codepoint_offsets': offsets,
            'discarded_codepoints': sorted({f'U+{ord(c):04X}' for c in discarded})}
