"""Recurrence, source adapters and external capability links."""
import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app import tasks as ts, task_external, task_schedule, task_sources
from app.db import DmsArea, DmsAccess, DmsRecord, Recording, Meeting, User, utcnow
from app.task_models import Task, TaskAttachment, TaskActivity, TaskComment, TaskExternal, TaskReminder, TaskSeries, TaskOccurrence
from conftest import client, csrf_of, settings
from test_native_tasks import task_people, make, client_for  # noqa: F401


def test_recurrence_keys_month_end_leap_year_and_dst(db, task_people, monkeypatch):
    from app import db as dm
    tz = ZoneInfo('Europe/Berlin')
    monkeypatch.setattr(task_schedule, 'LOCAL_TZ', tz)
    monkeypatch.setattr(ts, 'LOCAL_TZ', tz)
    monkeypatch.setattr(dm, 'LOCAL_TZ', tz)
    row = make(db, task_people, due_date='2026-03-28', due_time='02:30')
    series = task_schedule.save_series(db, task_people[0], row, {'repeat':'daily','repeat_count':'3'}); db.commit()
    assert task_schedule.tick(now=datetime(2026,3,28)) == 2
    assert task_schedule.tick(now=datetime(2026,3,28)) == 0
    dates = list(db.scalars(select(Task.due_at).where(Task.series_id == series.id).order_by(Task.due_at)))
    assert dates == [datetime(2026,3,28,1,30), datetime(2026,3,29,1,30), datetime(2026,3,30,0,30)]
    from dateutil.rrule import rrulestr
    rule = task_schedule.recurrence_rule({'repeat':'monthly','repeat_count':'3'}, datetime(2026,1,31,12))
    assert [d.month for d in rrulestr(rule, dtstart=datetime(2026,1,31,12))] == [1,3,5]
    rule = task_schedule.recurrence_rule({'repeat':'yearly','repeat_count':'2'}, datetime(2024,2,29,12))
    assert [d.year for d in rrulestr(rule, dtstart=datetime(2024,2,29,12))] == [2024,2028]
    settings(module_tasks='0')
    assert task_schedule.tick(now=datetime(2027,1,1)) == 0


def test_reminders_are_atomic_retried_and_currently_authorized(db, task_people, monkeypatch):
    row = make(db, task_people, due_date='2026-01-01')
    ts.transition(db, task_people[1], row, 'in_progress'); db.commit()
    task_schedule.set_reminder(db, task_people[0], row, {'offset_minutes':'0','recipient_id':task_people[1].id}); db.commit()
    from app import notify
    sent = []
    def queue(*args, **kwargs): sent.append(args[1]); return True
    monkeypatch.setattr(notify, 'enqueue', queue)
    assert task_schedule.tick(now=row.due_at+timedelta(hours=1)) == 1
    assert task_schedule.tick(now=row.due_at+timedelta(hours=1)) == 0
    assert sent == [task_people[1].email]
    # Changing the due event schedules exactly one new reminder.
    db.refresh(row)
    row.due_at = datetime(2026,1,2,12); db.commit()
    assert task_schedule.tick(now=datetime(2026,1,3)) == 1


def test_external_links_expiry_revocation_exact_scope_and_review(db, task_people):
    row = ts.create(db, task_people[0], {'title':'Extern prüfen','description':'Öffentlicher Auftrag',
                    'external':'1','external_name':'Externe Person','external_email':'extern@example.org','requires_review':'1'})
    db.commit()
    raw = task_external.issue(db, task_people[0], row, comments=True); db.commit()
    link = db.get(TaskExternal,row.id)
    assert link.token_hash == hashlib.sha256(raw.encode()).hexdigest() and raw not in link.token_hash
    c = client()
    r = c.get(f'/aufgaben/gast/{raw}')
    assert r.status_code == 200 and 'Öffentlicher Auftrag' in r.text and '/admin/users' not in r.text
    assert r.headers['cache-control']=='no-store' and r.headers['referrer-policy']=='no-referrer'
    token = csrf_of(r.text)
    db.refresh(row)
    assert c.post(f'/aufgaben/gast/{raw}',data={'csrf':token,'version':row.version,'action':'status','status':'in_progress'}).status_code==303
    db.refresh(row)
    db.add(TaskComment(task_id=row.id, author_id=task_people[0].id, body='Interne sensible Notiz'))
    hidden = TaskAttachment(task_id=row.id, name='Intern.docx', uploaded_by=task_people[0].id)
    db.add(hidden);db.commit()
    assert 'Interne sensible Notiz' not in c.get(f'/aufgaben/gast/{raw}').text
    assert c.get(f'/aufgaben/gast/{raw}/dateien/{hidden.id}').status_code==404
    assert c.post(f'/aufgaben/gast/{raw}',data={'csrf':token,'version':row.version,'action':'status','status':'done'}).status_code==303
    db.refresh(row); assert row.status=='review'
    assert c.post(f'/aufgaben/gast/{raw}',data={'csrf':token,'version':row.version,'action':'status','status':'done'}).status_code==422
    assert db.scalar(select(TaskActivity).where(TaskActivity.task_id==row.id,TaskActivity.kind=='status').order_by(TaskActivity.id.desc())).actor_name.endswith('(extern)')
    newer = task_external.issue(db, task_people[0], row); db.commit()
    assert c.get(f'/aufgaben/gast/{raw}').status_code==404
    link.expires_at = utcnow()-timedelta(seconds=1);db.commit()
    assert c.get(f'/aufgaben/gast/{newer}').status_code==404
    newest=task_external.issue(db,task_people[0],row);db.commit()
    link.revoked_at=utcnow();db.commit()
    assert c.get(f'/aufgaben/gast/{newest}').status_code==404


