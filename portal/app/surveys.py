"""One permission-filtered workspace for the existing survey engines.

This presentation adapter deliberately keeps each engine's participation and lifecycle rules.
"""
from urllib.parse import urlencode

from sqlalchemy import func, select
from . import live as lv, polls as pl, shares as sh, votes as vt
from .db import LiveAnswer, LivePoll, Poll, PollParticipant, Vote, VoteBallot

KINDS = {
    'live': ('Live-Umfrage', 'fa-tower-broadcast', 'Gemeinsam in einer Veranstaltung: QR-Code, Moderation, Quiz, Wortwolken und Präsentation.'),
    'poll': ('Terminumfrage', 'fa-calendar-check', 'Termine vorschlagen, Verfügbarkeit sammeln und einen gemeinsamen Termin festlegen.'),
    'vote': ('Abstimmung', 'fa-check-to-slot', 'Zwischen Optionen entscheiden. Wahlberechtigte, Geheimhaltung und förmliche Regeln bei Bedarf ergänzen.'),
}


def available(user, modules):
    return [key for key in KINDS if 'polls' in modules
            and user.can('polls' if key == 'poll' else 'votes')]


def url(**values):
    return '/umfragen' + ('?' + urlencode({k: v for k, v in values.items() if v and v != 'all'}) if any(v and v != 'all' for v in values.values()) else '')


def _visible(db, model, user, shared, all_objects):
    own = select(model)
    if not all_objects:
        own = own.where(model.owner_id == user.id)
    rows = {obj.id: (obj, 4) for obj in db.scalars(own)}
    for obj, level in shared:
        rows.setdefault(obj.id, (obj, level))
    return list(rows.values())


def _counts(db, model, column, ids, *, distinct=None, answered=False):
    if not ids:
        return {}
    stmt = select(column, func.count(func.distinct(distinct)) if distinct is not None else func.count(model.id)).where(column.in_(ids))
    if answered:
        stmt = stmt.where(model.answered_at.is_not(None))
    return dict(db.execute(stmt.group_by(column)).all())


def collect(db, user, modules, *, state='active', scope='all', admin_all=False):
    rows = []
    families = []
    if 'polls' in modules:
        families.extend((
            ('poll', _visible(db, Poll, user, sh.shared_with(db, 'poll', user), admin_all)),
            ('vote', _visible(db, Vote, user, sh.shared_with(db, 'vote', user), admin_all)),
        ))
        if user.can('votes'):
            families.append(('live', _visible(db, LivePoll, user, [], admin_all)))
    for kind, objects in families:
        objects = [(obj, level) for obj, level in objects
                   if (scope != 'own' or obj.owner_id == user.id)
                   and (scope != 'shared' or obj.owner_id != user.id)
                   and (not getattr(obj, 'deleted_at', None))
                   and bool(obj.archived_at) == (state == 'archive')]
        ids = [obj.id for obj, _ in objects]
        counts = ({'live': lambda: _counts(db, LiveAnswer, LiveAnswer.poll_id, ids, distinct=LiveAnswer.device),
                   'poll': lambda: _counts(db, PollParticipant, PollParticipant.poll_id, ids, answered=True),
                   'vote': lambda: _counts(db, VoteBallot, VoteBallot.vote_id, ids)}[kind])()
        for obj, level in objects:
            base = {'live': '/votes/live/', 'poll': '/polls/', 'vote': '/votes/'}[kind] + str(obj.id)
            if kind == 'live':
                opened = obj.status == 'open'
                status = 'Entwurf' if obj.status == 'draft' else lv.STATUSES[obj.status][0].capitalize()
                results, edit = base + '?tab=results', base + '?tab=build'
                question_count = len(obj.questions)
            elif kind == 'poll':
                opened = pl.is_open(obj)
                status = 'Termin festgelegt' if obj.final_option_id else 'Offen' if opened else 'Entwurf' if not obj.published_at else 'Beendet'
                results, edit = base + '?tab=results', base + '/edit'
                question_count = len(obj.options)
            else:
                opened = vt.is_open(obj)
                status = 'Angehalten' if obj.status == 'draft' and obj.opened_at else vt.STATUSES[obj.status][0].capitalize()
                results, edit = base + '?tab=results', base + '/edit'
                question_count = len(obj.questions)
            archived = bool(obj.archived_at)
            draft = status == 'Entwurf'
            rows.append(dict(id=obj.id, kind=kind, title=obj.title, description=obj.description,
                             owner=obj.owner.name if obj.owner else 'Ohne Zuordnung', shared=obj.owner_id != user.id,
                             level=level, updated=obj.updated_at, status='Archiviert' if archived else status,
                             tone='neutral' if archived or draft else 'success' if opened else 'info',
                             count=counts.get(obj.id, 0), unit='Teilnehmende' if kind == 'live' else 'Stimmzettel' if kind == 'vote' else 'Antworten',
                             question_count=question_count, question_unit='Terminvorschläge' if kind == 'poll' else 'Fragen',
                             href=edit if draft and level >= 3 and not archived else results,
                             results=results, edit=edit if level >= 3 and not archived else '',
                             present=base + '/praesentation' if kind == 'live' and not archived else '',
                             share=(base + '?tab=share' if kind == 'live' else base + '?tab=share#teilen' if kind == 'poll' else base + '?tab=share#zugang') if level >= 2 and not archived else ''))
    return sorted(rows, key=lambda row: (row['updated'], row['kind'], row['id']), reverse=True)
