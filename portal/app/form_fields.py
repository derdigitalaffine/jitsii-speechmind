"""Reusable structured fields. Validation and calculations always run on the server."""
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TYPES = {
    'expense_accounting': ('Reisekostenberechnung', 'fa-file-invoice-dollar', True),
    'route': ('Fahrtstrecken', 'fa-route', True),
    'period': ('Zeitraum', 'fa-calendar-days', True),
    'table': ('Wiederholbare Tabelle / Kostenpositionen', 'fa-table', True),
    'calculation': ('Berechnung', 'fa-calculator', True),
    'declaration': ('Ausdrückliche Bestätigung', 'fa-square-check', True),
    'signature': ('Gezeichnete Unterschrift', 'fa-signature', True),
}
ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
CELL_TYPES = {'text', 'number', 'amount', 'date', 'time', 'datetime', 'select', 'checkbox'}
OPERATIONS = {'sum', 'difference', 'product', 'table_total'}


def load(value, default):
    if isinstance(value, str):
        if len(value) > 100000:
            return default
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return value if isinstance(value, type(default)) else default


def bounded(value, low, high, default):
    try:
        return min(high, max(low, int(value)))
    except (ValueError, TypeError):
        return default


def number(value):
    try:
        value = Decimal(str(value).strip().replace(',', '.'))
        return value if value.is_finite() and abs(value) <= Decimal('100000000') else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def clean(kind, raw):
    if kind == 'expense_accounting':
        from . import expense_rules
        return expense_rules.clean(raw)
    if kind == 'route':
        from . import routing
        return routing.clean(raw)
    if kind == 'period':
        return {'with_time': raw.get('with_time') is not False, 'within_source': str(raw.get('within_source') or '') if ID.fullmatch(str(raw.get('within_source') or '')) else ''}
    if kind == 'declaration':
        return {'statement': str(raw.get('statement') or 'Ich bestätige ausdrücklich die Richtigkeit und Vollständigkeit meiner Angaben.').strip()[:2000]}
    if kind == 'signature':
        return {'statement': str(raw.get('statement') or 'Ich bestätige die Richtigkeit meiner Angaben.').strip()[:2000]}
    if kind == 'table':
        columns, ids = [], set()
        source = load(raw.get('columns') or raw.get('columns_json'), [])
        for c in source[:20]:
            if not isinstance(c, dict):
                continue
            cid = str(c.get('id') or '')
            if not ID.fullmatch(cid) or cid in ids:
                continue
            ids.add(cid)
            kind_c = c.get('type') if c.get('type') in CELL_TYPES else 'text'
            column = {'id': cid, 'label': str(c.get('label') or cid)[:200], 'type': kind_c, 'required': bool(c.get('required'))}
            if kind_c == 'select':
                column['options'] = list(dict.fromkeys(str(x)[:200] for x in c.get('options', []) if str(x)))[:100]
            if kind_c in ('number', 'amount'):
                for k in ('min', 'max'):
                    n = number(c.get(k))
                    if n is not None:
                        column[k] = str(n)
            columns.append(column)
        return {'columns': columns or [{'id': 'description', 'label': 'Beschreibung', 'type': 'text', 'required': True},
                                       {'id': 'amount', 'label': 'Betrag (€)', 'type': 'amount', 'required': True, 'min': '0'}],
                'min_rows': bounded(raw.get('min_rows'), 0, 100, 0),
                'max_rows': bounded(raw.get('max_rows'), 1, 100, 30), 'period_source': str(raw.get('period_source') or '') if ID.fullmatch(str(raw.get('period_source') or '')) else ''}
    if kind == 'calculation':
        sources = raw.get('sources') or []
        if isinstance(sources, str):
            sources = re.split(r'[\s,;]+', sources)
        if not isinstance(sources, list):
            sources = []
        return {'operation': raw.get('operation') if raw.get('operation') in OPERATIONS else 'sum',
                'sources': [str(x) for x in sources if ID.fullmatch(str(x))][:30],
                'column': str(raw.get('column') or 'amount')[:40],
                'quantity_column': str(raw.get('quantity_column') or '')[:40],
                'precision': bounded(raw.get('precision'), 0, 4, 2), 'unit': str(raw.get('unit') or '')[:30]}
    return {}


