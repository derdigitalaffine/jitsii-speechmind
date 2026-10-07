"""Replaceable OSRM services and signed route results for reusable form fields."""
import hashlib
import json
import math
from datetime import timedelta
from urllib.parse import urlparse
import httpx
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from .config import settings
from .db import GeoCache, SessionLocal, get_settings, utcnow
from .geo_services import paced

DEFAULTS = {'car': 'https://routing.openstreetmap.de/routed-car',
            'bike': 'https://routing.openstreetmap.de/routed-bike',
            'foot': 'https://routing.openstreetmap.de/routed-foot'}
CATEGORIES = {
    'private_car': ('Privat-Pkw', 'car'),
    'recognized_car': ('Anerkannter Privat-Pkw', 'car'),
    'company_car': ('Dienstfahrzeug', 'car'),
    'motorcycle': ('Motorrad / Motorroller', 'car'),
    'bicycle': ('Fahrrad', 'bike'),
    'walk': ('Zu Fuß', 'foot'),
    'public_transport': ('Öffentliche Verkehrsmittel', None),
}
_SIGNER = URLSafeSerializer(settings.secret_key, salt='portal-route-v1')


def config():
    with SessionLocal() as db:
        cfg = get_settings(db)
    return {k: (cfg.get('routing_' + k + '_url') or v).rstrip('/') for k, v in DEFAULTS.items()}


def public_service(url):
    host = (urlparse(url).hostname or '').lower()
    return host == 'routing.openstreetmap.de'


def coordinate(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return None
        return round(lat, 6), round(lon, 6)
    except (TypeError, ValueError):
        return None


def quote(points, category, public_points=False):
    if category not in CATEGORIES or not 2 <= len(points) <= 12:
        raise ValueError('Bitte Verkehrsmittel sowie Start und Ziel wählen (höchstens zehn Zwischenstopps).')
    cleaned = []
    for point in points:
        if not isinstance(point, dict) or not coordinate(point.get('lat'), point.get('lon')):
            raise ValueError('Für alle Punkte werden gültige Koordinaten benötigt.')
        lat, lon = coordinate(point['lat'], point['lon'])
        cleaned.append({'label': str(point.get('label') or f'{lat}, {lon}')[:300], 'lat': lat, 'lon': lon})
    profile = CATEGORIES[category][1]
    url = config().get(profile) if profile else ''
    if url and public_service(url) and not public_points:
        raise ValueError('Der öffentliche Routingdienst darf hier nur für öffentliche Orte verwendet werden. Für persönliche oder vertrauliche Punkte einen geeigneten Dienst konfigurieren.')
    result = {'category': category, 'profile': profile, 'points': cleaned, 'provider': url,
              'at': utcnow().isoformat(timespec='seconds'), 'meters': 0, 'seconds': 0,
              'geometry': {'type': 'LineString', 'coordinates': [[p['lon'], p['lat']] for p in cleaned]}}
    if profile:
        coords = ';'.join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in cleaned)
        endpoint = url + '/route/v1/driving/' + coords
        params = {'overview': 'simplified', 'geometries': 'geojson', 'steps': 'false'}
        key = hashlib.sha256((endpoint + json.dumps(params, sort_keys=True)).encode()).hexdigest()
        with SessionLocal() as db:
            hit = db.get(GeoCache, key)
            cached = json.loads(hit.value_json) if hit and hit.created_at > utcnow() - timedelta(days=30) else None
        if cached is None:
            try:
                with paced('routing'):
                    response = httpx.get(endpoint, params=params, headers={'User-Agent': f'Verwaltungsportal ({settings.portal_base_url})'}, timeout=12, follow_redirects=False)
                    if response.status_code != 200:
                        raise ValueError('Routingdienst derzeit nicht verfügbar. Bitte später erneut berechnen.')
                    cached = response.json()
                if cached.get('code') != 'Ok' or not cached.get('routes'):
                    raise ValueError('Keine befahrbare Strecke gefunden. Punkte prüfen oder einen geeigneten Dienst verwenden.')
                with SessionLocal() as db:
                    db.merge(GeoCache(key=key, value_json=json.dumps(cached), created_at=utcnow()))
                    db.commit()
            except (httpx.HTTPError, TypeError, KeyError):
                raise ValueError('Routingdienst derzeit nicht verfügbar. Bitte später erneut berechnen.') from None
        route = cached['routes'][0]
        distance, duration = route.get('distance'), route.get('duration')
        if not isinstance(distance, (int, float)) or not math.isfinite(distance) or not 0 <= distance <= 20000000:
            raise ValueError('Routingdienst hat eine ungültige Entfernung geliefert.')
        geometry = route.get('geometry') or {}
        if geometry.get('type') != 'LineString' or not isinstance(geometry.get('coordinates'), list) or len(geometry['coordinates']) > 10000:
            raise ValueError('Routingdienst hat eine ungültige Geometrie geliefert.')
        if any(not isinstance(p, list) or len(p) != 2 or not coordinate(p[1], p[0]) for p in geometry['coordinates']):
            raise ValueError('Routingdienst hat ungültige Koordinaten geliefert.')
        result.update(meters=round(distance), seconds=round(duration) if isinstance(duration, (int,float)) and math.isfinite(duration) else 0, geometry=geometry)
    else:
        result['note'] = 'Öffentliche Verkehrsmittel: Kosten über Belege erfassen; keine automatische Straßenkilometerberechnung.'
    result['proof'] = _SIGNER.dumps(result)
    return result


