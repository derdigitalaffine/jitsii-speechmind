"""Additional opt-in form rules, shared schema and server validation helpers."""
import math
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from .db import to_local, utcnow

DATE_KEYS = ('relative_min', 'relative_max', 'min_age', 'max_age', 'date_gap_min', 'date_gap_max')

def integer(value, low, high):
    try:
        if isinstance(value, bool) or str(value).strip() != str(int(value)):
            return None
        number = int(value)
        return number if low <= number <= high else None
    except (ValueError, TypeError, OverflowError):
        return None


def clean(item, src):
    kind = item['type']
    if kind in ('date', 'datetime'):
        if src.get('date_rule') in ('past', 'future'):
            item['date_rule'] = src['date_rule']
            item['include_today'] = src.get('include_today') is not False
        for key in DATE_KEYS:
            val = integer(src.get(key), -36500 if key.startswith('relative') else 0, 150 if key.endswith('age') else 36500)
            if val is not None:
                item[key] = val
        ref = str(src.get('date_reference') or '')
        if ref:
            item['date_reference'] = ref[:40]
        for key in ('min', 'max'):
            if item.get(key):
                try:
                    item[key] = date.fromisoformat(item[key][:10]).isoformat()
                except ValueError:
                    item[key] = ''
    if kind in ('short', 'long'):
        for key in ('min_length', 'max_length'):
            val = integer(src.get(key), 1, 1000 if kind == 'short' else 20000)
            if val is not None:
                item[key] = val
        if kind == 'short' and item.get('subtype') == 'number':
            try:
                step = float(src.get('step'))
                if math.isfinite(step) and step > 0:
                    item['step'] = step
            except (ValueError, TypeError, OverflowError):
                pass
    message = str(src.get('validation_message') or '').strip()[:500]
    if message and kind in ('date', 'datetime', 'short', 'long', 'checkbox', 'file'):
        item['validation_message'] = message


def clean_references(items):
    dates = {i['id']: i for i in items if i['type'] in ('date', 'datetime')}
    for item in dates.values():
        ref = item.get('date_reference')
        seen = {item['id']}
        while ref:
            if ref not in dates or ref in seen:
                item.pop('date_reference', None)
                break
            seen.add(ref)
            ref = dates[ref].get('date_reference')


def schema_errors(items):
    """Describe contradictory bounds before an editor saves an unusable form."""
    errors = {}
    pairs = (('min', 'max', 'Unter- und Obergrenze'),
             ('relative_min', 'relative_max', 'Zeitraum ab heute'),
             ('min_age', 'max_age', 'Altersgrenzen'),
             ('date_gap_min', 'date_gap_max', 'Abstand zum Bezugsdatum'),
             ('min_length', 'max_length', 'Textlänge'))
    for item in items:
        for low, high, label in pairs:
            if item.get(low) is not None and item.get(low) != '' and item.get(high) is not None and item.get(high) != '':
                if item[low] > item[high]:
                    errors[item['id']] = label + ': Die Untergrenze darf nicht größer als die Obergrenze sein.'
                    break
        if item['type'] in ('date', 'datetime') and item['id'] not in errors:
            limits = constraints(item)
            if limits.get('min') and limits.get('max') and limits['min'] > limits['max']:
                errors[item['id']] = 'Die Datumsregeln lassen derzeit kein gültiges Datum zu. Bitte den Zeitraum oder die Altersgrenzen anpassen.'
    return errors


def age_date(today, years):
    """Leap birthdays become 28 February in a non-leap year."""
    try:
        return today.replace(year=today.year-years)
    except ValueError:
        return today.replace(year=today.year-years, day=28)


def constraints(item, today=None):
    today = today or to_local(utcnow()).date()
    result = {'today': today.isoformat()}
    low, high = [], []
    for key, target in (('min', low), ('max', high)):
        if item.get(key):
            try:
                target.append(date.fromisoformat(item[key][:10]))
            except ValueError:
                pass
    if item.get('date_rule') == 'past':
        high.append(today if item.get('include_today', True) else today-timedelta(days=1))
    if item.get('date_rule') == 'future':
        low.append(today if item.get('include_today', True) else today+timedelta(days=1))
    for key, target in (('relative_min', low), ('relative_max', high)):
        if item.get(key) is not None:
            target.append(today+timedelta(days=item[key]))
    if item.get('min_age') is not None:
        high.append(age_date(today, item['min_age']))
    if item.get('max_age') is not None:
        low.append(age_date(today, item['max_age']+1)+timedelta(days=1))
    if low: result['min'] = max(low).isoformat()
    if high: result['max'] = min(high).isoformat()
    for key in ('date_reference', 'date_gap_min', 'date_gap_max', 'validation_message'):
        if key in item: result[key] = item[key]
    return result


