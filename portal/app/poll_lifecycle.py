"""Shared lifecycle policy for appointment polls, votes and live polls."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from .db import Poll, Vote, LivePoll, VoteBallot, LiveAnswer, SeminarActivity, Seminar, TrashItem, utcnow

MODELS = {'poll': Poll, 'vote': Vote, 'live_poll': LivePoll}


def owner(obj, user):
    return user.is_admin or obj.owner_id == user.id


def require_owner(obj, user):
    if not owner(obj, user):
        raise HTTPException(403, 'Nur die erstellende Person oder die Administration darf diese Aktion ausführen.')


def mutable(obj):
    if obj.archived_at:
        raise HTTPException(409, 'Diese Umfrage ist archiviert. Ergebnisse bleiben lesbar; Änderungen sind gesperrt.')


def mark_used(obj):
    obj.used_at = obj.used_at or utcnow()


def removable(db, kind, obj):
    if obj.used_at:
        return False
    if kind == 'poll':
        if obj.published_at or obj.public_token or obj.participants or obj.shares or obj.meeting_id or obj.final_option_id:
            return False
        if db.scalar(select(Seminar.id).where(Seminar.poll_id == obj.id).limit(1)):
            return False
    elif kind == 'vote':
        if obj.status != 'draft' or obj.opened_at or obj.closed_at or obj.voters or obj.shares:
            return False
        if db.scalar(select(VoteBallot.id).where(VoteBallot.vote_id == obj.id).limit(1)):
            return False
    else:
        if obj.status != 'draft' or obj.opened_at:
            return False
        if db.scalar(select(LiveAnswer.id).where(LiveAnswer.poll_id == obj.id).limit(1)):
            return False
    activity_kind = 'live' if kind == 'live_poll' else kind
    if db.scalar(select(SeminarActivity.id).where(SeminarActivity.kind == activity_kind,
                                                  SeminarActivity.object_id == obj.id).limit(1)):
        return False
    # Archived parents in the trash must be able to recover their links too.
    for item in db.scalars(select(TrashItem)):
        try:
            snapshot = json.loads(item.data_json or '{}')
            for row in snapshot.get('rows', []):
                data = row.get('data', {})
                if row.get('table') == 'seminar_activities' and data.get('kind') == activity_kind and data.get('object_id') == obj.id:
                    return False
                if kind == 'poll' and row.get('table') == 'seminars' and data.get('poll_id') == obj.id:
                    return False
        except (ValueError, TypeError, AttributeError):
            return False
    return True


def archive(db, kind, obj):
    if kind == 'poll':
        obj.closed = True
    elif kind == 'vote':
        from .votes import close
        if obj.status != 'closed':
            close(db, obj)
    else:
        obj.status = 'closed'
    obj.archived_at = utcnow()


def remove(db, kind, obj, user):
    require_owner(obj, user)
    if removable(db, kind, obj):
        from .trash import delete_obj
        delete_obj(db, kind, obj, user.name)
        return 'deleted'
    archive(db, kind, obj)
    return 'archived'


def trash_owner(item):
    try:
        rows = json.loads(item.data_json or '{}').get('rows', [])
        return next(r['data'].get('owner_id') for r in rows if r.get('table') == item.table_name and r['data'].get('id') == item.row_id)
    except (ValueError, TypeError, KeyError, StopIteration):
        return None


def trash_items(db, kinds, user):
    return [item for item in db.scalars(select(TrashItem).where(TrashItem.kind.in_(kinds), TrashItem.expires_at > utcnow()).order_by(TrashItem.deleted_at.desc()))
            if user.is_admin or trash_owner(item) == user.id]


def restored(obj, kind):
    obj.archived_at = None
    if kind == 'poll':
        obj.closed = True
        obj.public_token = None
        obj.published_at = None
    else:
        obj.status = 'draft'


def prepare_restore(db, kind, data):
    for row in data.get('rows', []):
        if row.get('table') == MODELS[kind].__tablename__:
            values = row['data']
            values['archived_at'] = None
            if kind == 'poll':
                values.update(closed=True, public_token=None, published_at=None)
            else:
                from .security import new_link_token
                values['status'] = 'draft'
                values['public_token'] = new_link_token()
    return data