def verified_quote(value):
    if not isinstance(value, dict):
        raise ValueError('Bitte Strecke neu berechnen.')
    try:
        signed = _SIGNER.loads(str(value.get('proof') or ''))
    except BadSignature:
        raise ValueError('Streckenberechnung ist ungültig. Bitte neu berechnen.') from None
    unsigned = {k: v for k, v in value.items() if k != 'proof'}
    if signed != unsigned:
        raise ValueError('Streckenberechnung wurde geändert. Bitte neu berechnen.')
    return signed


def clean(raw):
    from .form_fields import bounded
    return {'max_legs': bounded(raw.get('max_legs'), 1, 30, 10), 'allow_roundtrip': raw.get('allow_roundtrip') is not False,
            'allow_deviation': raw.get('allow_deviation') is not False}


def parse(item, data, name):
    from .form_fields import load, number
    from decimal import Decimal, ROUND_HALF_UP
    raw = data.get(name)
    if not raw:
        return None, 'Bitte eine Strecke erfassen.' if item.get('required') else ''
    value = load(raw, {})
    legs = value.get('legs') if isinstance(value, dict) else None
    if not isinstance(legs, list) or not 1 <= len(legs) <= item.get('max_legs', 10):
        return None, 'Bitte die Fahrtabschnitte prüfen.'
    cleaned, total, calculated = [], 0, 0
    try:
        for leg in legs:
            if not isinstance(leg, dict):
                raise ValueError('Ungültiger Fahrtabschnitt.')
            date_value = str(leg.get('date') or '')
            if date_value:
                from datetime import date
                try: date.fromisoformat(date_value)
                except ValueError: raise ValueError('Ungültiges Datum des Fahrtabschnitts.')
            quote_value = verified_quote(leg.get('quote'))
            meters = quote_value['meters']
            actual = leg.get('actual_km')
            reason = str(leg.get('reason') or '').strip()[:2000]
            if actual not in (None, ''):
                n = number(actual)
                if not item.get('allow_deviation') or n is None or not 0 <= n <= Decimal('20000'):
                    raise ValueError('Ungültige tatsächliche Kilometer.')
                actual_meters = int((n * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                if actual_meters != meters and not reason:
                    raise ValueError('Bitte die Abweichung von der berechneten Strecke begründen.')
            else:
                actual_meters = meters
            cleaned.append({'date':date_value,'quote': leg['quote'], 'actual_km': str(actual) if actual not in (None,'') else '',
                            'reason': reason, 'meters': actual_meters, 'deviation': actual_meters != meters})
            total += actual_meters
            calculated += meters
    except (ValueError, KeyError, TypeError) as exc:
        return None, str(exc)
    return {'legs': cleaned, 'meters': total, 'calculated_meters': calculated,
            'has_deviation': any(l['deviation'] for l in cleaned)}, ''


def display(item, value):
    if not isinstance(value, dict):
        return ''
    rows = []
    for leg in value.get('legs', []):
        q = leg.get('quote') or {}
        text = ' -> '.join(p.get('label', '') for p in q.get('points', []))
        rows.append(f"{CATEGORIES.get(q.get('category'), ('',))[0]}: {text}; {int(leg.get('meters', q.get('meters',0)))/1000:.3f} km" + (f" (berechnet {q.get('meters',0)/1000:.3f} km; Abweichung: {leg.get('reason','')})" if leg.get('deviation') else ''))
    return '\n'.join(rows)
