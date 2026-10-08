"""Independent seat pools, private rooms and per-term response changes."""
import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select, delete
from app import seminar_hybrid as hybrid, seminars as sm, seminar_series as series
from app.db import Meeting, SeminarSession, SeminarEnrollment, utcnow
from test_seminars import people, make, rec
from conftest import client, login, csrf_of


@pytest.fixture
def video_cleanup(db,people):
    yield
    db.rollback()
    for meeting in db.scalars(select(Meeting).where(Meeting.owner_id==people[0].id)):
        db.delete(meeting)
    db.commit()


def test_hybrid_seat_pools_and_switch_are_independent(db,people,monkeypatch):
    row,t=make(db,people,capacity=1)
    hybrid.configure_term(db,row,t,{'delivery_mode':'hybrid','online_capacity':1,'video_kind':'manual','online_url':'https://video.example.org/private'})
    a=rec(db,row,t,people[1]);b=rec(db,row,t,people[2]);c=rec(db,row,t,people[3])
    hybrid.set_modes(db,row,a,{'mode_'+str(t.id):'onsite'})
    hybrid.set_modes(db,row,b,{'mode_'+str(t.id):'online'})
    sm.request_place(db,row,a);sm.request_place(db,row,b);sm.request_place(db,row,c)
    assert (a.status,b.status,c.status)==('confirmed','confirmed','waitlist')
    old=a.modes_json
    with pytest.raises(HTTPException) as err:hybrid.switch(db,row,a,t,'online')
    assert err.value.status_code==409 and a.modes_json==old
    # Saving unchanged capacities at their current occupancy is valid.
    hybrid.configure_term(db,row,t,{'delivery_mode':'hybrid','online_capacity':1})
    sm.cancel(db,row,b,True)
    monkeypatch.setattr(sm,'mail',lambda *a,**kw:True)
    hybrid.switch(db,row,a,t,'online')
    assert hybrid.mode(a,t)=='online' and c.status=='offered'


def test_switch_cutoff_is_per_term_and_planner_can_override(db,people,monkeypatch):
    row,t=make(db,people,booking_mode='series')
    t.delivery_mode='hybrid';t.starts_at=utcnow()-timedelta(days=1);t.ends_at=t.starts_at+timedelta(hours=1)
    nextterm=SeminarSession(seminar_id=row.id,starts_at=utcnow()+timedelta(days=5),ends_at=utcnow()+timedelta(days=5,hours=1),delivery_mode='hybrid')
    db.add(nextterm);db.flush()
    a=sm.new_enrollment(db,row,0,people[1].name,people[1].email,people[1],status='confirmed')
    monkeypatch.setattr(sm,'mail',lambda *a,**kw:True)
    hybrid.switch(db,row,a,nextterm,'online')
    assert hybrid.mode(a,nextterm)=='online' and not hybrid.can_switch(db,row,t)
    nextterm.overrides_json=json.dumps({'registration_until':(utcnow()-timedelta(minutes=1)).isoformat()})
    with pytest.raises(HTTPException):hybrid.switch(db,row,a,nextterm,'onsite')
    hybrid.switch(db,row,a,nextterm,'onsite',staff=True)
    assert hybrid.mode(a,nextterm)=='onsite'


def test_private_manual_video_requires_confirmed_online_participant(db,people):
    row,t=make(db,people);t.delivery_mode='hybrid';t.online_url='https://video.example.org/secret-link';db.commit()
    a=rec(db,row,t,people[1],status='confirmed');b=rec(db,row,t,people[2],status='pending')
    hybrid.set_modes(db,row,b,{'mode_'+str(t.id):'online'});db.commit()
    assert 'secret-link' not in client().get(f'/seminare/{row.id}').text
    c=login(people[1].email,'passwort-test-123');url=sm.personal_path(a)+'/video/'+str(t.id)
    assert c.get(url).status_code==403
    hybrid.set_modes(db,row,a,{'mode_'+str(t.id):'online'});db.commit()
    response=c.get(url);assert response.status_code==303 and response.headers['location']==t.online_url
    assert 'secret-link' not in c.get(sm.personal_path(a)).text
    other=login(people[3].email,'passwort-test-123');assert other.get(url).status_code==403
    assert login(people[2].email,'passwort-test-123').get(sm.personal_path(b)+'/video/'+str(t.id)).status_code==403
    t.cancelled=True;db.commit();assert c.get(url).status_code in {403,404}


def test_portal_rooms_unique_shared_and_authorization(db,people,video_cleanup):
    row,t=make(db,people)
    hybrid.configure_term(db,row,t,{'delivery_mode':'online','video_kind':'term'})
    second=SeminarSession(seminar_id=row.id,starts_at=t.starts_at+timedelta(days=14),ends_at=t.ends_at+timedelta(days=14))
    db.add(second);db.flush();hybrid.configure_term(db,row,second,{'delivery_mode':'online','video_kind':'term'})
    assert t.meeting_id!=second.meeting_id
    meeting=db.get(Meeting,t.meeting_id)
    assert not meeting.guest_token
    assert hybrid.authorized_room(db,people[0],meeting)
    assert not hybrid.authorized_room(db,people[1],meeting)
    a=rec(db,row,t,people[1],status='confirmed');hybrid.set_modes(db,row,a,{})
    assert hybrid.authorized_room(db,people[1],meeting)
    a.status='cancelled';assert not hybrid.authorized_room(db,people[1],meeting)
    hybrid.configure_term(db,row,t,{'delivery_mode':'online','video_kind':'series'})
    hybrid.configure_term(db,row,second,{'delivery_mode':'online','video_kind':'series'})
    assert t.meeting_id==second.meeting_id and row.video_room
    row.status='draft';assert not hybrid.authorized_room(db,people[0],db.get(Meeting,t.meeting_id))