def parse(item, data, name):
    kind = item['type']
    if kind == 'route':
        from . import routing
        return routing.parse(item, data, name)
    raw = data.get(name)
    required = item.get('required')
    if kind == 'declaration':
        if str(raw or '') != '1':
            return None, 'Bitte die Erklärung ausdrücklich bestätigen.' if required else ''
        from .db import utcnow
        return {'confirmed': True, 'text': item['statement'], 'at': utcnow().isoformat(timespec='seconds')}, ''
    if kind in ('calculation', 'expense_accounting'):
        return None, ''  # Never trust the submitted result.
    if kind == 'period':
        value = load(raw, {})
        start = str(value.get('start') or data.get(name + '__start') or '')
        end = str(value.get('end') or data.get(name + '__end') or '')
        if not start and not end:
            return None, 'Bitte Anfang und Ende angeben.' if required else ''
        try:
            parser = datetime.fromisoformat if item.get('with_time') else date.fromisoformat
            a, b = parser(start), parser(end)
            if isinstance(a, datetime) and (a.tzinfo is not None or b.tzinfo is not None):
                raise ValueError('Use local times')
            if b < a:
                return None, 'Das Ende darf nicht vor dem Anfang liegen.'
        except (ValueError, TypeError, OverflowError):
            return None, 'Bitte einen gültigen Zeitraum angeben.'
        return {'start': start, 'end': end}, ''
    if kind == 'table':
        rows = load(raw, [])
        if raw and not isinstance(rows, list):
            return None, 'Bitte die Tabelle prüfen.'
        if raw and not rows and str(raw) != '[]':
            return None, 'Bitte die Tabelle prüfen.'
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                return None, 'Ungültige Tabellenzeile.'
            cleaned = {}
            for c in item['columns']:
                value = row.get(c['id'])
                text = str(value or '').strip()[:2000]
                if c['type'] == 'checkbox':
                    cleaned[c['id']] = value is True or value == '1'
                    continue
                if c['required'] and not text:
                    return None, f"Zeile {len(clean_rows)+1}: {c['label']} fehlt."
                if text and c['type'] in ('number', 'amount'):
                    n = number(text)
                    if n is None or ('min' in c and n < Decimal(c['min'])) or ('max' in c and n > Decimal(c['max'])):
                        return None, f"Zeile {len(clean_rows)+1}: {c['label']} ist ungültig."
                    if c['type'] == 'amount':
                        n = n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                    text = str(n)
                elif text and c['type'] == 'select' and text not in c['options']:
                    return None, f"Zeile {len(clean_rows)+1}: Bitte {c['label']} auswählen."
                elif text and c['type'] in ('date', 'datetime', 'time'):
                    from datetime import time
                    try:
                        {'date': date, 'datetime': datetime, 'time': time}[c['type']].fromisoformat(text)
                    except ValueError:
                        return None, f"Zeile {len(clean_rows)+1}: {c['label']} ist ungültig."
                cleaned[c['id']] = text
            clean_rows.append(cleaned)
        minimum = max(item['min_rows'], 1 if required else 0)
        if not minimum <= len(clean_rows) <= item['max_rows']:
            return None, f"Bitte {minimum} bis {item['max_rows']} Zeilen erfassen."
        return clean_rows or None, ''
    if kind == 'signature':
        value = load(raw, {})
        strokes = value.get('strokes') or []
        if not strokes:
            return None, 'Bitte unterschreiben.' if required else ''
        if not isinstance(strokes, list) or len(strokes) > 100:
            return None, 'Unterschrift ist ungültig.'
        clean_strokes, count = [], 0
        for stroke in strokes:
            if not isinstance(stroke, list) or len(stroke) < 2:
                continue
            points = []
            for point in stroke:
                count += 1
                if count > 5000 or not isinstance(point, list) or len(point) != 2:
                    return None, 'Unterschrift ist zu groß oder ungültig.'
                if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in point):
                    return None, 'Unterschrift ist ungültig.'
                points.append([round(x, 5) for x in point])
            clean_strokes.append(points)
        name_value = str(value.get('name') or '').strip()[:200]
        if not name_value or not clean_strokes:
            return None, 'Bitte Namen angeben und unterschreiben.'
        from .db import utcnow
        return {'name': name_value, 'strokes': clean_strokes, 'statement': item['statement'], 'at': utcnow().isoformat(timespec='seconds')}, ''
    return None, ''


