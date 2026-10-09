"""Ownership, dependency protection and recoverable DMS deletion."""
import hashlib
import json
from sqlalchemy import select
from .db import (Circulation, CirculationBundle, CirculationVersion, DmsArea, DmsFile,
                 DmsRecord, Form, KrankReport, SeminarMaterial, TrashItem, utcnow)


def owns(user, record):
    return bool(user.is_admin or (record.owner_id is not None and record.owner_id == user.id))


def _references(value, ids):
    if isinstance(value, dict):
        if value.get('kind') == 'dms' and str(value.get('id')) in ids:
            return True
        return any(_references(v, ids) for v in value.values())
    return isinstance(value, list) and any(_references(v, ids) for v in value)


def references(db, files):
    ids = {str(f.id) for f in files}
    if not ids:
        return []
    hits = []
    for model, column, label in ((Circulation, 'draft_json', 'Umlauf'),
            (CirculationBundle, 'draft_json', 'Sammelmappe'),
            (CirculationVersion, 'content_json', 'Veröffentlichter Umlauf'),
            (SeminarMaterial, 'item_json', 'Seminarunterlage'),
            (TrashItem, 'data_json', 'Wiederherstellbarer Papierkorbeintrag')):
        for obj in db.scalars(select(model)):
            try:
                value = json.loads(getattr(obj, column) or '{}')
                # Trash snapshots contain JSON strings inside row values.
                if model is TrashItem:
                    def expand(v):
                        if isinstance(v, str) and v[:1] in '{[':
                            try: return expand(json.loads(v))
                            except ValueError: return v
                        if isinstance(v, dict): return {k: expand(x) for k, x in v.items()}
                        if isinstance(v, list): return [expand(x) for x in v]
                        return v
                    value = expand(value)
                if _references(value, ids): hits.append(f'{label} #{obj.id}')
            except (ValueError, TypeError):
                hits.append(f'{label} #{obj.id}: Verknüpfungen nicht sicher prüfbar')
    return hits


def protection(db, record):
    reasons = references(db, record.files)
    if record.retention_until and record.retention_until > utcnow():
        reasons.append('Aufbewahrungsfrist läuft noch')
    if record.response and record.response.status not in {'done', 'approved', 'rejected', 'withdrawn'}:
        reasons.append('Laufender Antrag')
    if db.scalar(select(KrankReport.id).where(KrankReport.dms_record_id == record.id, KrankReport.status != 'done').limit(1)):
        reasons.append('Laufende Krankmeldung')
    if record.booking_id:
        reasons.append('Verknüpfte Ressourcenbuchung')
    return reasons


def file_protection(db, file):
    return protection(db, file.record) + ([] if file.kind == 'upload' else ['Unveränderlicher Abschlussstand'])


def folder_preview(db, area_id):
    from . import dms
    ids = dms.subtree_ids(db, area_id)
    areas = list(db.scalars(select(DmsArea).where(DmsArea.id.in_(ids)).order_by(DmsArea.id)))
    records = list(db.scalars(select(DmsRecord).where(DmsRecord.area_id.in_(ids)).order_by(DmsRecord.id)))
    forms = list(db.scalars(select(Form).where(Form.dms_area_id.in_(ids))))
    reasons = {r.id: protection(db, r) for r in records}
    links = _area_links(db, ids)
    if links: reasons['links'] = links
    if forms: reasons['forms'] = [f'Formular #{f.id}: {f.title}' for f in forms]
    if any(a.system_key for a in areas): reasons['system'] = ['Fest eingerichteter Systemordner']
    payload = {'areas': [(a.id,a.parent_id,a.name) for a in areas],
               'records': [(r.id,r.area_id,r.updated_at.isoformat(), [(f.id,f.sha256) for f in r.files]) for r in records],
               'reasons': {str(k):v for k,v in reasons.items()}}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return dict(areas=areas, records=records, reasons=reasons, fingerprint=fingerprint,
                count=len(areas)+len(records), blocked=any(reasons.values()))


def restore_error(db, item):
    data = json.loads(item.data_json or '{}')
    restored_areas = {row['data']['id'] for row in data.get('rows', []) if row['table'] == 'dms_areas'}
    for row in data.get('rows', []):
        if row['table'] == 'dms_areas':
            parent_id = row['data'].get('parent_id')
            if parent_id and parent_id not in restored_areas and not db.get(DmsArea, parent_id):
                return 'Der ursprüngliche übergeordnete Ordner fehlt. Bitte einen berechtigten Zielordner auswählen.'
        if row['table'] == 'dms_records' and not db.get(DmsArea, row['data']['area_id']) and row['data']['area_id'] not in restored_areas:
            return 'Der ursprüngliche Ordner fehlt. Bitte in der Ablage einen berechtigten Zielordner auswählen.'
        if row['table'] == 'dms_files' and item.kind == 'dms_file':
            parent = db.get(DmsRecord, row['data']['record_id'])
            if not parent:
                return 'Der übergeordnete Ablageeintrag muss zuerst wiederhergestellt werden.'
            if parent.archived_at:
                return 'Den archivierten Ablageeintrag vor der Dateiwiederherstellung ausdrücklich reaktivieren.'
    return None


def area_protection(db, area):
    reasons = []
    if area.system_key: reasons.append('Fest eingerichteter Systemordner')
    if db.scalar(select(DmsArea.id).where(DmsArea.parent_id == area.id).limit(1)): reasons.append('Unterordner vorhanden')
    if db.scalar(select(DmsRecord.id).where(DmsRecord.area_id == area.id).limit(1)): reasons.append('Einträge vorhanden')
    reasons.extend(_area_links(db, {area.id}))
    return reasons


def _area_links(db, ids):
    from .db import Base
    links = []
    for table in Base.metadata.sorted_tables:
        if table.name in {'dms_areas','dms_records','dms_access'}: continue
        for fk in table.foreign_keys:
            if fk.column.table.name == 'dms_areas':
                for row in db.execute(select(table).where(fk.parent.in_(ids))).mappings():
                    links.append(f"{table.name} #{row.get('id', '?')}: Ordnerverknüpfung")
    return links
