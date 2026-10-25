"""One permission-preserving view of work; each source remains responsible for actions."""
from datetime import datetime
from .db import utcnow, to_local

SCOPES = {'all': 'Alle', 'personal': 'Persönlich', 'proxy': 'Vertretung', 'group': 'Gruppenaufgaben'}
SOURCES = {'all': 'Alle Bereiche', 'application': 'Anträge', 'circulation': 'Umläufe', 'resource': 'Ressourcenbuchung', 'native': 'Aufgaben'}


def collect(db, user, modules, *, now=None):
    from . import workflow, circulations, resources
    now = now or utcnow()
    ready, pool, waiting, delegated, history, managed, archive = [], [], [], [], [], [], []
    source_modules = {'application': 'applications', 'circulation': 'circulations', 'resource': 'resources', 'native': 'tasks'}
    sources = {key: label for key, label in SOURCES.items() if key == 'all' or source_modules.get(key) in modules}

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

    if 'tasks' in modules:
        from . import tasks as native
        from .task_models import Task, TaskCheck
        from sqlalchemy import select
        rows = db.scalars(native.visible_query(user)).all()
        visible_ids = {task.id for task in rows}
        unfinished = set(db.scalars(select(TaskCheck.task_id).where(TaskCheck.task_id.in_(visible_ids), TaskCheck.done.is_(False))))
        for task in rows:
            predecessors = native.blockers(db, task)
            blocked = bool(predecessors)
            own = task.assignee_id == user.id
            review = task.status == 'review' and task.creator_id == user.id
            detail = native.STATUSES[task.status] + ' · ' + task.responsible_name
            if task.creator_id == user.id and not own:
                detail += ' · ' + ('noch nicht geöffnet' if not task.seen_at else 'geöffnet')
            if blocked:
                detail += ' · wartet auf Vorgänger'
            item = entry('native', task.title, f'/aufgaben/{task.id}', 'Freigabe prüfen' if review else 'Öffnen', task.due_at,
                         detail=detail, native_id=task.id, status=task.status, priority=task.priority, tags=task.tags,
                         assignee=task.responsible_name, updated_at=task.updated_at, seen_at=task.seen_at,
                         starts_at=task.starts_at, blocked=blocked, version=task.version, may_work=native.may_work(user,task), may_plan=native.may_edit(user,task),
                         status_choices=native.status_choices(user,task,blocked=blocked,unfinished=task.id in unfinished),
                         dependencies=[dict(id=b.id, title=b.title) for b in predecessors if b.id in visible_ids])
            if task.archived_at:
                item['late'] = False
                archive.append(item)
                continue
            if task.status in {'done', 'cancelled'}:
                item['late'] = False
            managed.append(dict(item))
            if task.status in {'done', 'cancelled'}:
                item['late'] = False
                history.append(item)
            if task.creator_id == user.id and not own:
                delegated.append(dict(item))
            if task.status in {'done', 'cancelled'}:
                continue
            if (own and task.status != 'review') or review:
                if blocked or (task.starts_at and task.starts_at > now):
                    item['late'] = False
                    waiting.append(item)
                else:
                    ready.append(item)
            elif own or task.creator_id == user.id or not native.manager(user):
                item['late'] = False
                waiting.append(item)
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
            detail += f' · als Vertretung für {task["recipient_name"]}' if task['proxy'] else ' · persönlich bestätigen'
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
    for items in (ready, pool, waiting, delegated, history, managed, archive): items.sort(key=order)
    return dict(ready=ready, pool=pool, waiting=waiting, delegated=delegated, history=history, managed=managed, archive=archive, sources=sources, count=len(ready), overdue=sum(t['late'] for t in ready),
                group_count=len(pool), waiting_count=len(waiting), now=now, available=bool(modules & {'applications', 'resources', 'circulations', 'tasks'}))


PERSPECTIVES = {'all': 'Jetzt bearbeiten', 'today': 'Heute', 'upcoming': 'Demnächst', 'overdue': 'Überfällig',
                'in_progress': 'In Bearbeitung', 'delegated': 'Delegiert von mir', 'group': 'Für meine Gruppen',
                'proxy': 'Vertretung', 'waiting': 'Wartet auf andere', 'history': 'Abgeschlossen', 'archive': 'Archiv', 'managed': 'Alle Aufgaben verwalten'}


def filtered(view, scope='all', source='all', *, perspective='all', priority='all', status='all', tag='', query='', sort='due', since='', until=''):
    scope = scope if scope in SCOPES else 'all'
    available_sources = view.get('sources', SOURCES)
    source = source if source in available_sources else 'all'
    perspective = perspective if perspective in PERSPECTIVES else 'all'
    today = to_local(view['now']).date()
    result = dict(view, scope=scope, source=source, scopes=SCOPES, sources=available_sources,
                  perspective=perspective, perspectives=PERSPECTIVES, priority=priority, status=status, tag=tag, query=query, sort=sort, since=since, until=until)
    for key in ('ready', 'pool', 'waiting', 'delegated', 'history', 'managed', 'archive'):
        result[key] = [dict(item) for item in view.get(key, []) if
                       (scope == 'all' or item['scope'] == scope) and (source == 'all' or item['source'] == source)
                       and (priority == 'all' or item.get('priority', 'normal') == priority)
                       and (status == 'all' or item.get('status', 'open') == status)
                       and (not tag or tag.casefold() in [t.casefold() for t in item.get('tags', '').split(',')])
                       and (not query or query.casefold() in (item['title'] + ' ' + item['detail']).casefold())
                       and (not since or (item['due'] and to_local(item['due']).date().isoformat() >= since))
                       and (not until or (item['due'] and to_local(item['due']).date().isoformat() <= until))]
        if sort == 'priority': result[key].sort(key=lambda t: {'urgent':0,'high':1,'normal':2,'low':3}.get(t.get('priority','normal'),2))
        elif sort == 'assignee': result[key].sort(key=lambda t: t.get('assignee','').casefold())
        elif sort == 'status': result[key].sort(key=lambda t: t.get('status','open'))
    if perspective == 'group':
        result['ready'], result['pool'], result['waiting'] = result['pool'], [], []
    elif perspective == 'waiting':
        result['ready'], result['pool'], result['waiting'] = result['waiting'], [], []
    elif perspective in {'delegated', 'history', 'managed', 'archive'}:
        result['ready'], result['pool'], result['waiting'] = result[perspective], [], []
    elif perspective != 'all':
        def matches(t):
            due = to_local(t['due']).date() if t['due'] else None
            if perspective == 'today': return due == today
            if perspective == 'upcoming': return bool(due and due > today)
            if perspective == 'overdue': return t['late']
            if perspective == 'in_progress': return t.get('status') == 'in_progress'
            if perspective == 'proxy': return t['scope'] == 'proxy'
            return True
        result['ready'] = [t for t in result['ready'] if matches(t)]
        result['pool'], result['waiting'] = [], []
    result['result_count'] = sum(len(result[k]) for k in ('ready', 'pool', 'waiting'))
    return result
