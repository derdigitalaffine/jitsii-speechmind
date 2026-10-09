"""Safe lifecycle of reusable collections; historical imports remain independent."""
import json
from sqlalchemy import select
from .db import Circulation, CirculationVersion, SeminarMaterial, TrashItem, utcnow


def may_remove(user, bundle):
    # Edit rights, group management and substitution never imply deleting another owner's work.
    return bool(user and (user.is_admin or bundle.owner_id == user.id))


def used_ids(db):
    """Inspect stored sources once per list, including historical and recoverable imports."""
    result=set()
    def collect(raw,collection=True):
        try: data=json.loads(raw or '{}')
        except (ValueError,TypeError):result.add('*');return
        items=data.get('items',[]) if collection and isinstance(data,dict) else [data]
        if not isinstance(items,list):result.add('*');return
        for item in items:
            if isinstance(item,dict) and item.get('bundle_id') is not None:result.add(str(item['bundle_id']))
    for raw in db.scalars(select(Circulation.draft_json)):collect(raw)
    for raw in db.scalars(select(CirculationVersion.content_json)):collect(raw)
    for raw in db.scalars(select(SeminarMaterial.item_json)):collect(raw,False)
    for raw in db.scalars(select(TrashItem.data_json)):
        try:saved=json.loads(raw or '{}')
        except (ValueError,TypeError):result.add('*');continue
        for row in saved.get('rows',[]):
            data=row.get('data',{})
            if row.get('table')=='circulations':collect(data.get('draft_json'))
            if row.get('table')=='circulation_versions':collect(data.get('content_json'))
            if row.get('table')=='seminar_materials':collect(data.get('item_json'),False)
    return result


def used(db,bundle):
    references=used_ids(db)
    return '*' in references or str(bundle.id) in references


def removable(db,bundle,references=None):
    if bundle.shared:return False
    references=used_ids(db) if references is None else references
    return '*' not in references and str(bundle.id) not in references


def trash_access(user, item):
    if not item or item.kind != 'circulation_bundle' or item.expires_at <= utcnow(): return False
    try:
        data = json.loads(item.data_json)
        original = next((r['data'] for r in data['rows'] if r['table'] == 'circulation_bundles'), None)
    except (ValueError, KeyError, TypeError): return False
    return bool(original and (user.is_admin or original.get('owner_id') == user.id))
