"""Reversible removal of unused drafts; published form evidence is retained."""
import json
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from .db import (Form, FormInvite, FormResponse, Seminar, SeminarActivity,
                 Circulation, CirculationBundle, CirculationVersion, TrashItem, utcnow)


def can_manage(form, user):
    # Sharing the editor does not transfer the owner's deletion rights.
    return bool(user.is_admin or form.owner_id == user.id)


def _reference(value, form_id):
    if isinstance(value, dict):
        if value.get('kind') == 'form' and str(value.get('id')) == str(form_id):
            return True
        return any(_reference(v, form_id) for v in value.values())
    return isinstance(value, list) and any(_reference(v, form_id) for v in value)


def used(db, form):
    """Check actual relations, not just cached response counts."""
    for model, condition in ((FormResponse, FormResponse.form_id == form.id),
                             (FormInvite, FormInvite.form_id == form.id),
                             (Seminar, Seminar.form_id == form.id),
                             (SeminarActivity, (SeminarActivity.kind == 'form') & (SeminarActivity.object_id == form.id))):
        if db.scalar(select(model.id).where(condition).limit(1)) is not None:
            return True
    for model, column in ((Circulation, Circulation.draft_json),
                          (CirculationBundle, CirculationBundle.draft_json),
                          (CirculationVersion, CirculationVersion.content_json)):
        for raw in db.scalars(select(column)):
            try:
                if _reference(json.loads(raw or '{}'), form.id):
                    return True
            except (ValueError, TypeError):
                continue
    # Recoverable collections/circulations may still refer to this draft.
    for raw in db.scalars(select(TrashItem.data_json)):
        try:
            for row in json.loads(raw or '{}').get('rows', []):
                data = row.get('data', {})
                for key in ('draft_json', 'content_json', 'item_json'):
                    if key in data and _reference(json.loads(data[key] or '{}'), form.id):
                        return True
        except (ValueError, TypeError, AttributeError):
            # Ambiguous snapshots should not cause loss of a recoverable reference.
            return True
    return False


def must_archive(db, form):
    # active also protects forms created by older integrations without a marker.
    return bool(form.published_at or form.archived_at or form.active or form.public_token or used(db, form))


def remove(db, form, user):
    if not can_manage(form, user):
        raise HTTPException(403, 'Nur die Eigentümerin oder der Eigentümer und Administratoren dürfen Formulare entfernen.')
    if form.deleted_at:
        return 'trash'
    protected = must_archive(db, form)
    form.active = False
    if protected:
        form.published_at = form.published_at or utcnow()
        form.archived_at = form.archived_at or utcnow()
        return 'archive'
    form.deleted_at = utcnow()
    return 'trash'


def restore(db, form, user):
    if not can_manage(form, user):
        raise HTTPException(403, 'Keine Berechtigung zum Wiederherstellen.')
    if form.deleted_at and form.deleted_at <= utcnow() - timedelta(days=30):
        raise HTTPException(410, 'Die Wiederherstellungsfrist von 30 Tagen ist abgelaufen.')
    form.deleted_at = None
    form.archived_at = None
    form.active = False  # Restore does not silently re-open links or applications.


def purge(db, now=None):
    """Worker hook; late references protect drafts even after they were trashed."""
    now = now or utcnow()
    removed = []
    for form in db.scalars(select(Form).where(Form.deleted_at <= now - timedelta(days=30))):
        if form.published_at or form.public_token or used(db, form):
            form.deleted_at = None
            form.archived_at = form.archived_at or now
            form.active = False
            continue
        removed.append(form.id)
        db.delete(form)
    db.flush()
    # Caller commits the database transaction before deleting associated storage.
    return removed


def purge_files(ids):
    from . import forms
    for form_id in ids:
        forms.delete_files(form_id)
