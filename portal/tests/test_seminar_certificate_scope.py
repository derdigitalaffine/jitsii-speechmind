"""Attendance protection applies only to terms actually covered by a certificate."""
import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from app import seminar_learning as learning, seminars as sm
from app.db import SeminarSession
from test_seminars import people, make, rec


def setup_two_terms(db,people,monkeypatch,scope):
    row,t=make(db,people,certificates=True);row.certificate_scope=scope
    second=SeminarSession(seminar_id=row.id,starts_at=t.starts_at+timedelta(days=14),ends_at=t.ends_at+timedelta(days=14))
    db.add(second);db.commit()
    first_rec=rec(db,row,t,people[1],status='confirmed');second_rec=rec(db,row,second,people[1],status='confirmed')
    monkeypatch.setattr(learning,'utcnow',lambda:second.ends_at+timedelta(hours=1))
    learning.mark_attendance(db,row,first_rec,t,people[0],True)
    learning.mark_attendance(db,row,second_rec,second,people[0],True)
    db.commit()
    return row,t,second,first_rec,second_rec


def test_individual_enrollment_certificate_does_not_lock_other_booking(db,people,monkeypatch):
    row,t,second,a,b=setup_two_terms(db,people,monkeypatch,'enrollment')
    cert=learning.issue_certificate(db,row,a,people[0]);db.flush()
    assert json.loads(cert.snapshot_json)['term_ids']==[t.id]
    learning.mark_attendance(db,row,b,second,people[0],False)
    with pytest.raises(HTTPException):learning.mark_attendance(db,row,a,t,people[0],False)
    # Equivalent certificates created before scope metadata was introduced.
    snapshot=json.loads(cert.snapshot_json);snapshot.pop('term_ids');snapshot.pop('scope_kind');cert.snapshot_json=json.dumps(snapshot)
    learning.mark_attendance(db,row,b,second,people[0],False)
    with pytest.raises(HTTPException):learning.mark_attendance(db,row,a,t,people[0],False)


def test_series_certificate_keeps_covered_terms_locked_after_setting_changes(db,people,monkeypatch):
    row,t,second,a,b=setup_two_terms(db,people,monkeypatch,'series')
    cert=learning.issue_certificate(db,row,b,people[0]);db.flush()
    snapshot=json.loads(cert.snapshot_json)
    assert snapshot['scope_kind']=='series' and set(snapshot['term_ids'])=={t.id,second.id}
    row.certificate_scope='enrollment'
    with pytest.raises(HTTPException):learning.mark_attendance(db,row,b,second,people[0],False)
    snapshot.pop('term_ids');snapshot.pop('scope_kind');cert.snapshot_json=json.dumps(snapshot)
    with pytest.raises(HTTPException):learning.mark_attendance(db,row,b,second,people[0],False)
    cert.revoked_at=second.ends_at+timedelta(hours=1)
    learning.mark_attendance(db,row,b,second,people[0],False)
