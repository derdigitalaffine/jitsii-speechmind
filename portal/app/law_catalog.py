"""Citizen-facing legal catalogue: metadata filters and shared title/content search."""
import json
import re
from collections import Counter
from math import ceil
from urllib.parse import urlencode
from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer
from . import laws as lx
from .db import LawLevel, LawSection, LawText

TOPICS = {
    'verwaltung': 'Verwaltung & Gremien', 'bauen': 'Bauen & Wohnen',
    'gebuehren': 'Gebühren & Steuern', 'friedhof': 'Friedhof & Bestattung',
    'familie': 'Familie & Betreuung', 'einrichtungen': 'Öffentliche Einrichtungen',
    'ordnung': 'Sicherheit & Ordnung', 'umwelt': 'Umwelt & Versorgung',
}
RULES = {
    'verwaltung': r'hauptsatzung|geschäftsordnung|gremi|ratsmitglied|entschädigung',
    'bauen': r'bau|wohn|erschließ|sanierung|stellplatz',
    'gebuehren': r'gebühr|steuer|beitrag|entgelt',
    'friedhof': r'friedhof|bestatt|grab', 'familie': r'kita|kindertages|betreu|jugend',
    'einrichtungen': r'bürgerhaus|dorfgemeinschaft|halle|sport|bibliothek|bücherei|benutzungsordnung',
    'ordnung': r'gefahrenabwehr|feuerwehr|ordnungsbehörd|sicherheit|straßenreinigung',
    'umwelt': r'abfall|wasser|abwasser|umwelt|natur|versorgung',
}
PAGE_SIZE = 12


def clean_topics(raw):
    if isinstance(raw, str):
        raw = re.split(r'[,;\n]', raw)
    if not isinstance(raw, list):
        raise ValueError('Themen bitte als Liste oder durch Komma getrennt angeben.')
    result, seen = [], set()
    canonical = {name.casefold(): name for name in TOPICS.values()}
    for value in raw:
        if not isinstance(value, str):
            raise ValueError('Jedes Thema benötigt eine Bezeichnung.')
        name = ' '.join(value.split())
        if not name:
            continue
        if len(name) > 60:
            raise ValueError('Themen dürfen höchstens 60 Zeichen lang sein.')
        name = canonical.get(name.casefold(), name)
        if name.casefold() not in seen:
            result.append(name); seen.add(name.casefold())
    if len(result) > 12:
        raise ValueError('Höchstens zwölf Themen je Rechtstext.')
    return result


def suggested_topics(law):
    text = (law.title or '') + ' ' + (law.short_title or '')
    return [TOPICS[key] for key, pattern in RULES.items() if re.search(pattern, text, re.I)]


def topics(law):
    if not law.topics_json:
        return suggested_topics(law)
    try:
        return clean_topics(json.loads(law.topics_json))
    except (ValueError, TypeError):
        return []


def form_topics(data):
    return clean_topics([name for key, name in TOPICS.items() if data.get('topic_' + key) == '1'] + clean_topics(data.get('other_topics') or ''))


def local(level):
    visited = set()
    while level is not None and level.id not in visited:
        visited.add(level.id)
        if level.kind != 'sonstige':
            return level.kind in ('vg', 'og')
        level = level.parent
    return None  # Unassigned records remain discoverable until editorial assignment.


def filters(params, focus=None):
    values = {'q': str(params.get('q') or '').strip()[:200],
              'bereich': params.get('bereich', 'alle' if focus else 'ort'), 'ebene': str(focus.id) if focus else str(params.get('ebene') or ''),
              'thema': str(params.get('thema') or '')[:60], 'art': params.get('art', ''),
              'geltung': params.get('geltung', 'aktuell'), 'sort': params.get('sort', 'titel')}
    for key, allowed, default in [('bereich', ('ort', 'weitere', 'alle'), 'ort'),
                                  ('geltung', ('aktuell', 'archiv', 'alle'), 'aktuell'),
                                  ('sort', ('titel', 'neu'), 'titel')]:
        if values[key] not in allowed: values[key] = default
    if values['art'] not in lx.DOC_TYPES: values['art'] = ''
    if not values['ebene'].isdigit(): values['ebene'] = ''
    return values


def search_terms(query):
    aliases = {'friedhofsgebühren': ['friedhof', 'gebühr'], 'friedhofsgebühr': ['friedhof', 'gebühr'], 'friedhofs':['friedhof'], 'gebühren':['gebühr']}
    return [term for word in lx.terms(query) for term in aliases.get(word.casefold(), [word.casefold()])]


def _fold(column):
    for upper, lower in [('Ä','ä'), ('Ö','ö'), ('Ü','ü'), ('ẞ','ß')]:
        column = func.replace(column, upper, lower)
    return func.replace(func.lower(column), 'ß', 'ss')


