"""Private map recovery without silently re-enabling old access."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from .db import UserMap, User, Group, utcnow


def can_manage(saved, user):
    return bool(user.is_admin or saved.owner_id == user.id)


def valid_shares(db, raw):
    try:
        value = json.loads(raw or '{}')
    except (ValueError, TypeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    result = {}
    for key, model in (('users', User), ('groups', Group)):
        values = value.get(key, [])
        ids = [i for i in values if type(i) is int] if isinstance(values, list) else []
        query = select(model.id).where(model.id.in_(ids))
        if model is User:
            query = query.where(User.active.is_(True))
        result[key] = list(db.scalars(query))[:500]
    return result


def trash_access(user, item):
    if not item or item.kind != 'user_map' or item.expires_at <= utcnow():
        return False
    try:
        original = next(row['data'] for row in json.loads(item.data_json)['rows'] if row['table'] == 'user_maps')
    except (ValueError, TypeError, KeyError, StopIteration):
        return False
    return bool(user.is_admin or original.get('owner_id') == user.id)


def remove(db, saved, user):
    if not can_manage(saved, user):
        raise HTTPException(403)
    from . import trash
    item = trash.delete_obj(db, 'user_map', saved, user.name)
    trash.log(db, user.name, 'delete', 'user_map', 1, item.label)
    return item


def prepare_restore(db, data):
    """Applied by the shared trash service, including administrator restores."""
    for row in data.get('rows', []):
        if row.get('table') == 'user_maps':
            values = row['data']
            old = values.get('share_json') or '{}'
            suggested = valid_shares(db, old)
            if not any(suggested.values()):
                suggested = valid_shares(db, values.get('restore_share_json'))
            values['restore_share_json'] = json.dumps(suggested)
            values['share_json'] = '{}'
            values['public_token'] = None
    return data
