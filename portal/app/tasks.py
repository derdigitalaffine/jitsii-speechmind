"""Permission-checked native task operations, shared by every view and source adapter."""
import json
import re
from datetime import datetime, time, timezone
from pathlib import Path

from fastapi import HTTPException
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy import or_, select, text

from .db import LOCAL_TZ, Group, GroupMember, User, to_local, utcnow
from .task_models import Task, TaskActivity, TaskCheck, TaskComment, TaskDependency, TaskParticipant

STATUSES = {'open': 'Offen', 'in_progress': 'In Bearbeitung', 'review': 'Wartet auf Freigabe', 'done': 'Erledigt', 'cancelled': 'Storniert'}
PRIORITIES = {'low': 'Niedrig', 'normal': 'Normal', 'high': 'Hoch', 'urgent': 'Dringend'}
TONES = {'open': 'neutral', 'in_progress': 'info', 'review': 'warning', 'done': 'success', 'cancelled': 'neutral'}
TRANSITIONS = {'open': {'in_progress', 'review', 'done', 'cancelled'},
               'in_progress': {'open', 'review', 'done', 'cancelled'},
               'review': {'done', 'in_progress', 'cancelled'}, 'done': {'open'}, 'cancelled': {'open'}}
_MD = MarkdownIt('commonmark', {'html': False, 'linkify': False, 'maxNesting': 20})
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024


class Invalid(ValueError):
    pass


def markdown(value):
    return Markup(_MD.render(value or ''))


def manager(user):
    return user.can('tasks_manage')


def may_create(user):
    return user.can('tasks') or manager(user)


def visible_query(user):
    q = select(Task)
    if not manager(user):
        q = q.where(or_(Task.creator_id == user.id, Task.assignee_id == user.id,
                        Task.id.in_(select(TaskParticipant.task_id).where(TaskParticipant.user_id == user.id))))
    return q


def get(db, user, task_id):
    row = db.scalar(visible_query(user).where(Task.id == task_id))
    if row is None:
        raise HTTPException(404, 'Aufgabe nicht gefunden.')
    return row


def may_edit(user, row):
    return manager(user) or row.creator_id == user.id


def may_work(user, row):
    return may_edit(user, row) or row.assignee_id == user.id


def status_choices(user, row, *, blocked=False, unfinished=False):
    if not may_work(user, row) or row.archived_at:
        return {}
    choices = {}
    for target, label in STATUSES.items():
        if target not in TRANSITIONS[row.status]:
            continue
        if (row.status in {'done', 'cancelled', 'review'} or target == 'cancelled') and not may_edit(user, row):
            continue
        # Review returns need a reason, provided on the task detail page.
        if row.status == 'review' and target == 'in_progress':
            continue
        if target == 'review':
            continue  # Completion chooses review automatically according to the task's rule.
        if blocked and target in {'in_progress', 'done'}:
            continue
        if unfinished and target == 'done':
            continue
        choices[target] = 'Zur Freigabe einreichen' if target == 'done' and row.requires_review and row.status != 'review' else label
    return choices


def check_version(row, data):
    if str(data.get('version', '')) != str(row.version):
        raise Invalid('Die Aufgabe wurde inzwischen geändert. Bitte laden Sie die aktuelle Fassung und übernehmen Sie Ihre Änderung erneut.')


def audit(db, row, user, kind, text):
    row.updated_at = utcnow()
    db.add(TaskActivity(task_id=row.id, actor_id=user.id if user else None,
                        actor_name=user.name if user else 'System', kind=kind, text=text))


def ping(db, row, users, event):
    # Payload intentionally contains no description, comments or source details.
    from . import notify
    from .config import settings
    for uid in set(users) - {None}:
        person = db.get(User, uid)
        if person and person.active:
            notify.enqueue(db, person.email, f'TAKT: {event}',
                           f'{event}\n\nÖffnen Sie die Aufgabe im Portal:\n{settings.portal_base_url}/aufgaben/{row.id}', 'task_update')


def users(db):
    return list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.id)))


def tags(value):
    values = [t.strip().lstrip('#') for t in re.split(r'[,\n]', str(value)) if t.strip()]
    if len(values) > 20 or any(not re.fullmatch(r'[\w-]{1,40}', t, re.UNICODE) for t in values):
        raise Invalid('Bitte bis zu 20 Tags verwenden: Buchstaben, Zahlen, Bindestrich oder Unterstrich, jeweils höchstens 40 Zeichen.')
    return ','.join(dict.fromkeys(values))