def hint(item):
    parts = []
    if item['type'] in ('date', 'datetime'):
        rule = item.get('date_rule')
        if rule:
            parts.append(('Nicht in der Zukunft' if rule == 'past' else 'Nicht in der Vergangenheit') + ('; heute erlaubt' if item.get('include_today', True) else '; heute ausgeschlossen'))
        for key, label in (('min', 'Frühestens'), ('max', 'Spätestens')):
            if item.get(key):
                try:
                    parts.append(label+' '+date.fromisoformat(item[key][:10]).strftime('%d.%m.%Y'))
                except ValueError:
                    pass
        for key, label in (('relative_min', 'Frühestens'), ('relative_max', 'Spätestens')):
            if item.get(key) is not None: parts.append(f"{label} heute {item[key]:+d} Tage")
        for key, label in (('min_age', 'Mindestalter'), ('max_age', 'Höchstalter')):
            if item.get(key) is not None: parts.append(f"{label}: {item[key]} Jahre")
        if item.get('date_reference'):
            parts.append('Ab dem Bezugsdatum' if not item.get('date_gap_min') else f"Mindestens {item['date_gap_min']} Tage nach dem Bezugsdatum")
            if item.get('date_gap_max') is not None: parts.append(f"Höchstens {item['date_gap_max']} Tage nach dem Bezugsdatum")
    for key, label in (('min_length', 'Mindestens'), ('max_length', 'Höchstens')):
        if item.get(key): parts.append(f"{label} {item[key]} Zeichen")
    if item.get('step'): parts.append(f"Schrittweite: {item['step']:g}")
    return ' · '.join(parts)


def error(item, value, all_values, *, relationship_only=False):
    if value in (None, '', []): return ''
    kind = item['type']
    message = ''
    if kind in ('short', 'long'):
        if item.get('min_length') and len(str(value)) < item['min_length']:
            message = f"Bitte mindestens {item['min_length']} Zeichen eingeben."
        if item.get('max_length') and len(str(value)) > item['max_length']:
            message = f"Bitte höchstens {item['max_length']} Zeichen eingeben."
        if kind == 'short' and item.get('subtype') == 'url':
            try:
                parsed = urlsplit(str(value))
                if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                        parsed.username is not None or parsed.password is not None or
                        any(char.isspace() or ord(char) < 32 for char in str(value))):
                    message = 'Bitte eine vollständige HTTP- oder HTTPS-Adresse angeben.'
                _ = parsed.port  # Invalid/out-of-range ports raise ValueError.
            except ValueError:
                message = 'Bitte eine gültige Internetadresse angeben.'
        if kind == 'short' and item.get('subtype') == 'number' and item.get('step'):
            try:
                num = Decimal(str(value).replace(',', '.'))
                base = Decimal(str(item.get('min') or 0))
                step = Decimal(str(item['step']))
                if not num.is_finite() or (num-base) % step != 0:
                    message = f"Bitte Schritte von {item['step']:g} ab {base} verwenden."
            except InvalidOperation:
                message = 'Bitte eine gültige Zahl angeben.'
    if kind in ('date', 'datetime'):
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return ''  # Original parser reports malformed values.
        limits = {} if relationship_only else constraints(item)
        low, high = limits.get('min'), limits.get('max')
        ref = all_values.get(item.get('date_reference'))
        if ref:
            try:
                reference = date.fromisoformat(str(ref)[:10])
                ref_low = reference+timedelta(days=item.get('date_gap_min', 0))
                low = max(low or ref_low.isoformat(), ref_low.isoformat())
                if item.get('date_gap_max') is not None:
                    ref_high = reference+timedelta(days=item['date_gap_max'])
                    high = min(high or ref_high.isoformat(), ref_high.isoformat())
            except ValueError:
                pass
            except OverflowError:
                message = 'Der Abstand zum Bezugsdatum liegt außerhalb des gültigen Datumsbereichs.'
        if low and d.isoformat() < low: message = 'Frühestens '+date.fromisoformat(low).strftime('%d.%m.%Y')+'.'
        if high and d.isoformat() > high: message = 'Spätestens '+date.fromisoformat(high).strftime('%d.%m.%Y')+'.'
    return item.get('validation_message') or message if message else ''
