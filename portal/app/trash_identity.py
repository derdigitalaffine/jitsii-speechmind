"""Keep restorable identifiers free when SQLite would reuse a deleted row ID."""
import json
from sqlalchemy import event, func, select, text
from .db import DmsArea, DmsFile, DmsRecord, LivePoll, Poll, TrashItem, UserMap, Vote


_INSTALLED = False


def _reserve(mapper, connection, target):
    if target.id is not None or connection.dialect.name != 'sqlite':
        return
    # Serialize allocation with other writers, including an empty trash table.
    connection.execute(text('UPDATE trash_items SET id = id WHERE 0'))
    table = target.__table__
    highest = connection.scalar(select(func.max(table.c.id))) or 0
    saved = connection.info.setdefault('restorable_object_ids', {})
    highest = max(highest, saved.get(table.name, 0))
    for raw in connection.scalars(select(TrashItem.data_json)):
        try:
            rows = json.loads(raw or '{}').get('rows', [])
            for row in rows:
                if row.get('table') == table.name and type(row.get('data', {}).get('id')) is int:
                    highest = max(highest, row['data']['id'])
        except (ValueError, TypeError, AttributeError):
            # Malformed snapshots never reserve an invented identifier.
            continue
    target.id = highest + 1
    saved[table.name] = target.id


def install():
    global _INSTALLED
    if not _INSTALLED:
        for model in (UserMap, DmsArea, DmsRecord, DmsFile, Poll, Vote, LivePoll):
            event.listen(model, 'before_insert', _reserve)
        _INSTALLED = True
