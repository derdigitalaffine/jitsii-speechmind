import json
import secrets
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import select,delete
from app import seminars as sm
from app.db import (Seminar,SeminarSession,SeminarEnrollment,SeminarEvent,SeminarDelivery,User,SessionLocal,
                    SeminarAttendance,SeminarMaterial,SeminarActivity,SeminarCertificate,Notification,utcnow,get_settings,set_setting)
from conftest import login,client,csrf_of,settings

@pytest.fixture
def people(db):
    old=get_settings(db);settings(module_seminars='1',smtp_host='localhost',mail_from='portal@example.org')
    from app.main import hash_password
    users=[]
    for name in ('planner','member','teacher','other'):
        u=User(name=name,email=f'sem-{name}-{secrets.token_hex(4)}@example.org',password_hash=hash_password('passwort-test-123'),permissions='seminars' if name=='planner' else '')
        db.add(u);users.append(u)
    db.commit();yield users
    db.rollback()
    for row in db.scalars(select(Seminar).where(Seminar.owner_id.in_([u.id for u in users]))):db.delete(row)
    db.flush()
    db.execute(delete(Notification).where(Notification.kind=='seminar'))
    for u in users:db.delete(u)
    for key in ('module_seminars','smtp_host','mail_from'):set_setting(db,key,old.get(key,''))
    db.commit()


def make(db,people,**kw):
    row=Seminar(owner_id=people[0].id,title='Testseminar',status='published',channels='internal,guest,public',**kw);db.add(row);db.flush()
    term=SeminarSession(seminar_id=row.id,starts_at=datetime(2027,3,15,9),ends_at=datetime(2027,3,15,11),location='Rathaus');db.add(term);db.commit();return row,term


def rec(db,row,term,u,**kw):return sm.new_enrollment(db,row,term.id,u.name,u.email,u,**kw)


def test_recurrence_local_time_monthly_and_dst(monkeypatch):
    from zoneinfo import ZoneInfo
    import app.db as dbmod
    monkeypatch.setattr(sm,"LOCAL_TZ",ZoneInfo("Europe/Berlin"))
    monkeypatch.setattr(dbmod,"LOCAL_TZ",ZoneInfo("Europe/Berlin"))
    start=sm.parse_time('2027-03-22T10:00');end=sm.parse_time('2027-03-22T12:00')
    weeks=sm.recurrence(start,end,'fortnightly',3)
    assert [sm.local_input(x[0]) for x in weeks]==['2027-03-22T10:00','2027-04-05T10:00','2027-04-19T10:00']
    assert (weeks[1][0]-weeks[0][0]).total_seconds()==(14*24-1)*3600
    months=sm.recurrence(sm.parse_time('2027-01-01T10:00'),sm.parse_time('2027-01-01T12:00'),'monthly_weekday',3,2,0)
    assert [sm.local_input(x[0])[:10] for x in months]==['2027-01-11','2027-02-08','2027-03-08']
    last=sm.recurrence(sm.parse_time('2027-01-01T10:00'),sm.parse_time('2027-01-01T12:00'),'monthly_weekday',2,-1,4)
    assert sm.local_input(last[0][0])[:10]=='2027-01-29'
    with pytest.raises(HTTPException):sm.parse_time('2027-03-28T02:30')


def test_seats_waitlist_offer_accept_and_replay(db,people):
    row,t=make(db,people,capacity=1);a=rec(db,row,t,people[1]);b=rec(db,row,t,people[2]);sm.request_place(db,row,a);sm.request_place(db,row,b);db.commit()
    assert a.status=='confirmed' and b.status=='waitlist'
    sm.lock(db,row);sm.cancel(db,row,a,True);db.commit();assert b.status=='offered'
    sm.lock(db,row);sm.accept_offer(db,row,b);db.commit();assert b.status=='confirmed'
    with pytest.raises(HTTPException):sm.accept_offer(db,row,b)
    assert 'BEGIN:VEVENT' in sm.calendar_text(db,row,b)


def test_parallel_registration_never_overbooks(db,people):
    row,t=make(db,people,capacity=1);a=rec(db,row,t,people[1]);b=rec(db,row,t,people[2]);db.commit();sid=row.id;ids=[a.id,b.id]
    def book(eid):
        with SessionLocal() as connection:
            r=connection.get(Seminar,sid);sm.lock(connection,r);e=connection.get(SeminarEnrollment,eid);sm.request_place(connection,r,e);connection.commit();return e.status
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(book,ids))
    assert sorted(statuses)==['confirmed','waitlist']


def test_series_capacity_and_duplicate_scope(db,people):
    row,t=make(db,people,booking_mode='series',capacity=1)
    t2=SeminarSession(seminar_id=row.id,starts_at=t.starts_at+timedelta(days=7),ends_at=t.ends_at+timedelta(days=7));db.add(t2);db.commit()
    a=sm.new_enrollment(db,row,0,people[1].name,people[1].email,people[1]);sm.request_place(db,row,a)
    b=rec(db,row,t2,people[2]);sm.request_place(db,row,b);assert b.status=='waitlist'
    duplicate=rec(db,row,t,people[1])
    with pytest.raises(HTTPException):sm.request_place(db,row,duplicate)
    assert sm.calendar_text(db,row,a).count('BEGIN:VEVENT')==2