def visible_query(editor=False, query=''):
    stmt = select(LawText).options(defer(LawText.body_md), defer(LawText.planned_md))
    if not editor: stmt = stmt.where(LawText.published.is_(True))
    for word in search_terms(query):
        # Escape SQL wildcards: user text remains a literal search term.
        like = '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        compact = '%' + re.sub(r'\s+', '', word).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        stmt = stmt.where(or_(_fold(LawText.title).like(like, escape='\\'), _fold(LawText.short_title).like(like, escape='\\'),
                              LawText.sections.any(or_(_fold(LawSection.plain).like(like, escape='\\'),
                                                       _fold(func.replace(LawSection.number, ' ', '')).like(compact, escape='\\')))))
    return stmt


def choose(rows, levels, f, *, query_ids=None, omit=''):
    selected = levels.get(int(f['ebene'])) if f['ebene'] else None
    level_ids = set(lx.descendant_ids(selected)) if selected else None
    result = []
    for law in rows:
        if omit != 'bereich':
            is_local = local(levels.get(law.level_id))
            if f['bereich'] == 'ort' and is_local is False: continue
            if f['bereich'] == 'weitere' and is_local is not False: continue
        if omit != 'ebene' and f['ebene'] and (not level_ids or law.level_id not in level_ids): continue
        if omit != 'geltung':
            expired = lx.expired(law)
            if f['geltung'] == 'aktuell' and expired: continue
            if f['geltung'] == 'archiv' and not expired: continue
        if omit != 'art' and f['art'] and law.doc_type != f['art']: continue
        if omit != 'thema' and f['thema'] and f['thema'].casefold() not in [t.casefold() for t in topics(law)]: continue
        if query_ids is not None and law.id not in query_ids: continue
        result.append(law)
    return result


def browse(db, params, *, editor=False, focus=None, base='/recht'):
    f = filters(params, focus)
    levels = {level.id: level for level in db.scalars(select(LawLevel))}
    rows = list(db.scalars(visible_query(editor).order_by(LawText.title)))
    query_ids = None
    if f['q']:
        query_ids = {law.id for law in db.scalars(visible_query(editor, f['q']))} if lx.terms(f['q']) else set()
    results = choose(rows, levels, f, query_ids=query_ids)
    words = search_terms(f['q'])
    if f['sort'] == 'neu': results.sort(key=lambda law: (law.updated_at, law.id), reverse=True)
    else: results.sort(key=lambda law: (bool(words) and not all(w in (law.title+' '+law.short_title).casefold() for w in words), law.title.casefold(), law.id))
    total = len(results); pages = max(1, ceil(total / PAGE_SIZE))
    try: page = max(1, min(pages, int(params.get('seite', '1'))))
    except (ValueError, TypeError): page = 1
    items = results[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    path = base + (f'/ebene/{focus.id}' if focus else '')
    def url(**changes):
        values = dict(f); values.update(changes)
        if focus: values.pop('ebene', None)
        return path + '?' + urlencode({k:v for k,v in values.items() if v not in ('', None)}) + '#catalog-results'
    topic_rows = choose(rows, levels, f, query_ids=query_ids, omit='thema')
    topic_counts, canonical_topics = Counter(), {}
    for law in topic_rows:
        for name in topics(law):
            label = canonical_topics.setdefault(name.casefold(), name)
            topic_counts[label] += 1
    if f['thema']:
        f['thema'] = canonical_topics.get(f['thema'].casefold(), f['thema'])
        topic_counts.setdefault(f['thema'], 0)
    level_rows = choose(rows, levels, f, query_ids=query_ids, omit='ebene')
    available_levels = set()
    for law in level_rows:
        level = levels.get(law.level_id)
        if level:
            available_levels.update(p.id for p in lx.level_path(level))
    options = sorted([level for level in levels.values() if (level.id in available_levels and (f['bereich']!='ort' or local(level) is not False)) or str(level.id)==f['ebene']], key=lambda level: level.name.casefold())
    featured = sorted(topic_counts.items(), key=lambda x:(-x[1],x[0].casefold()))[:6]
    if f['thema'] and f['thema'] not in [name for name,n in featured]:
        featured = featured[:5] + [(f['thema'],topic_counts[f['thema']])]
    return {'items':items, 'filters':f, 'total':total, 'page':page, 'pages':pages, 'url':url,
            'topics':sorted(topic_counts.items(), key=lambda x:x[0].casefold()), 'levels':options,
            'featured_topics':featured, 'first':(page-1)*PAGE_SIZE+1 if total else 0, 'last':min(page*PAGE_SIZE,total)}
