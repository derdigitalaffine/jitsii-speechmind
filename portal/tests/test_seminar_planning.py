from datetime import date
import json
import pytest
from fastapi import HTTPException
from app import seminar_planning as planning, seminars as sm
from app.db import SeminarSession
from app.routes_seminar_planning import save
from test_seminars import people, make


def data(**kw):
    value={'title':'Wissenshäppchen','schedule':{'first':'2027-01-01','time':'10:00','duration':60,'kind':'monthly_weekday','nth':-1,'weekday':4,'count':3},'locations':['Otterbach','Otterberg'],'channels':['internal'],'lecturers':[],'guests':[],'action':'save'}
    value.update(kw);return value


def test_calendar_last_weekday_and_first_monday():
    v=data();p=planning.preview(v)
    assert [t['starts_at'] for t in p['terms']]==['2027-01-29T10:00','2027-02-26T10:00','2027-03-26T10:00']
    assert [t['location'] for t in p['terms']]==['Otterbach','Otterberg','Otterbach']
    v['schedule'].update(nth=1,weekday=0)
    assert [t['starts_at'][:10] for t in planning.preview(v)['terms']]==['2027-01-04','2027-02-01','2027-03-01']


def test_holidays_skip_keeps_location_alternation_and_until_bound():
    v=data();v['schedule'].update(first='2027-03-12',kind='fortnightly',skip_holidays=True,count=3)
    p=planning.preview(v)
    assert [t['starts_at'][:10] for t in p['terms']]==['2027-03-12','2027-04-09']
    assert [t['location'] for t in p['terms']]==['Otterbach','Otterberg']
    assert planning.holiday(date(2027,3,26))=='Karfreitag'
    assert planning.holiday(date(2027,5,27))=='Fronleichnam'
    v['schedule'].update(end_mode='until',until='2027-04-20')
    assert len(planning.preview(v)['terms'])==2
    v['schedule']['until']='2040-01-01'
    with pytest.raises(HTTPException):planning.preview(v)


def test_manual_dates_sorted_unique_and_duration_validation():
    v=data();v['schedule'].update(kind='dates',dates=['2027-03-03','2027-01-01','2027-03-03'])
    assert len(planning.preview(v)['terms'])==2
    v['schedule']['duration']=0
    with pytest.raises(HTTPException):planning.preview(v)


def test_initial_save_lecturers_external_and_draft(db,people):
    v=data(lecturers=[people[2].id],lead_id=people[2].id,guests=[{'name':'Externe Dozentin','organization':'Institut'}]);v['terms']=planning.preview(v)['terms']
    row=save(db,people[0],v);db.commit()
    assert json.loads(row.lecturers_json)==[people[2].id]
    assert len(sm.sessions(db,row))==3
    assert all(json.loads(t.guests_json)[0]['name']=='Externe Dozentin' for t in sm.sessions(db,row))
    assert row.lead_id==people[2].id
    draft=save(db,people[0],{'action':'draft','title':'Noch offen','schedule':{'first':''}});db.commit()
    assert not sm.sessions(db,draft) and json.loads(draft.planning_json)['schedule']['first']==''


def test_existing_terms_not_silently_lost_or_other_seminar_reused(db,people):
    row,t=make(db,people)
    with pytest.raises(HTTPException):save(db,people[0],data(revision=row.revision,terms=[]),row)
    db.rollback()
    v=data(terms=[{'id':t.id,'revision':0,'starts_at':'2027-01-01T10:00','ends_at':'2027-01-01T11:00'}])
    with pytest.raises(HTTPException):save(db,people[0],v)
    db.rollback()


def test_reedit_inherits_doctors_and_keeps_explicit_term_override(db,people):
    from app.routes_seminar_planning import state
    v=data(lecturers=[people[2].id],lead_id=people[2].id,guests=[{'name':'Reihendozentin'}])
    v['terms']=planning.preview(v)['terms'];row=save(db,people[0],v);db.commit()
    loaded=state(db,row)
    assert loaded['terms'][0]['lecturers'] is None and loaded['terms'][0]['guests'] is None
    loaded.update(action='save',lecturers=[people[1].id],lead_id=people[1].id,guests=[{'name':'Neue Reihendozentin'}])
    loaded['terms'][0]['inherit_new']=True
    loaded['terms'][1].update(lecturers=[people[2].id],lead_id=people[2].id,guests=[{'name':'Terminexpertin'}],customized=True)
    save(db,people[0],loaded,row);db.commit()
    terms=sm.sessions(db,row,False)
    assert terms[0].lecturers_json=='' and terms[0].lead_id==people[1].id
    assert json.loads(terms[0].guests_json)[0]['name']=='Neue Reihendozentin'
    assert json.loads(terms[1].lecturers_json)==[people[2].id]
    assert json.loads(terms[1].guests_json)[0]['name']=='Terminexpertin'
    assert state(db,row)['terms'][1]['customized'] is True
    # Unselected inherited terms retain the old defaults, including historical terms.
    assert json.loads(terms[2].lecturers_json)==[people[2].id]
    assert json.loads(terms[2].guests_json)[0]['name']=='Reihendozentin'
    assert terms[2].lead_id==people[2].id


def test_excluding_all_dates_cannot_save_as_ready(db,people):
    v=data();v['terms']=planning.preview(v)['terms']
    for t in v['terms']:t['include']=False
    with pytest.raises(HTTPException):save(db,people[0],v)
    db.rollback()


def test_initial_external_main_and_reusable_directory(db,people):
    from sqlalchemy import select
    from app.db import SeminarExternalLecturer
    name='External '+people[0].email
    v=data(guests=[{'name':name,'lead':True,'save':True,'email':'lecturer@example.org'}]);v['terms']=planning.preview(v)['terms']
    row=save(db,people[0],v);db.commit()
    lecturer=db.scalar(select(SeminarExternalLecturer).where(SeminarExternalLecturer.name==name))
    assert lecturer and json.loads(row.guests_json)[0]['lead'] is True
    db.delete(lecturer);db.commit()


def test_planner_json_create_end_to_end_and_csrf(db,people):
    import re
    from conftest import login
    c=login(people[0].email,'passwort-test-123')
    page=c.get('/seminare/planen')
    assert page.status_code==200 and 'Schritt für Schritt' in page.text
    config=json.loads(re.search(r'<script[^>]*id="sp-data"[^>]*>(.*?)</script>',page.text,re.S).group(1))
    v=data(action='draft',csrf=config['csrf'],lecturers=[people[2].id],guests=[{'name':'Extern'}]);v['terms']=planning.preview(v)['terms']
    assert c.post('/seminare/planen',json={**v,'csrf':'invalid'}).status_code==400
    response=c.post('/seminare/planen',json=v)
    assert response.status_code==200 and response.json()['redirect'].endswith('/planen')
    sid=int(response.json()['redirect'].split('/')[2])
    row=db.get(__import__('app.db',fromlist=['Seminar']).Seminar,sid)
    assert json.loads(row.lecturers_json)==[people[2].id]
    assert len(sm.sessions(db,row))==3


def test_unpublished_draft_term_can_be_removed_without_cancelling(db,people):
    from app.routes_seminar_planning import state
    v=data(action='draft');v['terms']=planning.preview(v)['terms'];row=save(db,people[0],v);db.commit()
    loaded=state(db,row);assert not loaded['terms'][0]['published']
    loaded['action']='draft';loaded['terms'][0]['include']=False
    save(db,people[0],loaded,row);db.commit()
    assert len(sm.sessions(db,row,False))==2