def test_personal_mode_csrf_and_calendar_topic_location(db,people):
    row,t=make(db,people);t.delivery_mode='hybrid';t.title='Wissenshäppchen';t.location='Otterberg'
    a=rec(db,row,t,people[1],status='confirmed');db.commit();c=login(people[1].email,'passwort-test-123')
    page=c.get(sm.personal_path(a));url=sm.personal_path(a)+'/mode/'+str(t.id)
    assert c.post(url,data={'mode':'online'}).status_code==400
    assert c.post(url,data={'csrf':csrf_of(page.text),'mode':'online'}).status_code==303
    db.refresh(a);assert hybrid.mode(a,t)=='online'
    calendar=sm.calendar_text(db,row,a)
    assert 'Wissenshäppchen' in calendar and 'LOCATION:Online' in calendar and 'Teilnahme: Online' in calendar
    mine=c.get('/seminare?tab=mine').text;assert 'Wissenshäppchen' in mine and 'Online' in mine


def test_external_teacher_notice_is_opt_in_and_contains_no_access_token(db,people,monkeypatch):
    row,t=make(db,people)
    t.guests_json=json.dumps([{'name':'Extern','email':'external@example.org','lead':True}]);db.flush()
    out=[];monkeypatch.setattr(series.notify,'enqueue',lambda *args,**kw:out.append(args[1:4]))
    series.staff_message(db,row,'Veröffentlicht','Termine prüfen',[t])
    assert all(x[0]!='external@example.org' for x in out)
    series.staff_message(db,row,'Veröffentlicht','Termine prüfen',[t],include_external=True)
    external=next(x for x in out if x[0]=='external@example.org')
    assert 'Rathaus' in external[2] and '/participants' not in external[2] and 'jwt=' not in external[2]
    assert series.teachers(db,row,t)[0]['lead']


def test_known_portal_room_cannot_bypass_seminar_access(db,people,video_cleanup):
    row,t=make(db,people)
    hybrid.configure_term(db,row,t,{'delivery_mode':'online','video_kind':'term'})
    meeting=db.get(Meeting,t.meeting_id);meeting.guest_token='unguessable-seminar-guest-test';db.commit()
    outsider=people[3];outsider.permissions='video';db.commit()
    c=login(outsider.email,'passwort-test-123')
    assert c.get('/jitsi/auth',params={'room':meeting.room}).status_code in {403,404}
    assert client().get('/g/'+meeting.guest_token).status_code in {403,404}
    a=rec(db,row,t,people[1],status='confirmed');hybrid.set_modes(db,row,a,{});db.commit()
    participant=login(people[1].email,'passwort-test-123')
    response=participant.get(sm.personal_path(a)+'/video/'+str(t.id))
    assert response.status_code==303 and 'jwt=' in response.headers['location']
    # Switching a generated room no longer attached to a term never opens it to general users.
    hybrid.configure_term(db,row,t,{'delivery_mode':'online','video_kind':'series'});db.commit()
    assert hybrid.is_seminar_room(db,meeting) and not hybrid.authorized_room(db,outsider,meeting)



def test_guest_teacher_explicit_private_invite_and_revocation(db,people,video_cleanup,monkeypatch):
    from app.db import SeminarLecturerAccess
    from app.security import decrypt
    row,t=make(db,people)
    hybrid.configure_term(db,row,t,{'delivery_mode':'online','video_kind':'term'})
    t.guests_json=json.dumps([{'name':'Externer Dozent','email':'teacher-external@example.org'}]);db.flush()
    notices=[];monkeypatch.setattr(series.notify,'enqueue',lambda *args,**kw:notices.append(args[1:4]))
    series.staff_message(db,row,'Veröffentlicht','Termine prüfen',[t])
    assert not db.scalar(select(SeminarLecturerAccess))
    series.staff_message(db,row,'Veröffentlicht','Termine prüfen',[t],include_external=True);db.commit()
    access=db.scalar(select(SeminarLecturerAccess).where(SeminarLecturerAccess.term_id==t.id))
    token=decrypt(access.token_enc);url='/seminare/dozent/'+token;c=client();page=c.get(url)
    assert page.status_code==200 and 'Externer Dozent' in page.text and people[1].email not in page.text
    assert token not in client().get(f'/seminare/{row.id}').text
    assert c.post(url+'/video').status_code==400
    response=c.post(url+'/video',data={'csrf':csrf_of(page.text)})
    assert response.status_code==303 and 'jwt=' in response.headers['location']
    assert not db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id))
    t.guests_json='[]';db.commit();assert c.get(url).status_code==404
    t.guests_json=json.dumps([{'name':'Externer Dozent','email':'teacher-external@example.org'}]);access.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert c.get(url).status_code==404


def test_fixed_circle_prevents_uninvited_public_registration(db,people):
    from app import seminar_fixed
    from app.db import Group
    row,t=make(db,people);group=Group(name='Hybrid fixed private',members=[people[1]])
    db.add(group);db.flush();seminar_fixed.configure(db,row,[group.id],True)
    seminar_fixed.enroll_published(db,row,[t]);db.commit()
    outsider=login(people[3].email,'passwort-test-123');page=outsider.get(f'/seminare/{row.id}')
    assert 'festen Teilnehmerkreis' in page.text
    assert outsider.post(f'/seminare/{row.id}/register',data={'csrf':csrf_of(page.text),'sessions':[t.id]}).status_code==403
    assert len(list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id))))==1
    db.delete(group);db.commit()
