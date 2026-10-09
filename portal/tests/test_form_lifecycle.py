"""Owners can remove drafts without destroying published submission evidence."""
import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from app import form_lifecycle as life, forms
from app.db import (SessionLocal, User, Form, FormShare, FormResponse, FormInvite,
                    CirculationBundle, utcnow)
from app.security import hash_password
from conftest import csrf_of, login


@pytest.fixture
def fixture():
    with SessionLocal() as db:
        owner = User(name='Lifecycle owner', email='form-life-owner@example.org', password_hash=hash_password('owner-password-123'), permissions='forms', active=True, must_change_password=False)
        editor = User(name='Lifecycle editor', email='form-life-editor@example.org', password_hash=hash_password('editor-password-123'), permissions='', active=True, must_change_password=False)
        db.add_all([owner, editor]); db.flush()
        form = Form(title='Lifecycle draft', owner_id=owner.id, active=False, public_token='lifecycle-draft-secret')
        db.add(form); db.flush(); db.add(FormShare(form_id=form.id, user_id=editor.id, level=forms.EDIT)); db.commit()
        ids = owner.id, editor.id, form.id
    yield ids
    with SessionLocal() as db:
        for model, id in ((Form, ids[2]), (User, ids[1]), (User, ids[0])):
            row = db.get(model, id)
            if row: db.delete(row)
        db.commit()


def test_shared_editor_cannot_delete_or_restore(fixture):
    owner, editor, fid = fixture
    c = login('form-life-editor@example.org', 'editor-password-123')
    token = csrf_of(c.get(f'/forms/{fid}').text)
    for action in ('delete', 'restore', 'responses/delete-all'):
        assert c.post(f'/forms/{fid}/{action}', data={'csrf': token}).status_code == 403
    with SessionLocal() as db:
        assert db.get(Form, fid).deleted_at is None


def test_draft_trash_restore_keeps_acl_and_blocks_access(fixture):
    owner, editor, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None; db.commit()
    c = login('form-life-owner@example.org', 'owner-password-123')
    token = csrf_of(c.get('/forms').text)
    assert c.post(f'/forms/{fid}/delete', data={'csrf': token}).status_code == 303
    assert c.get(f'/forms/{fid}').status_code == 404
    assert 'Lifecycle draft' not in c.get('/forms').text
    assert 'Lifecycle draft' in c.get('/forms?state=trash').text
    assert c.post(f'/forms/{fid}/restore', data={'csrf': token}).status_code == 303
    with SessionLocal() as db:
        form = db.get(Form, fid)
        assert not form.deleted_at and not form.active
        assert forms.access_level(db, form, db.get(User, editor)) == forms.EDIT


@pytest.mark.parametrize('reason', ['published', 'response', 'invite', 'collection'])
def test_used_forms_archive_with_all_evidence_intact(fixture, reason):
    owner, _, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None
        bundle = None
        if reason == 'published': form.published_at = utcnow()
        if reason == 'response': db.add(FormResponse(form_id=fid, answers_json='{"answer":"retained"}'))
        if reason == 'invite': db.add(FormInvite(form_id=fid, email='guest@example.org', token='retained-invite-secret'))
        if reason == 'collection':
            bundle = CirculationBundle(owner_id=owner, draft_json=json.dumps({'items': [{'kind': 'form', 'id': fid}]})); db.add(bundle)
        db.flush()
        assert life.remove(db, form, db.get(User, owner)) == 'archive'
        db.commit()
        assert form.archived_at and not form.deleted_at and not forms.is_open(form)
        if reason == 'response': assert form.responses[0].answers_json == '{"answer":"retained"}'
        if reason == 'invite': assert form.invites[0].token == 'retained-invite-secret'
        if bundle: db.delete(bundle); db.commit()
    c = login('form-life-owner@example.org', 'owner-password-123')
    assert c.get(f'/forms/{fid}/results').status_code == 200
    assert c.get(f'/forms/{fid}').status_code == 409
    assert 'Lifecycle draft' in c.get('/forms?state=archive').text


def test_purge_protects_late_use_and_expired_restore(fixture):
    owner, _, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None
        form.deleted_at = utcnow() - timedelta(days=31)
        with pytest.raises(HTTPException) as exc: life.restore(db, form, db.get(User, owner))
        assert exc.value.status_code == 410
        db.add(FormResponse(form_id=fid, answers_json='{"late":"keep"}')); db.flush()
        assert life.purge(db) == []
        assert form.archived_at and form.deleted_at is None and not form.active
        db.commit()


def test_unused_expired_draft_is_purged(fixture):
    owner, _, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None
        form.deleted_at = utcnow() - timedelta(days=31); db.flush()
        assert life.purge(db) == [fid]
        db.commit()
        assert db.get(Form, fid) is None


def test_archive_closes_public_link_and_never_deletes_uploads(fixture, monkeypatch):
    owner, _, fid = fixture
    def prohibited(*args):
        raise AssertionError('Removing a form must retain response uploads')
    monkeypatch.setattr(forms, 'delete_files', prohibited)
    c = login('form-life-owner@example.org', 'owner-password-123')
    token = csrf_of(c.get('/forms').text)
    assert c.post(f'/forms/{fid}/delete', data={'csrf': token}).status_code == 303
    page = c.get('/f/lifecycle-draft-secret')
    assert page.status_code == 200 and 'geschlossen' in page.text.lower()
    assert c.get(f'/forms/{fid}/results').status_code == 200


def test_closed_published_form_keeps_publication_marker(fixture):
    owner, _, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None; db.commit()
    c = login('form-life-owner@example.org', 'owner-password-123')
    token = csrf_of(c.get(f'/forms/{fid}/settings').text)
    assert c.post(f'/forms/{fid}/settings', data={'csrf': token, 'active': '1'}).status_code == 303
    assert c.post(f'/forms/{fid}/settings', data={'csrf': token}).status_code == 303
    assert c.post(f'/forms/{fid}/delete', data={'csrf': token}).status_code == 303
    with SessionLocal() as db:
        form = db.get(Form, fid)
        assert form.published_at and form.archived_at and not form.deleted_at


def test_recoverable_collection_reference_protects_form(fixture):
    from app.db import TrashItem
    owner, _, fid = fixture
    with SessionLocal() as db:
        form = db.get(Form, fid); form.public_token = None
        snapshot = TrashItem(kind='circulation_bundle', table_name='circulation_bundles', row_id=999999,
            expires_at=utcnow()+timedelta(days=30), data_json=json.dumps({'rows': [
                {'table': 'circulation_bundles', 'data': {'draft_json': json.dumps({'items': [{'kind': 'form', 'id': fid}]})}}
            ]}))
        db.add(snapshot); db.flush()
        assert life.remove(db, form, db.get(User, owner)) == 'archive'
        assert not form.deleted_at and form.archived_at
        db.delete(snapshot); db.commit()