def test_public_email_consent_and_personal_privacy(db,people):
    row,t=make(db,people);c=client();page=c.get(f'/seminare/{row.id}');assert page.status_code==200
    r=c.post(f'/seminare/{row.id}/register',data={'csrf':csrf_of(page.text),'sessions':[t.id],'name':'Gast','email':'gast@example.org'});assert r.status_code==200 and 'Postfach' in r.text
    e=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id));assert e.status=='unverified' and not e.verified_at
    p=c.get(sm.personal_path(e));assert 'E-Mail bestätigen' in p.text and people[1].email not in p.text
    assert c.post(sm.personal_path(e)+'/action',data={'csrf':csrf_of(p.text),'action':'register'}).status_code==303
    db.refresh(e);assert e.status=='confirmed' and e.verified_at
    assert c.get(sm.personal_path(e)+'/calendar.ics').status_code==200
    other=login(people[3].email,'passwort-test-123');assert other.get(f'/seminare/{row.id}/participants').status_code==404


def test_internal_access_csrf_and_manual_admission(db,people):
    row,t=make(db,people,manual_admission=True);row.channels='internal';db.commit()
    assert client().get(f'/seminare/{row.id}').status_code==404
    c=login(people[1].email,'passwort-test-123');p=c.get(f'/seminare/{row.id}')
    assert c.post(f'/seminare/{row.id}/register',data={'sessions':[t.id]}).status_code==400
    assert c.post(f'/seminare/{row.id}/register',data={'csrf':csrf_of(p.text),'sessions':[t.id],'email':'spoof@example.org'}).status_code==303
    e=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id));assert e.email==people[1].email and e.status=='pending'
    owner=login(people[0].email,'passwort-test-123');p=owner.get(f'/seminare/{row.id}/participants');assert p.status_code==200
    assert owner.post(f'/seminare/{row.id}/participants/{e.id}/decision',data={'csrf':csrf_of(p.text),'action':'approve'}).status_code==303
    db.refresh(e);assert e.status=='confirmed'
    assert client().get(sm.personal_path(e)).status_code==403


def test_editor_and_teacher_boundaries(db,people):
    row,t=make(db,people,advanced=True,lecturers_json=json.dumps([people[2].id]));owner=login(people[0].email,'passwort-test-123');p=owner.get(f'/seminare/{row.id}/edit');assert p.status_code==200
    assert 'Alle 14 Tage' in p.text and 'Woche im Monat' in p.text
    teacher=login(people[2].email,'passwort-test-123');assert teacher.get(f'/seminare/{row.id}/participants').status_code==200
    assert teacher.get(f'/seminare/{row.id}/edit').status_code==404
    assert 'Seminare &amp; Lehrgänge' in owner.get('/seminare').text


def test_reminders_idempotent_and_expired_offers(db,people):
    row,t=make(db,people,capacity=1);t.starts_at=utcnow()+timedelta(hours=8);t.ends_at=t.starts_at+timedelta(hours=2);a=rec(db,row,t,people[1]);sm.request_place(db,row,a);db.commit()
    assert sm.tick()>=1;count=db.scalar(select(__import__('sqlalchemy').func.count(SeminarDelivery.id)))
    sm.tick();assert db.scalar(select(__import__('sqlalchemy').func.count(SeminarDelivery.id)))==count


def test_editor_save_publication_and_stale_revision(db,people):
    row,t=make(db,people);row.status='draft';db.commit()
    c=login(people[0].email,'passwort-test-123');p=c.get(f'/seminare/{row.id}/edit');token=csrf_of(p.text)
    data={'csrf':token,'revision':row.revision,'title':'Neuer Titel','channels':['internal','public'],'booking_mode':'individual','capacity':'2','save_action':'publish','reminder_days':'7,1','waitlist':'1'}
    response=c.post(f'/seminare/{row.id}/edit',data=data,headers={'Accept':'application/json'});assert response.status_code==200
    db.refresh(row);assert row.title=='Neuer Titel' and row.status=='published' and response.json()['redirect']==f'/seminare/{row.id}'
    assert c.post(f'/seminare/{row.id}/edit',data=data).status_code==409
    # Seat allocation preserves the editor's content revision.
    before=row.revision;e=rec(db,row,t,people[1]);sm.lock(db,row);sm.request_place(db,row,e);db.commit();assert row.revision==before


def test_session_post_recurrence_then_cancelled_calendar(db,people):
    row,t=make(db,people);c=login(people[0].email,'passwort-test-123');p=c.get(f'/seminare/{row.id}/edit');token=csrf_of(p.text)
    data={'csrf':token,'starts_at':'2027-04-01T10:00','ends_at':'2027-04-01T12:00','repeat':'fortnightly','count':'3','location':'Externer Ort','online_url':'https://meet.example.org/seminar'}
    assert c.post(f'/seminare/{row.id}/sessions',data=data).status_code==303
    db.expire_all();assert len(sm.sessions(db,row))==4
    e=rec(db,row,t,people[1]);sm.request_place(db,row,e);db.commit()
    assert c.post(f'/seminare/{row.id}/sessions/{t.id}',data={'csrf':token,'revision':t.revision,'action':'cancel','reason':'Dozent verhindert'}).status_code==303
    db.expire_all();assert 'STATUS:CANCELLED' in sm.calendar_text(db,row,e)
