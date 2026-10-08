from datetime import timedelta
import pytest
from app import circulations as cl, home, main
from app.db import Absence, CirculationRecipient, get_settings, utcnow
from conftest import login, settings
from test_circulations import actors, make


@pytest.fixture
def only_circulations(db, actors):
    old = get_settings(db)
    settings(module_applications='0', module_resources='0', module_circulations='1')
    main._badge_cache.clear()
    yield
    db.rollback()
    settings(**{key: old.get(key, '') for key in ('module_applications','module_resources','module_circulations')})
    main._badge_cache.clear()


def test_all_tasks_not_dashboard_slice_and_completed_disappear(db, actors, only_circulations, monkeypatch):
    now=utcnow()
    rows = [make(db, actors, title=f'Umlauf {i}', due_on=(now+timedelta(days=i+1)).isoformat()) for i in range(8)]
    monkeypatch.setattr(cl, 'utcnow', lambda: now+timedelta(days=10))
    monkeypatch.setattr('app.routes_workflow.utcnow', lambda: now+timedelta(days=10))
    assert len(cl.pending_tasks(db, actors[1])) == 8
    assert cl.overview(db, actors[1])['count'] == 8 and len(cl.overview(db, actors[1])['items']) == 6
    user = login(actors[1].email, 'passwort-test-123')
    page = user.get('/tasks')
    assert page.status_code == 200
    for row, ver, rec in rows:
        assert f'/umlaeufe/{row.id}?recipient={rec.id}' in page.text
    assert 'Kenntnisnahme erforderlich' in page.text and 'überfällig seit' in page.text
    assert main._task_badge(actors[1]) == 8
    assert home._tasks(db, actors[1])['count'] == 8
    assert user.get('/').status_code == 200
    assert 'data-nav-id="tasks"' in page.text
    row, ver, rec = rows[0]
    cl.acknowledge(db, row, ver, rec, actors[1], 'all', 'ack'); db.commit()
    assert f'/umlaeufe/{row.id}?recipient={rec.id}' not in user.get('/tasks').text
    assert len(cl.pending_tasks(db, actors[1])) == 7


def test_personal_progress_and_sequential_station(db, actors, only_circulations):
    row, ver, rec = make(db, actors, per_item=True, items=[{'key':'doc','kind':'markdown','title':'Text','body':'Inhalt'}])
    cl.acknowledge(db, row, ver, rec, actors[1], 'body', 'ack'); db.commit()
    task = cl.pending_tasks(db, actors[1])[0]
    assert task['done'] == 1 and task['required'] == 2 and task['ready']
    row2, ver2, rec2 = make(db, actors, mode='approval', sequential=True)
    rec2.position=2
    db.add(CirculationRecipient(version_id=ver2.id, user_id=actors[2].id, name=actors[2].name, email=actors[2].email, position=1))
    db.commit()
    page=login(actors[1].email,'passwort-test-123').get('/tasks')
    assert page.status_code == 200 and '1 / 2 Nachweise' in page.text
    assert 'Sie sind später an der Reihe' in page.text
    assert not next(t for t in cl.pending_tasks(db,actors[1]) if t['row'].id==row2.id)['ready']


def test_proxy_approval_only_and_no_other_users_tasks(db, actors, only_circulations):
    db.add(Absence(user_id=actors[1].id, substitute_id=actors[2].id, created_by=actors[1].id,
                   starts_on=cl.absence.today(), ends_on=cl.absence.today(), status='confirmed'));db.commit()
    ack, _, _ = make(db, actors, title='Persönliche Kenntnisnahme')
    approval, _, rec = make(db, actors, title='Vertretbare Freigabe', mode='approval', allow_proxy_approval=True)
    tasks=cl.pending_tasks(db,actors[2])
    assert [t['row'].id for t in tasks]==[approval.id] and tasks[0]['proxy']
    html=login(actors[2].email,'passwort-test-123').get('/tasks').text
    assert f'/umlaeufe/{approval.id}?recipient={rec.id}' in html and 'als Vertretung für' in html
    assert f'/umlaeufe/{ack.id}?' not in html
    assert cl.pending_tasks(db,actors[3]) == []


def test_info_unpublished_expired_archived_hidden_and_module_disabled(db, actors, only_circulations, monkeypatch):
    make(db, actors, mode='info')
    now=utcnow()
    expired, _, _=make(db,actors,expires_on=(now+timedelta(days=1)).isoformat())
    archive, _, _=make(db,actors);archive.archived=True;db.commit()
    make(db,actors,publish_on=(now+timedelta(days=3)).isoformat())
    monkeypatch.setattr(cl, 'utcnow', lambda: now+timedelta(days=2))
    assert cl.pending_tasks(db,actors[1]) == []
    make(db,actors)
    assert main._task_badge(actors[1])==1
    settings(module_circulations='0')
    user=login(actors[1].email,'passwort-test-123')
    assert user.get('/tasks').status_code == 404
    assert main._task_badge(actors[1])==0
    assert 'data-nav-id="tasks"' not in user.get('/').text
