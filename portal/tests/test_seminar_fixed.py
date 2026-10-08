import json
import secrets
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import seminar_fixed as fixed, seminars as sm
from app.db import Group, SeminarEnrollment, SeminarSession
from test_seminars import people, make


@pytest.fixture
def audience(db, people):
    first = Group(name='fixed-a-' + secrets.token_hex(5), members=[people[1], people[2]])
    second = Group(name='fixed-b-' + secrets.token_hex(5), members=[people[1], people[3]])
    db.add_all([first, second]); db.commit()
    yield first, second
    db.rollback()
    db.delete(first); db.delete(second); db.commit()


def enrollments(db, row):
    return list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id == row.id)
                           .order_by(SeminarEnrollment.id)))


def test_group_validation_is_atomic_and_drafts_never_invite(db, people, audience, monkeypatch):
    row, term = make(db, people)
    fixed.configure(db, row, [audience[0].id, audience[0].id], 'on')
    assert json.loads(row.fixed_groups_json) == [audience[0].id] and row.fixed_confirmation
    before = row.fixed_groups_json
    with pytest.raises(HTTPException):
        fixed.configure(db, row, [999999999], False)
    assert row.fixed_groups_json == before and row.fixed_confirmation
    monkeypatch.setattr(sm, 'mail', lambda *args, **kw: pytest.fail('Draft must not notify'))
    row.status = 'draft'
    assert fixed.enroll_published(db, row, [term])['created'] == 0
    row.status = 'published'; term.published = False
    assert fixed.enroll_published(db, row, [term])['created'] == 0
    assert not enrollments(db, row)


def test_fixed_group_deduplicates_active_members_and_keeps_cancellations(db, people, audience, monkeypatch):
    row, term = make(db, people)
    fixed.configure(db, row, [g.id for g in audience], True)
    people[3].active = False
    notices = []
    monkeypatch.setattr(sm, 'mail', lambda *args, **kw: notices.append(args[2].id))
    counts = fixed.enroll_published(db, row, [term, term], people[0])
    records = enrollments(db, row)
    assert counts['created'] == counts['invited'] == 2
    assert len(notices) == 2 and {r.user_id for r in records} == {people[1].id, people[2].id}
    records[0].status = 'cancelled'
    records[1].status = 'rejected'
    people[1].email = 'changed-fixed@example.org'
    counts = fixed.enroll_published(db, row, [term])
    assert counts['created'] == 0 and counts['skipped'] == 2
    assert len(notices) == 2 and {r.status for r in enrollments(db, row)} == {'cancelled', 'rejected'}


def test_fixed_participants_capacity_admission_and_term_scope(db, people, audience, monkeypatch):
    row, term = make(db, people, capacity=1)
    fixed.configure(db, row, [audience[0].id], False)
    second = SeminarSession(seminar_id=row.id, starts_at=term.starts_at+timedelta(days=14),
                            ends_at=term.ends_at+timedelta(days=14),
                            overrides_json=json.dumps({'manual_admission': True}))
    db.add(second); db.flush()
    monkeypatch.setattr(sm, 'mail', lambda *args, **kw: True)
    counts = fixed.enroll_published(db, row, [term, second])
    assert counts['created'] == 4
    assert counts['confirmed'] == 1 and counts['waitlist'] == 1 and counts['pending'] == 2
    assert all(r.scope_id in {term.id, second.id} for r in enrollments(db, row))


def test_full_fixed_group_without_waitlist_keeps_invitation(db, people, audience, monkeypatch):
    row, term = make(db, people, capacity=1, waitlist=False)
    fixed.configure(db, row, [audience[0].id], False)
    monkeypatch.setattr(sm, 'mail', lambda *args, **kw: True)
    counts = fixed.enroll_published(db, row, [term])
    assert counts['created'] == 2 and counts['confirmed'] == 1 and counts['invited'] == 1
    invited = next(r for r in enrollments(db, row) if r.status == 'invited')
    assert 'Alle Plätze' in invited.reason


def test_series_enrollment_is_not_recreated_for_fixed_term(db, people, audience, monkeypatch):
    row, term = make(db, people)
    fixed.configure(db, row, [audience[0].id], True)
    old = sm.new_enrollment(db, row, 0, people[1].name, people[1].email, people[1], status='cancelled')
    monkeypatch.setattr(sm, 'mail', lambda *args, **kw: True)
    counts = fixed.enroll_published(db, row, [term])
    assert counts['created'] == 1 and counts['skipped'] == 1
    assert old.status == 'cancelled'
