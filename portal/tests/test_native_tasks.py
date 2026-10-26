"""Native task boundaries, review, concurrent writes and the shared workplace."""
import secrets
from datetime import datetime
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError
from app import tasks as ts, task_capture, task_overview
from app.db import User, SessionLocal, get_settings
from app.task_models import Task, TaskActivity, TaskAttachment, TaskCheck, TaskComment, TaskParticipant, TaskDependency, TaskSeries, TaskReminder, TaskOccurrence, TaskExternal, TaskRule, TaskRuleRun
from conftest import login, csrf_of, settings


@pytest.fixture
def task_people(db):
    old = get_settings(db)
    settings(module_tasks='1')
    from app.security import hash_password
    key = secrets.token_hex(5)
    people = [User(name=name, email=f'task-{i}-{key}@example.org', permissions='tasks' if i < 3 else '',
                   password_hash=hash_password('task-passwort-123'), active=True)
              for i, name in enumerate(['Anna Eins', 'Bert Zwei', 'Anna Drei', 'Unbeteiligt'])]
    db.add_all(people); db.commit()
    yield people
    db.rollback()
    ids = list(db.scalars(select(Task.id).where(Task.creator_id.in_([u.id for u in people]))))
    for attachment in db.scalars(select(TaskAttachment).where(TaskAttachment.task_id.in_(ids))):
        if not attachment.is_reference and attachment.storage_key:
            ts.attachment_path(attachment).unlink(missing_ok=True)
    for model in (TaskRuleRun, TaskExternal, TaskOccurrence, TaskDependency, TaskReminder, TaskAttachment, TaskComment, TaskCheck, TaskParticipant, TaskActivity):
        if model is TaskDependency:
            db.query(model).filter((model.task_id.in_(ids)) | (model.blocker_id.in_(ids))).delete(synchronize_session=False)
        else:
            db.query(model).filter(model.task_id.in_(ids)).delete(synchronize_session=False)
    db.query(Task).filter(Task.id.in_(ids)).delete(synchronize_session=False)
    db.query(TaskSeries).filter(TaskSeries.creator_id.in_([u.id for u in people])).delete(synchronize_session=False)
    db.query(TaskRule).filter(TaskRule.creator_id.in_([u.id for u in people])).delete(synchronize_session=False)
    db.commit()
    for person in people: db.delete(person)
    db.commit()
    settings(module_tasks=old.get('module_tasks', '1'))


def make(db, people, **values):
    row = ts.create(db, people[0], dict(title='Präsentation vorbereiten', assignee_id=str(people[1].id), **values))
    db.commit()
    return row


def client_for(person):
    c = login(person.email, 'task-passwort-123')
    return c, csrf_of(c.get('/tasks').text)


def test_native_rights_validation_and_review(db, task_people):
    a, b, follower, stranger = task_people
    row = make(db, task_people, requires_review='1')
    with pytest.raises(HTTPException): ts.get(db, stranger, row.id)
    with pytest.raises(HTTPException): ts.create(db, stranger, {'title': 'No'})
    db.add(TaskParticipant(task_id=row.id, user_id=follower.id)); db.commit()
    assert ts.get(db, follower, row.id)
    with pytest.raises(HTTPException): ts.transition(db, follower, row, 'done')
    ts.transition(db, b, row, 'in_progress'); db.commit()
    ts.transition(db, b, row, 'done'); db.commit()
    assert row.status == 'review' and row.completed_at is None
    with pytest.raises(HTTPException): ts.transition(db, b, row, 'done')
    with pytest.raises(ts.Invalid): ts.transition(db, a, row, 'in_progress')
    ts.transition(db, a, row, 'in_progress', 'Bitte Zahlen ergänzen.'); db.commit()
    ts.transition(db, b, row, 'done'); db.commit()
    ts.transition(db, a, row, 'done'); db.commit()
    assert row.completed_by == a.id and row.completed_at
    assert db.scalar(select(TaskComment).where(TaskComment.task_id == row.id)).body == 'Bitte Zahlen ergänzen.'
    ts.transition(db, a, row, 'open'); db.commit()
    with pytest.raises(ts.Invalid): ts.update(db, a, row, {**ts.form_values(row), 'priority': 'wild'})
    b.active = False; db.commit()
    with pytest.raises(ts.Invalid): ts.values(db, ts.form_values(row), a)
    b.active = True; db.commit()