def local_date(value, *, date_only=False):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is not None:
            raise ValueError
        if date_only:
            parsed = datetime.combine(parsed.date(), time(23, 59, 59))
        aware = parsed.replace(tzinfo=LOCAL_TZ)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(LOCAL_TZ).replace(tzinfo=None) != parsed:
            raise ValueError
        # Ambiguous fall-back times require an explicit choice instead of guessing.
        if not date_only and parsed.replace(tzinfo=LOCAL_TZ, fold=0).utcoffset() != parsed.replace(tzinfo=LOCAL_TZ, fold=1).utcoffset():
            raise Invalid('Diese Uhrzeit kommt beim Zeitwechsel zweimal vor. Bitte wählen Sie eine eindeutige Uhrzeit.')
        return utc.replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise Invalid('Bitte ein gültiges Datum und eine im Portal eindeutige Uhrzeit eingeben.') from None


def values(db, data, user):
    title = str(data.get('title', '')).strip()
    if not title or len(title) > 300:
        raise Invalid('Geben Sie einen Aufgabentitel mit höchstens 300 Zeichen ein.')
    description = str(data.get('description', '')).strip()
    if len(description) > 30000:
        raise Invalid('Die Beschreibung darf höchstens 30.000 Zeichen enthalten.')
    priority = str(data.get('priority', 'normal'))
    if priority not in PRIORITIES:
        raise Invalid('Bitte eine gültige Priorität auswählen.')
    raw_id = str(data.get('assignee_id', user.id))
    assignee = db.get(User, int(raw_id)) if raw_id.isdigit() else None
    external = str(data.get('external', '')) in {'1', 'on', 'true'}
    external_name = str(data.get('external_name', '')).strip() if external else ''
    external_email = str(data.get('external_email', '')).strip().lower() if external else ''
    if external and (not external_name or len(external_name) > 255 or len(external_email) > 255 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', external_email)):
        raise Invalid('Geben Sie einen Namen und eine gültige E-Mail-Adresse für die externe Person ein.')
    if not external and (assignee is None or not assignee.active):
        raise Invalid('Wählen Sie genau eine aktive verantwortliche Person aus.')
    group_id = str(data.get('group_id', ''))
    group = db.get(Group, int(group_id)) if group_id.isdigit() else None
    if group_id and group is None:
        raise Invalid('Bitte eine gültige Gruppe auswählen.')
    if group and not manager(user) and not db.get(GroupMember, (group.id, user.id)):
        raise Invalid('Sie können nur eine Ihrer eigenen Gruppen als Kontext wählen.')
    day = str(data.get('due_date', '')).strip()
    clock = str(data.get('due_time', '')).strip()
    if clock and not day:
        raise Invalid('Zur Uhrzeit fehlt noch das Fälligkeitsdatum.')
    if clock and not re.fullmatch(r'\d{2}:\d{2}', clock):
        raise Invalid('Bitte die Uhrzeit im Format HH:MM angeben.')
    due = local_date(day + ('T' + clock if clock else ''), date_only=not clock) if day else None
    starts = local_date(str(data.get('starts_at', '')).strip())
    if starts and due and starts > due:
        raise Invalid('Der Start muss vor der Fälligkeit liegen.')
    return dict(title=title, description=description, assignee_id=None if external else assignee.id, external_name=external_name, external_email=external_email, group_id=group.id if group else None,
                priority=priority, due_at=due, due_has_time=bool(clock), starts_at=starts,
                tags=tags(data.get('tags', '')), requires_review=str(data.get('requires_review', '')) in {'1', 'on', 'true'})


def create(db, user, data, *, source_type='', source_id='', source_key=None, schedule=None):
    if not may_create(user):
        raise HTTPException(403, 'Für neue Aufgaben fehlt die Berechtigung „Aufgaben erstellen“.')
    clean = values(db, data, user)
    if schedule is not None:
        clean.update(due_at=schedule['due_at'], due_has_time=schedule['due_has_time'], starts_at=schedule.get('starts_at'))
    if source_key:
        db.execute(text('UPDATE tasks SET version=version WHERE id=-1'))
        old = db.scalar(select(Task).where(Task.source_key == source_key))
        if old:
            return get(db, user, old.id)
    row = Task(creator_id=user.id, source_type=source_type, source_id=str(source_id), source_key=source_key, **clean)
    db.add(row)
    db.flush()
    audit(db, row, user, 'created', 'Aufgabe angelegt.')
    if row.assignee_id != user.id:
        ping(db, row, [row.assignee_id], 'Eine Aufgabe wurde Ihnen zugewiesen')
    from . import task_rules
    task_rules.emit(db, row, 'created', f'created:{row.id}')
    return row


def update(db, user, row, data):
    if not may_edit(user, row):
        raise HTTPException(403, 'Nur Ersteller und Aufgabenverwaltung können die Planung ändern.')
    check_version(row, data)
    clean = values(db, data, user)
    if row.status == 'review' and clean['requires_review'] != row.requires_review:
        raise Invalid('Während einer Freigabe kann die Abschlussregel nicht geändert werden.')
    labels = {'title': 'Titel', 'description': 'Beschreibung', 'assignee_id': 'Verantwortlichkeit', 'group_id': 'Gruppe',
              'external_name': 'Externe Person', 'external_email': 'Externe E-Mail', 'priority': 'Priorität', 'due_at': 'Frist', 'due_has_time': 'Fristuhrzeit', 'starts_at': 'Start', 'tags': 'Tags', 'requires_review': 'Freigabe erforderlich'}
    old_assignee = row.assignee_id
    old_external = row.external_email
    assignment_names = {p.id: p.name for p in users(db)}
    for key, value in clean.items():
        old = getattr(row, key)
        if old != value:
            if key == 'assignee_id':
                before = assignment_names.get(old, row.external_name)
                after = assignment_names.get(value, clean['external_name'])
                row.seen_at = None
            elif key == 'priority':
                before, after = PRIORITIES[old], PRIORITIES[value]
            elif isinstance(old, datetime) or isinstance(value, datetime):
                before = to_local(old).strftime('%d.%m.%Y %H:%M') if old else '–'
                after = to_local(value).strftime('%d.%m.%Y %H:%M') if value else '–'
            else:
                before, after = str(old), str(value)
            audit(db, row, user, key, f'{labels[key]} geändert.' if key == 'description' else f'{labels[key]}: {before} → {after}')
            setattr(row, key, value)
    if old_assignee != row.assignee_id or old_external != row.external_email:
        from .task_models import TaskExternal
        link = db.get(TaskExternal, row.id)
        if link:
            link.revoked_at = utcnow()
        if old_assignee != row.assignee_id:
            ping(db, row, [row.assignee_id], 'Eine Aufgabe wurde Ihnen zugewiesen')
            db.flush()
            from . import task_rules
            task_rules.emit(db, row, 'assigned', f'assigned:{row.id}:{row.version}')


def blockers(db, row):
    return list(db.scalars(select(Task).join(TaskDependency, TaskDependency.blocker_id == Task.id)
                           .where(TaskDependency.task_id == row.id, Task.status != 'done')))


def transition(db, user, row, target, reason=''):
    if not may_work(user, row):
        raise HTTPException(403, 'Sie können den Arbeitsstatus dieser Aufgabe nicht ändern.')
    if target not in STATUSES:
        raise Invalid('Bitte einen gültigen Status wählen.')
    if row.archived_at:
        raise Invalid('Die Aufgabe ist archiviert. Stellen Sie sie zuerst wieder her.')
    if target == row.status:
        return
    if target == 'done' and row.status != 'review' and row.requires_review:
        target = 'review'
    if target not in TRANSITIONS[row.status]:
        raise Invalid('Dieser Statuswechsel ist im aktuellen Zustand nicht möglich.')
    if row.status in {'done', 'cancelled', 'review'} or target == 'cancelled':
        if not may_edit(user, row):
            raise HTTPException(403, 'Nur Ersteller und Aufgabenverwaltung können freigeben, zurückgeben, stornieren oder wieder öffnen.')
    if row.status == 'review' and target == 'in_progress':
        if not reason.strip():
            raise Invalid('Bitte begründen Sie die Rückgabe mit einem Kommentar.')
        comment(db, user, row, reason)
    if target in {'in_progress', 'review', 'done'} and blockers(db, row):
        raise Invalid('Diese Aufgabe wartet noch auf eine andere Aufgabe. Schließen Sie zuerst die Vorgänger ab.')
    if target in {'done', 'review'} and db.scalar(select(TaskCheck.id).where(TaskCheck.task_id == row.id, TaskCheck.done.is_(False))):
        raise Invalid('In der Checkliste sind noch Punkte offen.')
    old = row.status
    row.status = target
    row.completed_at = utcnow() if target == 'done' else None
    row.completed_by = user.id if target == 'done' else None
    audit(db, row, user, 'status', f'{STATUSES[old]} → {STATUSES[target]}')
    ping(db, row, {row.creator_id, row.assignee_id} - {user.id}, f'Aufgabenstatus: {STATUSES[target]}')
    db.flush()
    from . import task_rules
    event_key = f'status:{row.id}:{row.version}'
    task_rules.emit(db, row, 'status_changed', event_key)
    if old == 'review':
        task_rules.emit(db, row, 'review_approved' if target == 'done' else 'review_returned', event_key)
    if target == 'done':
        task_rules.emit(db, row, 'completed', event_key)
        task_rules.emit(db, row, 'predecessor_done', event_key)
        for child in db.scalars(select(Task).join(TaskDependency, TaskDependency.task_id == Task.id).where(TaskDependency.blocker_id == row.id)):
            # Flush the completed state before evaluating the remaining blockers.
            db.flush()
            if not blockers(db, child):
                audit(db, child, user, 'unblocked', 'Alle Vorgänger sind erledigt. Die Aufgabe ist startbereit.')


def resolve_mentions(db, row, body):
    people = {u.id: u for u in users(db) if u.id in {row.creator_id, row.assignee_id} or db.get(TaskParticipant, (row.id, u.id))}
    mentioned = {int(v) for v in re.findall(r'@\[(\d+)\]', body)}
    if not mentioned <= people.keys():
        raise Invalid('Erwähnungen sind nur für aktive Beteiligte dieser Aufgabe möglich. Fügen Sie die Person zuerst als Mitwirkende hinzu.')
    for match in re.finditer(r'(?<![\w@])@(?:"([^"\n]+)"|([\w.\-]+))', body):
        name = (match[1] or match[2]).casefold()
        hits = [p.id for p in people.values() if p.name.casefold() == name or p.name.casefold().split()[0] == name or (p.name + ' <' + p.email + '>').casefold() == name]
        if len(hits) != 1:
            raise Invalid('Diese Erwähnung ist nicht eindeutig. Wählen Sie eine beteiligte Person unter „Person erwähnen“.')
        mentioned.add(hits[0])
    return mentioned


def comment(db, user, row, body):
    body = str(body).strip()
    if not body or len(body) > 10000:
        raise Invalid('Bitte einen Kommentar mit 1 bis 10.000 Zeichen eingeben.')
    mentioned = resolve_mentions(db, row, body)
    item = TaskComment(task_id=row.id, author_id=user.id, body=body)
    db.add(item)
    audit(db, row, user, 'comment', 'Kommentar hinzugefügt.')
    ping(db, row, mentioned - {user.id}, 'Sie wurden in einer Aufgabe erwähnt')
    return item


def add_dependency(db, user, row, blocker_id):
    if not may_edit(user, row):
        raise HTTPException(403)
    other = get(db, user, blocker_id)
    if other.archived_at or row.id == other.id:
        raise Invalid('Eine Aufgabe kann nicht auf sich selbst oder auf eine archivierte Aufgabe warten.')
    if row.status in {'done', 'cancelled'}:
        raise Invalid('Öffnen Sie die Aufgabe vor einer neuen Abhängigkeit wieder.')
    # Serialize graph modifications before reading reachability (SQLite worker and HTTP requests).
    from sqlalchemy import text
    db.execute(text('UPDATE tasks SET version=version WHERE id=:id'), {'id': row.id})
    edges = list(db.execute(select(TaskDependency.task_id, TaskDependency.blocker_id)))
    graph = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
    seen, pending = set(), [other.id]
    while pending:
        current = pending.pop()
        if current == row.id:
            raise Invalid('Diese Abhängigkeit würde einen Kreis erzeugen.')
        if current not in seen:
            seen.add(current)
            pending.extend(graph.get(current, []))
    if not db.get(TaskDependency, (row.id, other.id)):
        db.add(TaskDependency(task_id=row.id, blocker_id=other.id))
        audit(db, row, user, 'dependency', 'Vorgänger verknüpft.')


def attachment_path(row):
    from .config import settings
    # Storage key is generated internally, never a user-supplied filename.
    if not re.fullmatch(r'[a-f0-9]{64}', row.storage_key):
        raise HTTPException(404, 'Datei nicht verfügbar.')
    return settings.data_dir / 'task-files' / str(row.task_id) / row.storage_key


def filename(value):
    value = re.split(r'[/\\]', str(value))[-1]
    value = ''.join(c for c in value if c.isprintable() and c not in '"<>:|?*').strip(' .')[:180]
    return value or 'Datei'


def safe_mime(content):
    # Only raster images whose actual bytes can be decoded get an inline preview.
    from PIL import Image
    import io
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            return {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}.get(image.format, 'application/octet-stream')
    except Exception:
        return 'application/octet-stream'


def form_values(row):
    due = to_local(row.due_at)
    return dict(title=row.title, description=row.description, assignee_id=str(row.assignee_id or ''), external='1' if row.external_email else '', external_name=row.external_name, external_email=row.external_email, group_id=str(row.group_id or ''),
                priority=row.priority, due_date=due.strftime('%Y-%m-%d') if due else '',
                due_time=due.strftime('%H:%M') if due and row.due_has_time else '',
                starts_at=to_local(row.starts_at).strftime('%Y-%m-%dT%H:%M') if row.starts_at else '',
                tags=row.tags, requires_review='1' if row.requires_review else '', version=str(row.version))