def calculate(items, answers, errors):
    calculated = {i['id']: i for i in items if i['type'] == 'calculation'}
    visiting, done = set(), set()
    def compute(qid):
        if qid in done:
            return number(answers.get(qid)) or Decimal(0)
        if qid in visiting:
            raise ValueError('Zyklische Berechnung: bitte Formularaufbau prüfen.')
        visiting.add(qid)
        i = calculated[qid]
        nums = []
        known = {q['id'] for q in items}
        for source in i['sources']:
            if source not in known:
                raise ValueError('Quellfeld für Berechnung fehlt.')
            if source in errors:
                raise ValueError('Bitte die Angaben für die Berechnung prüfen.')
            if source in calculated:
                nums.append(compute(source))
            elif i['operation'] == 'table_total':
                rows = answers.get(source) or []
                if not isinstance(rows, list):
                    raise ValueError('Tabellenquelle für Berechnung fehlt.')
                for row in rows:
                    n = number(row.get(i['column']))
                    qty = number(row.get(i['quantity_column'])) if i['quantity_column'] else Decimal(1)
                    if n is None or qty is None:
                        raise ValueError('Ungültige Tabellenwerte für Berechnung.')
                    nums.append(n * qty)
            else:
                value = answers.get(source)
                n = Decimal(0) if value in (None, '') else number(value)
                if n is None:
                    raise ValueError('Berechnung benötigt Zahlen.')
                nums.append(n)
        result = Decimal(0)
        if i['operation'] == 'product':
            result = math.prod(nums) if nums else Decimal(0)
        elif i['operation'] == 'difference':
            result = nums[0] - sum(nums[1:]) if nums else Decimal(0)
        else:
            result = sum(nums, Decimal(0))
        if not result.is_finite() or abs(result) > Decimal('100000000'):
            raise ValueError('Berechnetes Ergebnis liegt außerhalb des zulässigen Bereichs.')
        answers[qid] = str(result.quantize(Decimal(10) ** -i['precision'], rounding=ROUND_HALF_UP))
        done.add(qid)
        visiting.remove(qid)
        return result
    for qid in calculated:
        try:
            compute(qid)
        except (ValueError, InvalidOperation, TypeError) as exc:
            errors[qid] = str(exc)


    for item in items:
        if item['type']=='period' and item.get('within_source') and answers.get(item['id']):
            parent=answers.get(item['within_source']);child=answers[item['id']]
            if not isinstance(parent,dict) or child['start']<parent['start'] or child['end']>parent['end']:
                errors[item['id']]='Das Dienstgeschäft muss innerhalb des Reisezeitraums liegen.'
    for item in items:
        if item['type'] != 'expense_accounting': continue
        try:
            if any(errors.get(item[k]) for k in item if k.endswith('_source')):
                raise ValueError('Bitte zuerst die Quelldaten der Abrechnung prüfen.')
            from . import expense_rules
            answers[item['id']] = expense_rules.calculate(item, answers)
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            errors[item['id']] = str(exc)

def display(item, value):
    kind = item['type']
    if kind == 'route':
        from . import routing
        return routing.display(item, value)
    if kind == 'expense_accounting':
        from . import expense_rules
        return expense_rules.display(item, value)
    if kind == 'period' and isinstance(value, dict):
        def readable(raw):
            try:
                parsed=datetime.fromisoformat(raw)
                return parsed.strftime('%d.%m.%Y %H:%M') if 'T' in raw else parsed.strftime('%d.%m.%Y')
            except (ValueError,TypeError):return str(raw or '')
        return f"{readable(value.get('start', ''))} bis {readable(value.get('end', ''))}"
    if kind == 'table' and isinstance(value, list):
        return '\n'.join(f"{index+1}. " + '; '.join(f"{c['label']}: {'ja' if row.get(c['id']) is True else 'nein' if row.get(c['id']) is False else row.get(c['id'], '')}" for c in item['columns']) for index, row in enumerate(value))
    if kind == 'declaration' and isinstance(value, dict):
        return f"Ausdrücklich bestätigt: {value.get('text', '')} ({value.get('at', '')})"
    if kind == 'signature' and isinstance(value, dict):
        return f"{value.get('name', '')} · gezeichnete Unterschrift · {value.get('at', '')} · {value.get('statement', '')}"
    if kind == 'calculation':
        return str(value).replace('.', ',') + (' ' + item['unit'] if item.get('unit') else '')
    return str(value)


def profile_values(items, values, user):
    """Session user's opted-in defaults; submitted answers always take priority."""
    from .profiles import defaults
    return defaults(items, values, user)
