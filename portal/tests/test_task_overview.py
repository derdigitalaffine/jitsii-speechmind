"""Readiness and responsibility determine work, rather than merely missing decisions."""
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from test_circulations import actors  # noqa: F401
from app import task_overview as work, workflow, circulations, resources


def test_sources_share_priority_but_pool_and_blocked_never_become_personal_work(monkeypatch):
    now = datetime(2026, 1, 20, 12)
    user = NS(id=1)
    response = NS(id=7, form_id=2, ref_no='AN-7', form=NS(title='Formular'))
    def task(id, assignee, due):
        return NS(id=id, response=response, assignee_id=assignee, assignee=NS(name='Vertretene Person'),
                  group=NS(name='Personal'), kind='task', name=f'Schritt {id}', due_at=due)
    monkeypatch.setattr(workflow, 'my_tasks', lambda db, user: [task(1, 1, now+timedelta(days=2)), task(2, None, now-timedelta(days=4)), task(3, 2, now-timedelta(days=1))])
    monkeypatch.setattr(workflow, 'waiting_requests', lambda db, user: [NS(title='Unterlagen', response=response, due_at=now-timedelta(days=8))])
    def circulation(id, ready):
        return dict(row=NS(id=id), title=f'Umlauf {id}', recipient_id=id, due=now-timedelta(days=3), ready=ready,
                    action='Freigabe erforderlich', done=0, required=1, proxy=False, stopped=not ready, recipient_name='Empfänger')
    monkeypatch.setattr(circulations, 'pending_tasks', lambda db, user: [circulation(8, True), circulation(9, False)])
    booking = NS(ref='B-1', resource=NS(name='Raum'), name='Buchender')
    monkeypatch.setattr(resources, 'booking_tasks', lambda db, user: [dict(booking=booking, label='Übergabe', href='/resources/bookings/1', due=now, note='', icon='fa-key')])
    monkeypatch.setattr(resources, 'when_text', lambda booking: 'heute')
    view = work.collect(None, user, {'applications', 'circulations', 'resources'}, now=now)
    assert view['count'] == 4 and view['overdue'] == 2
    assert [item['title'] for item in view['ready']][:2] == ['Umlauf 8', 'Schritt 3']
    assert view['group_count'] == 1 and view['pool'][0]['claim_url'].endswith('/task/2')
    assert view['waiting_count'] == 2 and all(not item['late'] for item in view['waiting'])
    proxy = work.filtered(view, 'proxy')
    assert [item['title'] for item in proxy['ready']] == ['Schritt 3']
    assert not proxy['pool'] and not proxy['waiting']
    grouped = work.filtered(view, 'group', 'application')
    assert not grouped['ready'] and len(grouped['pool']) == 1


def test_disabled_sources_are_not_read(monkeypatch):
    def forbidden(*args): raise AssertionError('Disabled module was accessed')
    monkeypatch.setattr(workflow, 'my_tasks', forbidden)
    monkeypatch.setattr(circulations, 'pending_tasks', forbidden)
    monkeypatch.setattr(resources, 'booking_tasks', forbidden)
    view = work.collect(None, NS(id=1), set())
    assert not view['available'] and view['count'] == view['waiting_count'] == view['group_count'] == 0
    assert work.filtered(view, 'invalid', 'invalid')['scope'] == 'all'


def test_actual_resource_viewer_has_no_management_task_and_future_deadline_is_not_late(db, actors):
    from app.db import Resource, ResourceBooking, ResourceShare, Absence, utcnow
    import secrets
    token = secrets.token_hex(6)
    now = utcnow()
    resource = Resource(name='Privater Aufgabenraum', slug='tasks-' + token, owner_id=actors[0].id, public=False)
    db.add(resource); db.flush()
    booking = ResourceBooking(resource_id=resource.id, ref='TASK-' + token, token=token, status='requested',
                              starts_at=now+timedelta(days=5), ends_at=now+timedelta(days=6), name='Kunde', email='task@example.org')
    share = ResourceShare(resource_id=resource.id, user_id=actors[1].id, level=2)
    db.add_all([booking, share]); db.commit()
    try:
        assert work.collect(db, actors[3], {'resources'}, now=now)['count'] == 0
        assert work.collect(db, actors[1], {'resources'}, now=now)['count'] == 0
        share.level = 3; db.commit()
        view = work.collect(db, actors[1], {'resources'}, now=now)
        assert view['count'] == 1 and view['overdue'] == 0 and not view['ready'][0]['late']
        assert view['ready'][0]['href'] == f'/resources/bookings/{booking.id}'
        from app import absence
        share.level = 2
        resource.manager_user_id = actors[0].id
        db.add(Absence(user_id=actors[0].id, substitute_id=actors[1].id, created_by=actors[0].id,
                       starts_on=absence.today(), ends_on=absence.today(), status='confirmed'))
        db.commit()
        proxy = work.collect(db, actors[1], {'resources'}, now=now)
        assert proxy['ready'][0]['scope'] == 'proxy'
        assert len(work.filtered(proxy, 'proxy')['ready']) == 1
        assert not work.filtered(proxy, 'personal')['ready']
    finally:
        db.delete(share); db.delete(booking); db.delete(resource); db.commit()


def test_required_dashboard_work_survives_hidden_tiles_and_waiting_is_collapsed(db, actors):
    import json
    from app.db import CirculationRecipient, get_settings, utcnow
    from test_circulations import make
    from conftest import login, settings
    old = get_settings(db)
    settings(module_applications='0', module_resources='0', module_circulations='1')
    try:
        actors[1].dashboard_json = json.dumps({'hidden': ['tasks', 'circulations']})
        db.commit()
        now = utcnow()
        row, _, _ = make(db, actors, title='EmployeeWorkFocus', due_on=(now+timedelta(days=2)).isoformat())
        blocked, version, recipient = make(db, actors, title='BlockedWorkFocus', mode='approval', sequential=True,
                                           due_on=(now+timedelta(days=1)).isoformat())
        version_data = json.loads(version.content_json)
        version_data['due_on'] = (now-timedelta(days=2)).isoformat()
        version.content_json = json.dumps(version_data)
        recipient.position = 2
        db.add(CirculationRecipient(version_id=version.id, user_id=actors[2].id, name=actors[2].name,
                                   email=actors[2].email, position=1))
        db.commit()
        c = login(actors[1].email, 'passwort-test-123')
        html = c.get('/').text
        focus = html[html.index('id="dash-act-title"'):html.index('id="dash-today-title"')]
        assert 'EmployeeWorkFocus' in focus and f'/umlaeufe/{row.id}' in focus
        assert 'BlockedWorkFocus' not in focus
        tasks = c.get('/tasks').text
        assert '<details class="card mb-3" id="waiting">' in tasks
        assert 'BlockedWorkFocus' in tasks and 'überfällig seit' not in tasks
        assert work.collect(db, actors[1], {'circulations'}, now=now)['overdue'] == 0
    finally:
        db.rollback()
        settings(**{key: old.get(key, '') for key in ('module_applications', 'module_resources', 'module_circulations')})
