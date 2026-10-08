"""Publish-time invitations for an explicitly selected fixed participant circle.

Group membership is resolved at publication, never while editing a draft. Existing
responses remain authoritative, including cancellations and rejected requests.
The caller owns the transaction and must already have checked planning rights.
"""
import json

from fastapi import HTTPException
from sqlalchemy import select

from . import seminars as sm
from .db import Group, GroupMember, SeminarEnrollment, User, utcnow


def configure(db, row, group_ids, confirmation=False):
    """Validate and store the fixed audience without enrolling or notifying anyone."""
    try:
        ids = sorted({int(value) for value in group_ids if str(value).strip()})
    except (TypeError, ValueError):
        raise HTTPException(422, 'Bitte gültige Teilnehmergruppen auswählen.')
    if len(ids) > 100 or any(value <= 0 for value in ids):
        raise HTTPException(422, 'Bitte höchstens 100 gültige Teilnehmergruppen auswählen.')
    existing = set(db.scalars(select(Group.id).where(Group.id.in_(ids)))) if ids else set()
    if existing != set(ids):
        raise HTTPException(422, 'Eine ausgewählte Teilnehmergruppe existiert nicht mehr.')
    row.fixed_groups_json = json.dumps(ids)
    row.fixed_confirmation = confirmation is True or str(confirmation).lower() in {'1', 'true', 'on'}
    return ids


def group_ids(row):
    try:
        values = json.loads(row.fixed_groups_json or '[]')
        if not isinstance(values, list):
            return []
        return sorted({int(value) for value in values if int(value) > 0})
    except (TypeError, ValueError):
        return []


def enroll_published(db, row, terms, user=None):
    """Create one enrollment per active group member and newly published term.

Returns counts for a clear publication result. Repeated calls are harmless.
Forms, manual admission, capacity and waiting lists use the regular registration
path. If registration is unavailable, a plain invitation lets the participant or
planner resolve it without failing publication for the entire group.
"""
    counts = {'created': 0, 'confirmed': 0, 'invited': 0, 'pending': 0,
              'form': 0, 'waitlist': 0, 'skipped': 0}
    ids = group_ids(row)
    if row.status != 'published' or not ids:
        return counts
    now = utcnow()
    selected = {term.id: term for term in terms if term.id and term.seminar_id == row.id
                and term.published and not term.cancelled and term.starts_at > now}
    if not selected:
        return counts
    db.flush()
    sm.lock(db, row)
    members = list(db.scalars(select(User).join(GroupMember, GroupMember.user_id == User.id)
                             .where(GroupMember.group_id.in_(ids), User.active.is_(True))
                             .distinct().order_by(User.id)))
    for term in sorted(selected.values(), key=lambda item: (item.starts_at, item.id)):
        for member in members:
            email = member.email.strip().lower()
            previous = db.scalar(select(SeminarEnrollment.id).where(
                SeminarEnrollment.seminar_id == row.id,
                SeminarEnrollment.scope_id.in_([0, term.id]),
                (SeminarEnrollment.user_id == member.id) | (SeminarEnrollment.email == email)))
            if previous:
                counts['skipped'] += 1
                continue
            rec = sm.new_enrollment(db, row, term.id, member.name, email, member)
            from . import seminar_hybrid
            seminar_hybrid.set_modes(db, row, rec, {})
            if not row.fixed_confirmation:
                try:
                    sm.request_place(db, row, rec)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    rec.status = 'invited'
                    rec.reason = 'Automatische Einplanung nicht möglich: ' + str(exc.detail)[:430]
            # request_place already notifies confirmed/pending/waitlist members.
            # Required forms and invitations need their own actionable message.
            if rec.status in {'invited', 'form'}:
                message = ('Bitte bestätigen Sie Ihre Teilnahme über Ihre persönliche Seminarseite.'
                           if rec.status == 'invited' else
                           'Bitte füllen Sie das Pflichtformular auf Ihrer persönlichen Seminarseite aus.')
                if rec.reason:
                    message += '\n' + rec.reason
                sm.mail(db, row, rec, 'Einladung zum Termin', message, key=f'fixed:{term.id}')
            counts['created'] += 1
            counts[rec.status] = counts.get(rec.status, 0) + 1
            db.flush()
    if counts['created']:
        sm.event(db, row, 'fixed_participants', user,
                 f"Fester Teilnehmerkreis: {counts['created']} Terminzuordnungen erstellt.")
    return counts
