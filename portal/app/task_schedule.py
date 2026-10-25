"""Bounded RRULE generation and idempotent reminders in the existing worker transaction."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from sqlalchemy import func, select, text
from . import tasks as ts
from .db import LOCAL_TZ, SessionLocal, User, get_settings, to_local, utcnow
from .task_models import Task, TaskOccurrence, TaskReminder, TaskSeries

PRESETS = {'daily': ('Täglich', 'FREQ=DAILY'), 'weekly': ('Wöchentlich', 'FREQ=WEEKLY'),
           'weekdays': ('Montag bis Freitag', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'),
           'monthly': ('Monatlich', 'FREQ=MONTHLY'), 'yearly': ('Jährlich', 'FREQ=YEARLY'),
           'selected_weekdays': ('An ausgewählten Wochentagen', 'FREQ=WEEKLY'),
           'first_workday': ('Erster Werktag im Monat', 'FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1'),
           'last_workday': ('Letzter Werktag im Monat', 'FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1'),
           'first_monday': ('Erster Montag im Monat', 'FREQ=MONTHLY;BYDAY=1MO')}


def recurrence_rule(data, anchor):
    key = str(data.get('repeat', ''))
    if key not in PRESETS:
        raise ts.Invalid('Bitte eine Wiederholung auswählen.')
    raw_count = str(data.get('repeat_count', '')).strip()
    until = str(data.get('repeat_until', '')).strip()
    if raw_count and until:
        raise ts.Invalid('Wählen Sie entweder eine Anzahl oder ein Enddatum.')
    rule = PRESETS[key][1]
    if key == 'selected_weekdays':
        days = str(data.get('repeat_days', '')).split(',')
        if not days or any(d not in {'MO','TU','WE','TH','FR','SA','SU'} for d in days):
            raise ts.Invalid('Wählen Sie mindestens einen Wochentag.')
        rule += ';BYDAY=' + ','.join(dict.fromkeys(days))
    if raw_count:
        if not raw_count.isdigit() or not 1 <= int(raw_count) <= 1000:
            raise ts.Invalid('Eine Serie kann 1 bis 1000 Vorkommen umfassen.')
        rule += ';COUNT=' + str(int(raw_count))
    elif until:
        try:
            day = datetime.fromisoformat(until)
            if day.date() < anchor.date():
                raise ValueError
        except ValueError:
            raise ts.Invalid('Das Serienende muss am oder nach dem ersten Termin liegen.') from None
        rule += ';UNTIL=' + day.replace(hour=23, minute=59, second=59).strftime('%Y%m%dT%H%M%S')
    return rule


def utc_occurrence(local, tz):
    # A spring-forward gap shifts this occurrence forward by the gap. Fall-back uses the first occurrence once.
    aware = local.replace(tzinfo=tz, fold=0)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def save_series(db, user, row, data):
    if not ts.may_edit(user, row):
        from fastapi import HTTPException
        raise HTTPException(403)
    if row.external_email:
        raise ts.Invalid('Externe Aufträge werden einzeln vergeben. Wiederholungen benötigen eine interne verantwortliche Person.')
    if not row.due_at:
        raise ts.Invalid('Geben Sie der Aufgabe zuerst eine Fälligkeit als ersten Serientermin.')
    if row.series_id:
        raise ts.Invalid('Diese Aufgabe gehört bereits zu einer Serie. Stoppen Sie diese bei Bedarf und beginnen Sie mit einer neuen Aufgabe.')
    anchor = to_local(row.due_at).replace(tzinfo=None)
    rule = recurrence_rule(data, anchor)
    # Validate the selected pattern before persisting it.
    if rrulestr(rule, dtstart=anchor).after(anchor - timedelta(seconds=1)) != anchor:
        raise ts.Invalid('Die erste Fälligkeit passt nicht zum Muster. Wählen Sie zunächst einen passenden ersten Termin.')
    template = ts.form_values(row)
    template.pop('version', None)
    series = TaskSeries(creator_id=user.id, rule=rule, anchor_local=anchor.isoformat(), timezone=LOCAL_TZ.key,
                        template_json=json.dumps(template))
    db.add(series); db.flush()
    row.series_id = series.id
    db.add(TaskOccurrence(series_id=series.id, local_key=anchor.isoformat(), task_id=row.id))
    ts.audit(db, row, user, 'series', f'Serie eingerichtet: {PRESETS[str(data.get("repeat"))][0]}. Zeitzone {LOCAL_TZ.key}.')
    return series


def set_reminder(db, user, row, data):
    if not ts.may_work(user, row):
        from fastapi import HTTPException
        raise HTTPException(403)
    if not row.due_at:
        raise ts.Invalid('Erinnerungen benötigen eine Fälligkeit.')
    try:
        offset = int(str(data.get('offset_minutes', '0')))
    except ValueError:
        raise ts.Invalid('Wählen Sie einen gültigen Erinnerungszeitpunkt.') from None
    if offset not in {-10080, -2880, -1440, -60, 0, 60, 1440, 2880, 10080}:
        raise ts.Invalid('Wählen Sie einen angebotenen Erinnerungszeitpunkt.')
    raw = str(data.get('recipient_id', row.assignee_id))
    person = db.get(User, int(raw)) if raw.isdigit() else None
    involved = {row.creator_id, row.assignee_id}
    from .task_models import TaskParticipant
    involved.update(db.scalars(select(TaskParticipant.user_id).where(TaskParticipant.task_id == row.id)))
    if not person or not person.active or person.id not in involved:
        raise ts.Invalid('Erinnerungen können nur an aktive Beteiligte dieser Aufgabe gehen.')
    if person.id != user.id and not ts.may_edit(user, row):
        raise ts.Invalid('Nur Ersteller können Erinnerungen für andere Beteiligte einrichten.')
    old = db.scalar(select(TaskReminder).where(TaskReminder.task_id == row.id, TaskReminder.offset_minutes == offset, TaskReminder.recipient_id == person.id))
    if not old:
        db.add(TaskReminder(task_id=row.id, offset_minutes=offset, recipient_id=person.id))
        ts.audit(db, row, user, 'reminder', f'Erinnerung eingerichtet für {person.name}.')


def tick(*, now=None):
    now = now or utcnow()
    count = 0
    with SessionLocal() as db:
        if get_settings(db).get('module_tasks', '1') != '1':
            return 0
        # A single write lock protects generation and mailqueue deduplication, also across worker restarts.
        db.execute(text('UPDATE task_series SET active=active WHERE active=1'))
        for series in db.scalars(select(TaskSeries).where(TaskSeries.active.is_(True))):
            creator = db.get(User, series.creator_id)
            template = json.loads(series.template_json)
            assignee = db.get(User, int(template['assignee_id']))
            if not creator or not creator.active or not ts.may_create(creator) or not assignee or not assignee.active:
                continue
            tz = ZoneInfo(series.timezone)
            anchor = datetime.fromisoformat(series.anchor_local)
            horizon = (now + timedelta(days=30)).replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)
            rule = rrulestr(series.rule, dtstart=anchor)
            latest = db.scalar(select(func.max(TaskOccurrence.local_key)).where(TaskOccurrence.series_id == series.id))
            cursor = datetime.fromisoformat(latest) if latest else anchor - timedelta(seconds=1)
            # Bounded work per tick; the next tick resumes from the last committed local occurrence.
            pending = []
            for _ in range(200):
                local = rule.after(cursor)
                if local is None or local > horizon:
                    break
                pending.append(local)
                cursor = local
            for local in pending:
                key = local.isoformat()
                if db.get(TaskOccurrence, (series.id, key)):
                    continue
                data = {**template, 'due_date': '', 'due_time': '', 'starts_at': ''}
                starts = None
                if template.get('starts_at'):
                    start = datetime.fromisoformat(template['starts_at'])
                    starts = utc_occurrence(local - (anchor-start), tz)
                row = ts.create(db, creator, data, source_key=f'series:{series.id}:{key}',
                                schedule=dict(due_at=utc_occurrence(local,tz), due_has_time=bool(template.get('due_time')), starts_at=starts))
                row.series_id = series.id
                db.add(TaskOccurrence(series_id=series.id, local_key=key, task_id=row.id))
                ts.audit(db, row, None, 'series', 'Automatisch aus Aufgabenserie angelegt.')
                count += 1
        from . import task_rules
        for due_row in db.scalars(select(Task).where(Task.due_at <= now, Task.status.not_in(['done','cancelled']), Task.archived_at.is_(None))):
            task_rules.emit(db, due_row, 'due', f'due:{due_row.id}:{due_row.due_at.isoformat()}')
        for reminder in db.scalars(select(TaskReminder)):
            row = db.get(Task, reminder.task_id)
            if not row or row.status in {'done', 'cancelled'} or row.archived_at or not row.due_at:
                continue
            # A removed participant must not keep receiving task notifications.
            person = db.get(User, reminder.recipient_id)
            if not person or not person.active or not db.scalar(ts.visible_query(person).where(Task.id == row.id)):
                continue
            event_key = row.due_at.isoformat() + ':' + str(row.assignee_id)
            if reminder.sent_for == event_key or now < row.due_at + timedelta(minutes=reminder.offset_minutes):
                continue
            from . import notify
            from .config import settings
            queued = notify.enqueue(db, person.email, 'TAKT: Eine Aufgabenfrist steht an',
                                    'Bitte prüfen Sie Ihre Aufgabe im Portal:\n' + settings.portal_base_url + f'/aufgaben/{row.id}', 'task_reminder')
            if queued:
                reminder.sent_for = event_key
                ts.audit(db, row, None, 'reminder', 'Fristhinweis in die Benachrichtigungswarteschlange aufgenommen.')
                count += 1
        db.commit()
    if count:
        from .main import _badge_cache
        _badge_cache.clear()
    return count
