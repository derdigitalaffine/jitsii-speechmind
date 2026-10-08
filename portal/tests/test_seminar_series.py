import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app import seminars as sm, seminar_series as series, seminar_learning as learning
from app.db import SeminarSession, SeminarSubscription, SeminarEnrollment, SeminarMaterial, SeminarCertificate, SeminarNoticeDelivery, utcnow
from conftest import login, csrf_of, client
from test_seminars import people, make, rec


def test_subscription_consent_separate_booking_and_unsubscribe(db,people):
    row,t=make(db,people)
    sub=series.subscribe(db,row,None,'Gast','subscriber@example.org');db.commit()
    assert not sub.active and not sub.confirmed_at
    c=client();path=series.subscription_path(sub);page=c.get(path);assert page.status_code==200
    assert c.post(path,data={'csrf':csrf_of(page.text),'action':'book','sessions':[t.id]}).status_code==403
    assert c.post(path,data={'csrf':csrf_of(page.text),'action':'confirm'}).status_code==303
    assert not list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id)))
    assert c.post(path,data={'csrf':csrf_of(c.get(path).text),'action':'book','sessions':[t.id]}).status_code==303
    e=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id));assert e.status=='confirmed'
    assert c.post(path,data={'csrf':csrf_of(c.get(path).text),'action':'unsubscribe'}).status_code==303
    db.expire_all();assert not sub.active and e.status=='confirmed'
    assert c.get(path).status_code==200


def test_term_teacher_scope_guards_exports_materials_attendance(db,people):
    row,t=make(db,people);t.lecturers_json=json.dumps([people[2].id]);db.commit()
    t2=SeminarSession(seminar_id=row.id,starts_at=t.starts_at+timedelta(days=7),ends_at=t.ends_at+timedelta(days=7));db.add(t2);db.commit()
    a=rec(db,row,t,people[1]);sm.request_place(db,row,a)
    b=sm.new_enrollment(db,row,t2.id,'Secret Participant','secret@example.org',people[3]);sm.request_place(db,row,b);db.commit()
    teacher=login(people[2].email,'passwort-test-123')
    page=teacher.get(f'/seminare/{row.id}/participants');assert page.status_code==200 and 'Secret Participant' not in page.text
    assert teacher.get(f'/seminare/{row.id}/participants?tid={t2.id}').status_code==404
    assert teacher.get(f'/seminare/{row.id}/participants.csv?tid={t2.id}').status_code==404
    assert teacher.get(f'/seminare/{row.id}/terms/{t.id}').status_code==200
    assert teacher.get(f'/seminare/{row.id}/terms/{t2.id}').status_code==404
    token=csrf_of(page.text)
    assert teacher.post(f'/seminare/{row.id}/materials',data={'csrf':token,'action':'markdown','title':'Own','body':'Text','scope_id':t.id}).status_code==303
    assert teacher.post(f'/seminare/{row.id}/materials',data={'csrf':token,'action':'markdown','title':'Other','body':'Text','scope_id':t2.id}).status_code==404
    assert teacher.post(f'/seminare/{row.id}/materials',data={'csrf':token,'action':'markdown','title':'Global','body':'Text'}).status_code==404
    assert teacher.post(f'/seminare/{row.id}/attendance/{b.id}/{t2.id}',data={'csrf':token,'present':'1'}).status_code==404


def test_term_overrides_capacity_and_public_draft(db,people):
    row,t=make(db,people,capacity=5);t.overrides_json=json.dumps({'capacity':1,'manual_admission':True});db.commit()
    a=rec(db,row,t,people[1]);sm.request_place(db,row,a);assert a.status=='pending'
    a.status='confirmed';b=rec(db,row,t,people[2]);assert not sm.seats_available(db,row,b)
    draft=SeminarSession(seminar_id=row.id,title='Not Published',published=False,starts_at=t.starts_at,ends_at=t.ends_at);db.add(draft);db.commit()
    html=client().get(f'/seminare/{row.id}').text;assert 'Not Published' not in html
    assert draft not in sm.sessions(db,row)


def test_digest_idempotency_and_new_subscribers_not_old_notices(db,people,monkeypatch):
    row,t=make(db,people);sub=series.subscribe(db,row,people[1],'','');db.commit()
    series.announce(db,row,'new_terms','Neuer Termin');db.commit()
    series.tick(db,row);db.commit();assert not list(db.scalars(select(SeminarNoticeDelivery)))
    real=utcnow();monkeypatch.setattr(series,'utcnow',lambda:real+timedelta(days=1))
    series.tick(db,row);db.commit();assert len(list(db.scalars(select(SeminarNoticeDelivery))))==1
    series.tick(db,row);db.commit();assert len(list(db.scalars(select(SeminarNoticeDelivery))))==1


def test_term_and_series_certificates_keep_separate_snapshots(db,people,monkeypatch):
    row,t=make(db,people,certificates=True);row.certificate_scope='both'
    t2=SeminarSession(seminar_id=row.id,starts_at=t.starts_at+timedelta(days=7),ends_at=t.ends_at+timedelta(days=7));db.add(t2);db.commit()
    a=rec(db,row,t,people[1]);b=rec(db,row,t2,people[1]);sm.request_place(db,row,a);sm.request_place(db,row,b);db.commit()
    now=t2.ends_at+timedelta(hours=1);monkeypatch.setattr(learning,'utcnow',lambda:now)
    learning.mark_attendance(db,row,a,t,people[0],True);learning.mark_attendance(db,row,b,t2,people[0],True);db.commit()
    c1=learning.issue_certificate(db,row,a,people[0],t.id);c2=learning.issue_certificate(db,row,b,people[0],t2.id);cs=learning.issue_certificate(db,row,b,people[0],0);db.commit()
    assert len({c1.id,c2.id,cs.id})==3 and cs.enrollment_id==min(a.id,b.id)
    assert json.loads(cs.snapshot_json)['minutes']==240
    with pytest.raises(HTTPException):learning.mark_attendance(db,row,b,t2,people[0],False)
    before=c1.snapshot_json;row.title='Changed';db.commit();assert c1.snapshot_json==before
    c=login(people[1].email,'passwort-test-123');assert c.get(sm.personal_path(b)+f'/certificate.pdf?cid={c1.id}').status_code==200


def test_optional_participant_names_never_exposes_contacts(db,people):
    row,t=make(db,people);a=rec(db,row,t,people[1]);b=rec(db,row,t,people[2]);sm.request_place(db,row,a);sm.request_place(db,row,b);db.commit()
    c=login(people[1].email,'passwort-test-123');path=sm.personal_path(a)+f'/participants/{t.id}'
    assert c.get(path).status_code==404
    t.participants_visible=True;db.commit();page=c.get(path)
    assert page.status_code==200 and people[2].name in page.text and people[2].email not in page.text


def test_historical_bookings_and_settings_templates(db,people):
    row,t=make(db,people);a=rec(db,row,t,people[1]);a.status='cancelled';db.commit()
    c=login(people[1].email,'passwort-test-123');assert row.title in c.get('/seminare?tab=mine&period=past').text
    assert row.title not in c.get('/seminare?tab=mine&period=upcoming').text
    planner=login(people[0].email,'passwort-test-123');assert planner.get(f'/seminare/{row.id}/edit').status_code==200
    assert planner.get(f'/seminare/{row.id}/terms/{t.id}').status_code==200
    assert planner.get(f'/seminare/{row.id}/materials').status_code==200
