"""Source adapters re-check their own module's authority on every entry point."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select
from . import tasks as ts
from .db import DmsRecord, Recording
from .task_models import Task

LABELS = {'dms': 'Ablage', 'recording': 'Aufzeichnung'}


def source_info(db, user, kind, source_id, *, required=False):
    from .main import enabled_modules, own_recording
    info = dict(label=LABELS.get(kind, 'Verknüpfte Quelle'), href='', row=None)
    raw = str(source_id)
    if raw.isdigit():
        if kind == 'dms' and 'dms' in enabled_modules():
            from . import dms
            row = db.get(DmsRecord, int(raw))
            if row and not row.archived_at and dms.record_level(db, user, row):
                info.update(row=row, href=f'/dms/r/{row.id}')
        elif kind == 'recording' and user.can('video'):
            try:
                row = own_recording(db, int(raw), user)
                info.update(row=row, href=f'/recordings/{row.id}')
            except HTTPException:
                pass
    if required and not info['row']:
        raise HTTPException(404, 'Die Quelle ist nicht mehr verfügbar oder Sie haben keinen Zugriff.')
    return info


def create_from_source(db, user, kind, source_id, data, *, idempotency_key=None):
    from .main import enabled_modules
    if 'tasks' not in enabled_modules():
        raise HTTPException(404)
    source_info(db, user, kind, source_id, required=True)
    key = None
    if idempotency_key:
        key = f'{kind}:{source_id}:' + hashlib.sha256(str(idempotency_key).encode()).hexdigest()
    # Descriptions/titles are supplied by the user. We never copy source content to a task automatically.
    return ts.create(db, user, data, source_type=kind, source_id=source_id, source_key=key)


def recording_items(rec):
    summary = json.loads(rec.summary_json or '{}')
    items = summary.get('tasks', summary.get('taskItemList', []))
    return items if isinstance(items, list) else []


def recording_proposals(db, user, rec):
    people = ts.users(db)
    result = []
    for index, item in enumerate(recording_items(rec)[:100]):
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        if not text:
            continue
        name = str(item.get('assignedTo') or '').strip().casefold()
        hits = [p for p in people if name and (p.name.casefold() == name or p.email.casefold() == name)]
        proposed = str(hits[0].id) if len(hits) == 1 else ''
        day = str(item.get('date') or '')[:10]
        try:
            ts.local_date(day, date_only=True)
        except ts.Invalid:
            day = ''
        raw_key = 'id:' + str(item['id']) if item.get('id') else 'hash:' + hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = f'recording:{rec.id}:' + hashlib.sha256(raw_key.encode()).hexdigest()
        old = db.scalar(select(Task).where(Task.source_key == key))
        result.append(dict(index=index, title=text, name=str(item.get('assignedTo') or ''), assignee_id=proposed,
                           due_date=day, raw_key=raw_key, imported=bool(old), ambiguous=len(hits) != 1))
    return result