def test_forms_csrf_error_preservation_seen_and_disabled_module(db, task_people):
    row = make(db, task_people)
    a, b, _, outsider = task_people
    c, csrf = client_for(a)
    assert c.get(f'/aufgaben/{row.id}').status_code == 200
    db.refresh(row); assert row.seen_at is None
    assert c.post(f'/aufgaben/{row.id}/aktion', data={'action': 'status', 'status': 'done'}).status_code == 400
    d, token = client_for(b)
    html = d.get(f'/aufgaben/{row.id}').text
    db.refresh(row); assert row.seen_at is not None and 'Loslegen' in html
    stranger, _ = client_for(outsider)
    assert stranger.get(f'/aufgaben/{row.id}').status_code == 404
    bad = c.post('/aufgaben/neu', data={'csrf': csrf, 'title': 'Eingabe bleibt erhalten', 'assignee_id': 'nobody'})
    assert bad.status_code == 422 and 'Eingabe bleibt erhalten' in bad.text
    settings(module_tasks='0')
    assert d.get(f'/aufgaben/{row.id}').status_code == 404
    html = d.get('/tasks?source=native').text
    assert row.title not in html and 'value="native"' not in html and '/aufgaben/vorschau' not in html


def test_parser_dates_people_and_no_silent_ambiguity(task_people, monkeypatch):
    from zoneinfo import ZoneInfo
    from app import db as db_module
    monkeypatch.setattr(ts, "LOCAL_TZ", ZoneInfo("Europe/Berlin"))
    monkeypatch.setattr(db_module, "LOCAL_TZ", ZoneInfo("Europe/Berlin"))
    now = datetime(2026, 12, 31, 12)
    values, notices, _ = task_capture.parse('Plan bis morgen 14:30 @Bert #Marketing !hoch', task_people, task_people[0].id, now=now)
    assert values == dict(title='Plan', due_date='2027-01-01', due_time='14:30', assignee_id=str(task_people[1].id), priority='high', tags='Marketing')
    assert not notices
    values, notices, _ = task_capture.parse('Plan @Anna bis 31.02.2027', task_people, task_people[0].id, now=now)
    assert notices and not values['assignee_id'] and '31.02.2027' in values['title']
    assert task_capture.parse('Ganz normaler Text', [], 1, now=now)[0]['title'] == 'Ganz normaler Text'
    with pytest.raises(ts.Invalid): ts.local_date('2026-03-29T02:30')
    with pytest.raises(ts.Invalid): ts.local_date('2026-10-25T02:30')
    assert ts.local_date('2026-03-29T03:30') == datetime(2026, 3, 29, 1, 30)


def test_markdown_mentions_and_checklist_rights(db, task_people):
    row = make(db, task_people)
    html = str(ts.markdown('<script>alert(1)</script> [x](javascript:alert(1)) **okay**'))
    assert '<script>' not in html and 'href="javascript:' not in html and '<strong>okay</strong>' in html
    with pytest.raises(ts.Invalid): ts.comment(db, task_people[0], row, f'Hallo @[{task_people[3].id}]')
    ts.comment(db, task_people[0], row, f'Hallo @[{task_people[1].id}]'); db.commit()
    db.add(TaskCheck(task_id=row.id, title='Zahlen prüfen')); db.commit()
    with pytest.raises(ts.Invalid): ts.transition(db, task_people[1], row, 'done')


def test_stale_versions_do_not_overwrite(db, task_people):
    row = make(db, task_people)
    with SessionLocal() as second:
        old = second.get(Task, row.id)
        ts.transition(db, task_people[1], row, 'in_progress'); db.commit()
        old.title = 'Veraltetes Update'
        with pytest.raises(StaleDataError): second.commit()
    db.refresh(row)
    with pytest.raises(ts.Invalid): ts.check_version(row, {'version': row.version - 1})
    assert row.title == 'Präsentation vorbereiten'


def test_common_workplace_delegation_and_view_consistency(db, task_people):
    row = make(db, task_people, due_date='2026-01-01', priority='urgent', tags='Planung')
    owner = task_overview.collect(db, task_people[0], {'tasks'})
    assigned = task_overview.collect(db, task_people[1], {'tasks'})
    assert owner['count'] == 0 and len(owner['delegated']) == 1
    assert assigned['count'] == assigned['overdue'] == 1
    c, csrf = client_for(task_people[1])
    for mode in ['list', 'board', 'calendar', 'timeline']:
        r = c.get(f'/tasks?view={mode}&tag=Planung&date=2026-01-01')
        assert r.status_code == 200 and row.title in r.text and f'/aufgaben/{row.id}' in r.text
    assert 'tag=Planung' in c.get('/tasks').text


