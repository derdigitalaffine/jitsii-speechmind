"""Central public POIs, personal favourites and CSV exchange."""
import csv
import io
import json
from sqlalchemy import or_, select
from . import csvsafe
from .db import PortalLocation, LocationFavorite, get_settings
from .routing import coordinate

COLUMNS = ('name','category','street','zip','city','lat','lon','public')


def can_manage(db, user):
    if user is None:
        return False
    cfg = get_settings(db)
    groups = {int(x) for x in cfg.get('location_manager_groups','').split(',') if x.isdigit()}
    return user.can('locations_manage') or bool(groups & {g.id for g in user.groups})


def visible(db, user):
    q = select(PortalLocation).where(PortalLocation.active.is_(True))
    if user:
        q = q.where(or_(PortalLocation.owner_id.is_(None), PortalLocation.owner_id == user.id))
    else:
        q = q.where(PortalLocation.owner_id.is_(None), PortalLocation.public.is_(True))
    return list(db.scalars(q.order_by(PortalLocation.category, PortalLocation.name)))


def data(location):
    return {k:getattr(location,k) for k in COLUMNS} | {'id':location.id}


def label(location):
    return ', '.join(x for x in (location.name, location.street, ' '.join(x for x in (location.zip, location.city) if x)) if x)


def clean(raw):
    name = str(raw.get('name') or '').strip()[:200]
    if not name:
        raise ValueError('Bitte einen Namen für den Ort angeben.')
    lat, lon = raw.get('lat'), raw.get('lon')
    coords = coordinate(lat,lon) if lat not in ('',None) or lon not in ('',None) else None
    if (lat not in ('',None) or lon not in ('',None)) and coords is None:
        raise ValueError('Bitte gültige Breiten- und Längengrade angeben.')
    return {'name':name, 'category':str(raw.get('category') or '')[:100], 'street':str(raw.get('street') or '')[:255],
            'zip':str(raw.get('zip') or '')[:10], 'city':str(raw.get('city') or '')[:200],
            'lat':coords[0] if coords else None,'lon':coords[1] if coords else None,
            'public':raw.get('public') in (True,'1','true','ja')}


def export(rows):
    buf = io.StringIO(); writer=csvsafe.writer(buf,delimiter=';')
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([getattr(row,c) if c != 'public' else int(row.public) for c in COLUMNS])
    return '\ufeff'+buf.getvalue()


def import_rows(db, content, owner_id=None):
    if len(content)>2*1024*1024:
        raise ValueError('CSV darf höchstens 2 MB groß sein.')
    try:
        text=content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Bitte eine UTF-8-CSV verwenden.') from None
    reader=csv.DictReader(io.StringIO(text),delimiter=';')
    if not reader.fieldnames or 'name' not in reader.fieldnames:
        raise ValueError('CSV benötigt die Spalte name und verwendet Semikolon als Trennzeichen.')
    cleaned=[]
    for number, raw in enumerate(reader,2):
        if len(cleaned)>=1000:
            raise ValueError('Höchstens 1.000 Orte je Import.')
        try:
            cleaned.append(clean(raw))
        except ValueError as exc:
            raise ValueError(f'Zeile {number}: {exc}') from None
    for value in cleaned:
        db.add(PortalLocation(owner_id=owner_id,**value))
    db.flush()
    return len(cleaned)


def seed_offices(db):
    # Addresses verified against the municipality's official opening-hours page.
    # Coordinates intentionally require an explicit lookup/confirmation, never bulk geocoding.
    seeds=[('Rathaus Otterbach','Konrad-Adenauer-Straße 19','67731','Otterbach'),
           ('Rathaus Otterberg','Hauptstraße 27','67697','Otterberg')]
    count=0
    for name, street, zip_code, city in seeds:
        if db.scalar(select(PortalLocation.id).where(PortalLocation.owner_id.is_(None),PortalLocation.name==name)) is None:
            db.add(PortalLocation(name=name,category='Dienststätten',street=street,zip=zip_code,city=city,public=True))
            count+=1
    return count
