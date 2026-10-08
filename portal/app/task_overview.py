"""One permission-preserving view of work; each source remains responsible for actions."""
from datetime import datetime
from .db import utcnow

SCOPES = {'all': 'Alle', 'personal': 'Persönlich', 'proxy': 'Vertretung', 'group': 'Gruppenaufgaben'}
SOURCES = {'all': 'Alle Bereiche', 'application': 'Anträge', 'circulation': 'Umläufe', 'resource': 'Ressourcenbuchung'}


def collect(db, user, modules, *, now=None):
    from . import workflow, circulations, resources
    now = now or utcnow()
    ready, pool, waiting = [], [], []

    resource_scopes = {}

    def resource_scope(resource):
        # shares.access_level includes substitutions; inspect direct authority
        # here only to label existing permitted work, never to expand access.
        from sqlalchemy import or_, select
        from .db import GroupMember, ResourceShare
        if not getattr(resource, 'id', None):
            return 'personal'
        if resource.id in resource_scopes:
            return resource_scopes[resource.id]
        groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        direct = bool(user.is_admin or resource.owner_id == user.id or resource.manager_user_id == user.id)
        if not direct:
            direct = max(db.scalars(select(ResourceShare.level).where(ResourceShare.resource_id == resource.id,
                         or_(ResourceShare.user_id == user.id, ResourceShare.group_id.in_(groups)))), default=0) >= 3
        if not direct and resource.manager_group_id:
            direct = bool(db.scalar(select(GroupMember.user_id).where(GroupMember.group_id == resource.manager_group_id,
                                                                     GroupMember.user_id == user.id)))
        resource_scopes[resource.id] = 'personal' if direct else 'proxy'
        return resource_scopes[resource.id]

    def entry(source, title, href, action, due=None, scope='personal', detail='', icon='fa-list-check', **extra):
        return dict(source=source, source_label=SOURCES[source], title=title, href=href, action=action,
                    due=due, scope=scope, detail=detail, icon=icon, late=bool(due and due < now), **extra)

    if 'applications' in modules:
        for task in workflow.my_tasks(db, user):
            response = task.response
            scope = 'group' if not task.assignee_id else 'personal' if task.assignee_id == user.id else 'proxy'
            detail = f'{response.ref_no} · {response.form.title}'
            if scope == 'group': detail += f' · {task.group.name if task.group else "Gruppenaufgabe"}'
            if scope == 'proxy': detail += f' · Als Vertretung für {task.assignee.name if task.assignee else "Beschäftigte"}'
            item = entry('application', task.name, f'/forms/{response.form_id}/applications/{response.id}#schritt',
                         'Bearbeiten', task.due_at, scope, detail, workflow.STEP_TYPES.get(task.kind, ('', 'fa-list-check'))[1],
                         claim_url=f'/forms/{response.form_id}/applications/{response.id}/task/{task.id}' if scope == 'group' else '')
            (pool if scope == 'group' else ready).append(item)
        for request in workflow.waiting_requests(db, user):
            response = request.response
            item = entry('application', request.title, f'/forms/{response.form_id}/applications/{response.id}#nachforderungen',
                         'Ansehen', request.due_at, detail=f'{response.ref_no} · wartet auf Antragsteller:innen', icon='fa-hourglass-half')
            item['late'] = False
            waiting.append(item)
    if 'circulations' in modules:
        for task in circulations.pending_tasks(db, user):
            detail = task['action'] + f' · {task["done"]} / {task["required"]} Nachweise'
            detail += f' · Als Vertretung für {task["recipient_name"]}' if task['proxy'] else ' · persönlich bestätigen'
            if not task['ready']:
                detail += ' · Umlauf nach Ablehnung gestoppt' if task['stopped'] else ' · Sie sind später an der Reihe – wartet auf vorherige Station'
            item = entry('circulation', task['title'], f'/umlaeufe/{task["row"].id}?recipient={task["recipient_id"]}',
                         'Bearbeiten' if task['ready'] else 'Ansehen', task['due'], 'proxy' if task['proxy'] else 'personal', detail,
                         'fa-user-check' if task['ready'] else 'fa-hourglass-half')
            if not task['ready']: item['late'] = False
            (ready if task['ready'] else waiting).append(item)
    if 'resources' in modules:
        for task in resources.booking_tasks(db, user):
            booking = task['booking']
            ready.append(entry('resource', task['label'] + ': ' + booking.resource.name, task['href'], 'Öffnen', task['due'], scope=resource_scope(booking.resource),
                               detail=f'{booking.ref} · {resources.when_text(booking)} · {booking.name}' + (f' · {task["note"]}' if task['note'] else ''), icon=task['icon']))
    def order(item): return (not item['late'], item['due'] or datetime.max, item['source'], item['title'], item['href'])
    for items in (ready, pool, waiting): items.sort(key=order)
    return dict(ready=ready, pool=pool, waiting=waiting, count=len(ready), overdue=sum(t['late'] for t in ready),
                group_count=len(pool), waiting_count=len(waiting), now=now, available=bool(modules & {'applications', 'resources', 'circulations'}))


def filtered(view, scope='all', source='all'):
    scope = scope if scope in SCOPES else 'all'
    source = source if source in SOURCES else 'all'
    result = dict(view, scope=scope, source=source, scopes=SCOPES, sources=SOURCES)
    for key in ('ready', 'pool', 'waiting'):
        result[key] = [item for item in view[key] if (scope == 'all' or item['scope'] == scope) and (source == 'all' or item['source'] == source)]
    return result
