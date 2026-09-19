"""Extraction keeps reading alternatives outside the chosen base stream."""
import collections
import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .letters import normalize
from .sources import TORAH, NT, write_json, digest

OSIS = '{http://www.bibletechnologies.net/2003/OSIS/namespace}'
TEI = '{http://www.tei-c.org/ns/1.0}'


def oshb(path):
    root = ET.parse(path).getroot()
    verses, notes = [], []
    for verse in root.iter(OSIS + 'verse'):
        ref = verse.attrib['osisID']
        words = []
        for child in verse:
            tag = child.tag.removeprefix(OSIS)
            if tag == 'w':
                raw = ''.join(child.itertext())
                words.append(dict(source_word_id=child.get('id'), raw=raw,
                                  reading=child.get('type', 'main'), **normalize(raw, 'he')))
            elif tag == 'note':
                notes.append(dict(ref=ref, attributes=child.attrib,
                                  raw_xml=ET.tostring(child, encoding='unicode')))
            elif tag != 'seg':
                raise ValueError(f'Unexpected OSHB verse child: {tag} at {ref}')
        if not words:
            raise ValueError('Empty OSHB verse: ' + ref)
        verses.append(dict(ref=ref, words=words))
    if not verses or len({x['ref'] for x in verses}) != len(verses):
        raise ValueError('Missing or duplicate OSHB verses')
    return verses, notes


def sbl(path):
    root = ET.parse(path).getroot()
    verses, marks, current = [], [], None
    allowed = {'book', 'title', 'p', 'verse-number', 'w', 'prefix', 'suffix'}
    for el in root.iter():
        if el.tag not in allowed:
            raise ValueError('Unexpected SBLGNT tag: ' + el.tag)
        if el.tag == 'verse-number':
            current = dict(ref=el.attrib['id'], words=[])
            verses.append(current)
        elif el.tag == 'w':
            if current is None:
                raise ValueError('Greek word before first verse')
            raw = ''.join(el.itertext())
            current['words'].append(dict(raw=raw, **normalize(raw, 'grc')))
        elif el.tag in ('prefix', 'suffix') and el.text:
            marks.append(dict(ref=current['ref'] if current else None,
                              after_word=len(current['words']) if current else 0,
                              position=el.tag, raw=el.text))
    if not verses or len({x['ref'] for x in verses}) != len(verses) or any(not v['words'] for v in verses):
        raise ValueError('Missing, duplicate or empty SBLGNT verses')
    return verses, marks


def apparatus(path):
    ref, notes = None, []
    for el in ET.parse(path).getroot():
        if el.tag == 'verse':
            ref = el.text
        elif el.tag == 'note':
            if ref is None:
                raise ValueError('Apparatus note before verse')
            notes.append(dict(ref=ref, raw=''.join(el.itertext())))
        elif el.tag != 'book-name':
            raise ValueError('Unexpected apparatus tag: ' + el.tag)
    return notes


def summarize(verses):
    words = [w for v in verses for w in v['words']]
    stream = ''.join(w['letters'] for w in words)
    return dict(verses=len(verses), words=len(words), letters=len(stream),
                stream_sha256=digest(stream.encode()),
                empty_words=sum(not w['letters'] for w in words),
                discarded_codepoints=sorted({c for w in words for c in w['discarded_codepoints']}))


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div'):
            self.parts.append(' ')


def controls(root):
    path = root / 'data/raw/perseus/data/tlg0032/tlg006/tlg0032.tlg006.perseus-grc2.xml'
    tree = ET.parse(path).getroot()
    # Notes and headers must never enter the prose stream.
    body = tree.find('.//' + TEI + 'body')
    if body is None:
        raise ValueError('Missing Perseus body')
    excluded = {'note', 'head', 'bibl', 'speaker', 'del'}
    def prose(el):
        tag = el.tag.removeprefix(TEI)
        if tag in excluded:
            return ''
        if tag == 'gap':
            return '\ufffc'
        if tag == 'choice':
            for name in ('corr', 'reg'):
                choice = el.find(TEI + name)
                if choice is not None:
                    return prose(choice)
            raise ValueError('Unsupported editorial choice in Perseus')
        return (el.text or '') + ''.join(prose(c) + (c.tail or '') for c in el)
    greek_raw = prose(body)
    greek = normalize(greek_raw, 'grc')
    source = json.loads((root / 'data/raw/sefaria/berakhot.json').read_text())
    blocks = []
    def flatten(value):
        if isinstance(value, str):
            p = Plain(); p.feed(value); blocks.append(''.join(p.parts))
        elif isinstance(value, list):
            for v in value:
                flatten(v)
        else:
            raise ValueError('Unexpected Sefaria text structure')
    flatten(source['text'])
    hebrew_raw = '\n'.join(blocks)
    hebrew = normalize(hebrew_raw, 'he')
    write_json(root / 'data/derived/controls.json', {
        'xenophon': dict(raw=greek_raw, **greek,
                        contiguous_prefix_letters=normalize(greek_raw.split('\ufffc')[0], 'grc')['letters']),
        'berakhot': dict(raw=hebrew_raw, **hebrew),
    })
    return dict(
        xenophon=dict(letters=len(greek['letters']), status='unmatched Greek narrative control',
                      editorial_policy='corr and add retained, del omitted, gaps marked U+FFFC; calibration uses prefix before first gap',
                      critical_elements=dict(collections.Counter(e.tag.removeprefix(TEI) for e in body.iter()
                          if e.tag.removeprefix(TEI) in ('choice','corr','sic','add','del','gap')))),
        berakhot=dict(letters=len(hebrew['letters']), blocks=len(blocks),
                      status='unmatched Hebrew rabbinic prose control',
                      metadata={k: v for k, v in source.items() if k != 'text'}))


def audit_editions(root):
    summary = {'hebrew': {}, 'greek': {}, 'policy': 'protocol/testabilite.md'}
    for book in TORAH:
        verses, notes = oshb(root / f'data/raw/oshb/wlc/{book}.xml')
        write_json(root / f'data/derived/oshb/{book}.json', dict(verses=verses, notes=notes))
        summary['hebrew'][book] = dict(summarize(verses), notes=len(notes),
            variant_notes=sum(n['attributes'].get('type') == 'variant' for n in notes),
            ketiv_words=sum(w['reading'] == 'x-ketiv' for v in verses for w in v['words']))
    for book in NT:
        verses, marks = sbl(root / f'data/raw/sblgnt/data/sblgnt/xml/{book}.xml')
        notes = apparatus(root / f'data/raw/sblgnt/data/sblgntapp/xml/{book}.xml')
        write_json(root / f'data/derived/sblgnt/{book}.json', dict(verses=verses, marks=marks, apparatus=notes))
        summary['greek'][book] = dict(summarize(verses), apparatus_notes=len(notes))
    summary['controls'] = controls(root)
    return summary
