"""Narrow capability links. No portal account or source-object authority is conferred."""
import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from . import tasks as ts
from .db import utcnow
from .task_models import Task, TaskExternal


def issue(db, user, row, *, days=14, comments=False):
    if not ts.may_edit(user, row):
        raise HTTPException(403)
    if not row.external_email:
        raise ts.Invalid('Diese Aufgabe ist keiner externen Person zugewiesen.')
    if not 1 <= days <= 90:
        raise ts.Invalid('Der Link muss nach 1 bis 90 Tagen ablaufen.')
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    link = db.get(TaskExternal, row.id)
    if not link:
        link = TaskExternal(task_id=row.id)
        db.add(link)
    link.token_hash, link.email = digest, row.external_email
    link.expires_at, link.revoked_at = utcnow() + timedelta(days=days), None
    link.comments_enabled = bool(comments)
    ts.audit(db, row, user, 'external_link', 'Persönlicher Aufgabenlink erstellt; bisherige Links sind ungültig.')
    return raw


def resolve(db, token):
    if len(token) > 100:
        raise HTTPException(404, 'Dieser Aufgabenlink ist ungültig oder abgelaufen.')
    digest = hashlib.sha256(token.encode()).hexdigest()
    link = db.scalar(select(TaskExternal).where(TaskExternal.token_hash == digest))
    row = db.get(Task, link.task_id) if link else None
    if not link or link.revoked_at or link.expires_at <= utcnow() or not row or row.archived_at or row.assignee_id is not None or row.external_email != link.email:
        raise HTTPException(404, 'Dieser Aufgabenlink ist ungültig, widerrufen oder abgelaufen. Bitte bitten Sie die beauftragende Person um einen neuen Link.')
    return row, link


def actor(row):
    return SimpleNamespace(id=None, name=f'{row.external_name} <{row.external_email}> (extern)', can=lambda perm: False)
