"""Conventional creation is one transaction, including checklists and initial attachments."""
from html import unescape
import re
from pathlib import Path
import pytest
from sqlalchemy import func, select
from app import tasks as ts
from app.config import settings as config
from app.db import Notification
from app.task_models import Task, TaskActivity, TaskAttachment, TaskCheck
from conftest import settings
from test_native_tasks import task_people, client_for, make  # noqa: F401


def task_files():
    root=config.data_dir/'task-files'
    return {path for path in root.rglob('*') if path.is_file()} if root.exists() else set()


def test_form_is_visible_next_to_quick_capture_and_keeps_return_context(db,task_people):
    c,token=client_for(task_people[0])
    html=c.get('/tasks?perspective=delegated&view=board&tag=Planung').text
    assert 'id="capture-text"' in html and 'Mit Formular anlegen' in html
    path=unescape(re.search(r'href="([^"]*/aufgaben/neu\?[^\"]+)"',html).group(1))
    response=c.get(path)
    assert response.status_code==200
    assert all(f'name="{key}"' in response.text for key in ['title','description','assignee_id','due_date','checklist','files'])
    assert 'enctype="multipart/form-data"' in response.text and 'zur bisherigen Aufgabenübersicht' in response.text
    assert 'perspective=delegated&amp;tag=Planung&amp;view=board' in response.text


def test_create_with_checklist_and_files_returns_to_the_filtered_overview(db,task_people):
    c,token=client_for(task_people[0])
    back='/tasks?perspective=delegated&view=board'
    data={'csrf':token,'title':'Besprechung vorbereiten','description':'Bitte die Zahlen und Unterlagen zusammenstellen.',
          'assignee_id':str(task_people[1].id),'due_date':'2026-12-01','due_time':'14:30',
          'checklist':'  Unterlagen sammeln  \n\nZahlen prüfen\nRückmeldung einholen','back':back}
    response=c.post('/aufgaben/neu',data=data,files=[('files',('../../Plan.txt',b'Plan','text/plain')),
                       ('files',('Briefing.pdf',b'%PDF-briefing','image/png'))])
    assert response.status_code==303 and response.headers['location']==back
    task=db.scalar(select(Task).where(Task.title==data['title']))
    assert task and task.assignee_id==task_people[1].id and task.description==data['description']
    assert task.due_at==ts.local_date('2026-12-01T14:30')
    checks=list(db.scalars(select(TaskCheck).where(TaskCheck.task_id==task.id).order_by(TaskCheck.position)))
    assert [check.title for check in checks]==['Unterlagen sammeln','Zahlen prüfen','Rückmeldung einholen']
    assert all(not check.done for check in checks)
    files=list(db.scalars(select(TaskAttachment).where(TaskAttachment.task_id==task.id).order_by(TaskAttachment.id)))
    assert [file.name for file in files]==['Plan.txt','Briefing.pdf']
    assert all(file.uploaded_by==task_people[0].id and file.mime=='application/octet-stream' for file in files)
    recipient,_=client_for(task_people[1])
    assert recipient.get(f'/aufgaben/{task.id}/dateien/{files[0].id}').content==b'Plan'
    html=c.get(response.headers['location']).text
    assert 'angelegt.' in html and data['title'] in html


def test_validation_retains_form_values_and_explains_file_reselection(db,task_people):
    c,token=client_for(task_people[0])
    before=task_files()
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Eingabe bleibt','description':'Wichtige Beschreibung',
                    'assignee_id':'unbekannt','checklist':'Erster Punkt\nZweiter Punkt','back':'/tasks?view=calendar'},
                    files={'files':('Unterlagen.txt',b'Text','text/plain')})
    assert response.status_code==422
    assert all(value in response.text for value in ['Eingabe bleibt','Wichtige Beschreibung','Erster Punkt\nZweiter Punkt','/tasks?view=calendar'])
    assert 'Dateien erneut' in response.text
    assert not db.scalar(select(Task)) and task_files()==before


def test_later_invalid_file_rolls_back_task_checklist_mail_and_earlier_file(db,task_people,monkeypatch):
    c,token=client_for(task_people[0])
    monkeypatch.setattr(ts,'MAX_FILE',5)
    before=task_files()
    notifications=db.scalar(select(func.count(Notification.id)))
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Alles zusammen','assignee_id':task_people[1].id,'checklist':'Nicht teilweise speichern'},
                    files=[('files',('gueltig.txt',b'12345','text/plain')),('files',('zu-gross.txt',b'123456','text/plain'))])
    assert response.status_code==422 and 'erneut' in response.text
    assert not db.scalar(select(Task)) and not db.scalar(select(TaskCheck)) and not db.scalar(select(TaskAttachment))
    assert not db.scalar(select(TaskActivity)) and task_files()==before
    assert db.scalar(select(func.count(Notification.id)))==notifications


def test_storage_error_rolls_back_and_keeps_text(db,task_people,monkeypatch):
    c,token=client_for(task_people[0])
    original=Path.write_bytes
    def fail_task_write(path,content):
        if 'task-files' in path.parts:raise OSError('Disk unavailable')
        return original(path,content)
    monkeypatch.setattr(Path,'write_bytes',fail_task_write)
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Bei Fehler erhalten','assignee_id':task_people[0].id,'checklist':'Punkt behalten'},
                    files={'files':('Datei.txt',b'Inhalt','text/plain')})
    assert response.status_code==422 and 'noch nicht angelegt' in response.text
    assert 'Bei Fehler erhalten' in response.text and 'Punkt behalten' in response.text
    assert not db.scalar(select(Task))


@pytest.mark.parametrize('checklist',['x'*501,'\n'.join(f'Punkt {i}' for i in range(51))])
def test_checklist_limits_do_not_create_partial_tasks(db,task_people,checklist):
    c,token=client_for(task_people[0])
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Zu große Checkliste','assignee_id':task_people[0].id,'checklist':checklist})
    assert response.status_code==422 and 'höchstens 50' in response.text and 'Zu große Checkliste' in response.text
    assert not db.scalar(select(Task))


def test_upload_count_and_create_authority_are_checked_on_server(db,task_people):
    c,token=client_for(task_people[0])
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Zu viele Dateien','assignee_id':task_people[0].id},
                    files=[('files',(f'{i}.txt',b'x','text/plain')) for i in range(11)])
    assert response.status_code==422 and 'zehn Dateien' in response.text and not db.scalar(select(Task))
    stranger,token=client_for(task_people[3])
    assert 'Mit Formular anlegen' not in stranger.get('/tasks').text
    assert stranger.get('/aufgaben/neu').status_code==403
    assert stranger.post('/aufgaben/neu',data={'csrf':token,'title':'Nicht berechtigt'},files={'files':('Test.txt',b'Test')}).status_code==403
    assert not db.scalar(select(Task))
    settings(module_tasks='0')
    assert c.get('/aufgaben/neu').status_code==404


def test_quick_capture_uses_same_return_to_overview_without_extra_fields(db,task_people):
    c,token=client_for(task_people[0])
    back='/tasks?perspective=today&view=list'
    response=c.post('/aufgaben/neu',data={'csrf':token,'title':'Schnell erfasst','assignee_id':task_people[0].id,'inline_capture':'1','back':back})
    assert response.status_code==303 and response.headers['location']==back
    assert db.scalar(select(Task).where(Task.title=='Schnell erfasst'))
    assert not db.scalar(select(TaskCheck)) and not db.scalar(select(TaskAttachment))
