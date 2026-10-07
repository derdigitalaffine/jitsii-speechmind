"""Presentation and editing adapters; saved rule versions remain immutable."""
import json
from datetime import date
from decimal import Decimal
from . import expense_rules as rules
from .form_fields import number

GROUPS = [
 ('Fahrtkosten', 'Kilometersätze und Staffel für anerkannte Privat-Pkw.', ['private_car','private_car_reason','recognized_car','recognized_limit','recognized_after','company_car','motorcycle','motorcycle_reason','bicycle','walk','public_transport']),
 ('Tagegeld', 'Beträge pro Tag und Anteil bei Ausbildungsreisen.', ['day8','day14','day24','local_day','training_factor']),
 ('Mahlzeiten', 'Kürzungsanteile in Prozent und Mindestabzüge als Sachbezugswerte.', ['breakfast_fraction','breakfast_min','lunch_fraction','lunch_min','dinner_fraction','dinner_min']),
 ('Übernachtung', 'Pauschale ohne Nachweis; tatsächliche Hotelkosten werden separat erfasst.', ['overnight']),
]
PERCENT = {'training_factor','breakfast_fraction','lunch_fraction','dinner_fraction'}


def unit(key):
    return '%' if key in PERCENT else 'km/Jahr' if key == 'recognized_limit' else '€/km' if key in GROUPS[0][2] else '€'


def label(key):
    return rules.LABELS[key].replace(' (€/km)', '').replace(' (€)', '').replace('Faktor Ausbildungsreise', 'Ausbildungsreise: Anteil des Tagegelds').replace('Frühstück: Anteil des zustehenden Tagegelds', 'Frühstück: Kürzungsanteil').replace('Mittagessen: Anteil', 'Mittagessen: Kürzungsanteil').replace('Abendessen: Anteil', 'Abendessen: Kürzungsanteil')


def display(key, value, localized=False):
    value = number(value)
    if value is None:
        return ''
    if key in PERCENT:
        value *= 100
    result = format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')
    return result.replace('.', ',') if localized else result


def rates(row):
    try:
        result = json.loads(row.rates_json)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def source_parts(row):
    source, sep, reason = row.source.rpartition('; Änderungsgrund: ')
    return (source, reason) if sep else (row.source, '')


def initial(row=None):
    values = {'profile':'rlp', 'name':'Reisekostensätze', 'source':rules.SOURCE, 'valid_from':'', 'valid_until':'', 'base_id':''}
    values.update({key:display(key, value) for key,value in rules.PROPOSAL.items()})
    if row:
        values.update(profile=row.profile, name=row.name, source=source_parts(row)[0], valid_from=row.valid_from.isoformat(), valid_until=row.valid_until.isoformat(), base_id=str(row.id))
        values.update({key:display(key, rates(row).get(key)) for key in rules.LABELS})
    return values


def posted(raw):
    """UI uses percentages; old raw API form submissions stay compatible."""
    values = dict(raw)
    if values.get('editor_format') == 'percent':
        for key in PERCENT:
            n = number(values.get(key))
            values[key] = str(n / Decimal(100)) if n is not None else ''
    return values


def overview(row, active_ids):
    today = date.today()
    status = 'Künftig' if row.valid_from > today else 'Abgelaufen' if row.valid_until < today else 'Heute aktiv' if row.id in active_ids else 'Heute durch neuere Fassung ersetzt'
    return {'row':row, 'status':status, 'values':{key:display(key,rates(row).get(key),True) for key in rules.LABELS}, 'source':source_parts(row)[0], 'reason':source_parts(row)[1]}