def test_attachments_traversal_spoofing_foreign_access_and_removal(db, task_people):
    row = make(db, task_people)
    c, token = client_for(task_people[0])
    r = c.post(f'/aufgaben/{row.id}/dateien', data={'csrf': token, 'version': row.version},
               files={'files': ('../../evil.html', b'<script>alert(1)</script>', 'image/png')})
    assert r.status_code == 303
    db.refresh(row)
    file = db.scalar(select(TaskAttachment).where(TaskAttachment.task_id == row.id))
    assert file.name == 'evil.html' and file.mime == 'application/octet-stream'
    r = c.get(f'/aufgaben/{row.id}/dateien/{file.id}?preview=true')
    assert r.status_code == 200 and r.headers['content-type'] == 'application/octet-stream'
    assert r.headers['content-disposition'].startswith('attachment') and r.headers['x-content-type-options'] == 'nosniff'
    outsider, _ = client_for(task_people[3])
    assert outsider.get(f'/aufgaben/{row.id}/dateien/{file.id}').status_code == 404
    another = ts.create(db, task_people[0], {'title': 'Andere Aufgabe'})
    db.commit()
    assert c.get(f'/aufgaben/{another.id}/dateien/{file.id}').status_code == 404
    assert c.post(f'/aufgaben/{row.id}/dateien/{file.id}/entfernen', data={'csrf':token,'version':row.version}).status_code == 303
    assert not ts.attachment_path(file).exists()


def test_dependencies_reject_cycle_unblock_once_and_hide_foreign_title(db, task_people):
    a = make(db, task_people)
    b = ts.create(db, task_people[0], {'title': 'Folgeschritt', 'assignee_id': task_people[1].id}); db.commit()
    ts.add_dependency(db, task_people[0], b, a.id); db.commit()
    with pytest.raises(ts.Invalid): ts.add_dependency(db, task_people[0], a, b.id)
    with pytest.raises(ts.Invalid): ts.transition(db, task_people[1], b, 'in_progress')
    view = task_overview.collect(db, task_people[1], {'tasks'})
    assert view['count'] == 1 and view['waiting_count'] == 1
    ts.transition(db, task_people[1], a, 'done'); db.commit()
    ts.transition(db, task_people[1], a, 'done'); db.commit()
    assert not ts.blockers(db,b)
    assert len(list(db.scalars(select(TaskActivity).where(TaskActivity.task_id == b.id, TaskActivity.kind == 'unblocked')))) == 1


def test_quick_capture_confirms_inline_and_keeps_ambiguous_input(db,task_people):
    c,token=client_for(task_people[0])
    response=c.post('/aufgaben/vorschau',data={'csrf':token,'capture':'Plan bis morgen @Anna #Planung !hoch'})
    assert response.status_code==200 and 'Meine Aufgaben' in response.text
    assert 'Kurz prüfen, dann loslegen' in response.text and 'mehrdeutig' in response.text
    assert 'name="inline_capture" value="1"' in response.text and 'name="title" value="Plan @Anna"' in response.text
    assert not db.scalar(select(Task))
    bad=c.post('/aufgaben/neu',data={'csrf':token,'inline_capture':'1','title':'Eingabe behalten','assignee_id':'','original':'Original'})
    assert bad.status_code==422 and 'Kurz prüfen, dann loslegen' in bad.text and 'Eingabe behalten' in bad.text


def test_delegation_keeps_completed_work_and_archive_is_findable(db,task_people):
    row=make(db,task_people)
    ts.transition(db,task_people[1],row,'done');db.commit()
    view=task_overview.collect(db,task_people[0],{'tasks'})
    assert row.title in [item['title'] for item in task_overview.filtered(view,perspective='delegated')['ready']]
    row.archived_at=ts.utcnow();db.commit()
    view=task_overview.collect(db,task_people[0],{'tasks'})
    assert not view['ready'] and not view['delegated'] and len(view['archive'])==1
    c,token=client_for(task_people[0])
    assert row.title in c.get('/tasks?perspective=archive').text


def test_dependency_diamond_only_unblocks_after_both_branches(db,task_people):
    first=make(db,task_people)
    branches=[ts.create(db,task_people[0],{'title':f'Zweig {i}','assignee_id':task_people[1].id}) for i in [1,2]]
    last=ts.create(db,task_people[0],{'title':'Gemeinsamer Abschluss','assignee_id':task_people[1].id});db.commit()
    for branch in branches:
        ts.add_dependency(db,task_people[0],branch,first.id)
        ts.add_dependency(db,task_people[0],last,branch.id)
    db.commit()
    ts.transition(db,task_people[1],first,'done');db.commit()
    ts.transition(db,task_people[1],branches[0],'done');db.commit()
    assert len(ts.blockers(db,last))==1
    ts.transition(db,task_people[1],branches[1],'done');db.commit()
    assert not ts.blockers(db,last)


def test_board_choices_offer_only_possible_next_steps(db,task_people):
    row=make(db,task_people,requires_review='1')
    choices=ts.status_choices(task_people[1],row)
    assert choices['done']=='Zur Freigabe einreichen' and 'cancelled' not in choices and 'review' not in choices
    assert 'done' not in ts.status_choices(task_people[1],row,unfinished=True)
    assert 'in_progress' not in ts.status_choices(task_people[1],row,blocked=True)
    ts.transition(db,task_people[1],row,'done');db.commit()
    assert not ts.status_choices(task_people[1],row)
    assert 'done' in ts.status_choices(task_people[0],row)