def test_external_link_invalidated_by_internal_reassignment(db,task_people):
    row=ts.create(db,task_people[0],{'title':'Auftrag','external':'1','external_name':'Gast','external_email':'gast@example.org'})
    db.commit()
    raw=task_external.issue(db,task_people[0],row);db.commit()
    data=ts.form_values(row);data.update(external='',assignee_id=str(task_people[1].id))
    ts.update(db,task_people[0],row,data);db.commit()
    with pytest.raises(HTTPException):task_external.resolve(db,raw)
    assert row.assignee_id==task_people[1].id and not row.external_email


def test_sources_dms_current_rights_and_speechmind_confirmation(db,task_people):
    settings(module_dms='1')
    a,b,*_=task_people
    a.permissions += ',video';db.commit()
    area=DmsArea(name='Aufgaben-Testbereich');db.add(area);db.flush()
    acc=DmsAccess(area_id=area.id,user_id=a.id,level=1);db.add(acc)
    record=DmsRecord(area_id=area.id,title='Vertrauliche Quelle',kind='manuell');db.add(record)
    meeting=Meeting(owner_id=a.id,room='task-'+a.email.split('@')[0],title='Besprechung');db.add(meeting);db.flush()
    original=json.dumps({'tasks':[{'id':'one','text':'Zahlen prüfen','assignedTo':b.name,'date':'2026-12-01'},
                                  {'id':'two','text':'Unklar','assignedTo':'Anna','date':''},
                                  {'id':'three','text':'Unbekannt','assignedTo':'Niemand'}]})
    rec=Recording(meeting_id=meeting.id,room=meeting.room,session_dir='task-'+a.email,summary_json=original);db.add(rec);db.commit()
    try:
        row=task_sources.create_from_source(db,a,'dms',record.id,{'title':'Stellungnahme prüfen'},idempotency_key='stable');db.commit()
        assert task_sources.create_from_source(db,a,'dms',record.id,{'title':'Nicht doppelt'},idempotency_key='stable').id==row.id
        assert task_sources.source_info(db,b,'dms',record.id)['href']==''
        db.delete(acc);db.commit()
        assert task_sources.source_info(db,a,'dms',record.id)['href']==''
        db.delete(record);db.commit()
        assert task_sources.source_info(db,a,'dms',row.source_id)['href']==''
        proposals=task_sources.recording_proposals(db,a,rec)
        assert proposals[0]['assignee_id']==str(b.id)
        assert proposals[1]['assignee_id']==proposals[2]['assignee_id']==''
        c,token=client_for(a)
        r=c.get(f'/aufgaben/aufzeichnung/{rec.id}')
        assert r.status_code==200 and 'Zahlen prüfen' in r.text
        assert db.scalar(select(func.count(Task.id)).where(Task.source_type=='recording'))==0
        payload={'csrf':token,'selected':['0','1'],'title_0':'Zahlen prüfen','assignee_0':b.id,'due_0':'2026-12-01',
                 'title_1':'Unklar','assignee_1':a.id,'due_1':''}
        assert c.post(f'/aufgaben/aufzeichnung/{rec.id}',data=payload).status_code==303
        assert c.post(f'/aufgaben/aufzeichnung/{rec.id}',data=payload).status_code==303
        assert db.scalar(select(func.count(Task.id)).where(Task.source_type=='recording',Task.source_id==str(rec.id)))==2
        db.refresh(rec);assert rec.summary_json==original
    finally:
        db.delete(rec);db.delete(meeting)
        if db.get(DmsAccess,acc.id):db.delete(acc)
        if db.get(DmsRecord,record.id):db.delete(record)
        db.delete(area);db.commit()


def test_view_changes_preserve_status_rights_and_date_validation(db,task_people):
    row=make(db,task_people)
    c,token=client_for(task_people[1])
    payload={'csrf':token,'task_id':row.id,'version':row.version,'due_date':'2026-12-01'}
    assert c.post('/aufgaben/ansicht-aktion',data=payload).status_code==403
    owner,token=client_for(task_people[0]);payload['csrf']=token
    assert owner.post('/aufgaben/ansicht-aktion',data=payload).status_code==303
    db.refresh(row);assert row.due_at
    payload.update(version=row.version,due_date='2026-02-31')
    assert owner.post('/aufgaben/ansicht-aktion',data=payload).status_code==422


def test_dms_attachment_reference_rechecks_access_after_revocation(db,task_people):
    from app.db import DmsFile
    settings(module_dms='1')
    owner=task_people[0]
    area=DmsArea(name='Geschützte Anhänge');db.add(area);db.flush()
    permission=DmsAccess(area_id=area.id,user_id=owner.id,level=1);db.add(permission)
    record=DmsRecord(area_id=area.id,title='Geheim');db.add(record);db.flush()
    file=DmsFile(record_id=record.id,name='Vertrauliche Originaldatei.pdf',file='a'*16+'.pdf');db.add(file);db.commit()
    task=make(db,task_people)
    try:
        c,token=client_for(owner)
        r=c.post(f'/aufgaben/{task.id}/dms-datei',data={'csrf':token,'version':task.version,'dms_file_id':file.id})
        assert r.status_code==303
        attachment=db.scalar(select(TaskAttachment).where(TaskAttachment.task_id==task.id))
        assert attachment.is_reference and not attachment.storage_key and attachment.size==0
        assert c.get(f'/aufgaben/{task.id}/dateien/{attachment.id}').status_code==303
        db.delete(permission);db.commit()
        assert c.get(f'/aufgaben/{task.id}/dateien/{attachment.id}').status_code==404
        assert 'Vertrauliche Originaldatei.pdf' not in c.get(f'/aufgaben/{task.id}').text
    finally:
        db.delete(file);db.delete(record);db.delete(area);db.commit()
