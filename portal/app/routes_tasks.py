"""Native task UI; the common workplace stays at /tasks."""
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from . import tasks as ts, task_capture
from .db import DmsFile, DmsRecord, Group, GroupMember, User, utcnow
from .task_models import Task, TaskActivity, TaskAttachment, TaskCheck, TaskComment, TaskDependency, TaskParticipant
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render


def module_on():
    if 'tasks' not in enabled_modules():
        raise HTTPException(404, 'Aufgaben sind auf diesem Server nicht eingeschaltet.')


def back_path(value):
    # Only the common workplace's query string is accepted as a return destination.
    value = str(value or '')
    return value if value == '/tasks' or (value.startswith('/tasks?') and '\\' not in value and len(value) < 2000 and not any(ord(c) < 32 for c in value)) else '/tasks'


def groups(db, user):
    q = select(Group).order_by(Group.name)
    if not ts.manager(user):
        q = q.where(Group.id.in_(select(GroupMember.group_id).where(GroupMember.user_id == user.id)))
    return list(db.scalars(q))


def editor(request, db, user, data, error='', notices=(), *, row=None, back='/tasks', original=''):
    response = render(request, 'task_editor.html', user, data=data, error=error, notices=notices, task=row,
                  people=ts.users(db), groups=groups(db, user), statuses=ts.STATUSES, priorities=ts.PRIORITIES,
                  back=back_path(back), original=original)
    response.status_code = 422 if error else 200
    return response


@app.get('/aufgaben/neu')
def new_task(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    return editor(request, db, user, dict(assignee_id=str(user.id), priority='normal'), back=request.query_params.get('back'))


@app.post('/aufgaben/vorschau', dependencies=[Depends(check_csrf)])
async def capture_preview(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    form = await request.form()
    raw = str(form.get('capture', ''))[:2000]
    data, notices, _ = task_capture.parse(raw, ts.users(db), user.id)
    request.state.task_capture = dict(data=data, notices=notices, original=raw)
    from .routes_workflow import tasks_page
    return tasks_page(request, user, db)


@app.post('/aufgaben/neu', dependencies=[Depends(check_csrf)])
async def create_task(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    form = await request.form()
    # Upload objects stay out of the values re-rendered after a validation error.
    data = {key: value for key, value in form.items() if not hasattr(value, 'filename')}
    back = back_path(data.get('back'))
    paths = []
    try:
        checks = ts.initial_checklist(data.get('checklist', ''))
        row = ts.create(db, user, data)
        ts.add_initial_checks(db, user, row, checks)
        await ts.attach_files(db, user, row, form.getlist('files'), paths)
        db.commit()
    except (ts.Invalid, StaleDataError, OSError) as exc:
        db.rollback()
        ts.discard_files(paths)
        error = str(exc) if isinstance(exc, ts.Invalid) else (
            'Die Dateien konnten nicht gespeichert werden. Die Aufgabe wurde noch nicht angelegt.' if isinstance(exc, OSError)
            else 'Die Aufgabe konnte noch nicht angelegt werden. Bitte prüfen Sie Ihre Eingabe.')
        if any(getattr(upload, 'filename', '') for upload in form.getlist('files')) and 'erneut' not in error:
            error += ' Bitte wählen Sie die Dateien erneut aus.'
        if data.get('inline_capture') == '1':
            request.state.task_capture = dict(data=data, notices=[], original=data.get('original', ''), error=error)
            from .routes_workflow import tasks_page
            return tasks_page(request, user, db)
        return editor(request, db, user, data, error, back=back, original=data.get('original', ''))
    except Exception:
        db.rollback()
        ts.discard_files(paths)
        raise
    from .main import _badge_cache
    _badge_cache.clear()
    flash(request, f'Aufgabe „{row.title}“ angelegt.')
    return redirect(back)


def detail(request, db, user, row, *, error='', data=None):
    from .task_models import TaskExternal
    external = db.get(TaskExternal, row.id)
    members = list(db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == row.id)))
    people = ts.users(db)
    eligible = [u for u in people if u.id not in {row.creator_id, row.assignee_id, *(p.user_id for p in members)}]
    checks = list(db.scalars(select(TaskCheck).where(TaskCheck.task_id == row.id).order_by(TaskCheck.position, TaskCheck.id)))
    blockers = ts.blockers(db, row)
    visible_blockers = [b for b in blockers if db.scalar(ts.visible_query(user).where(Task.id == b.id))]
    dependency_ids = set(db.scalars(select(TaskDependency.blocker_id).where(TaskDependency.task_id == row.id)))
    dependencies = list(db.scalars(ts.visible_query(user).where(Task.id.in_(dependency_ids))))
    from . import task_schedule
    from .task_models import TaskSeries, TaskReminder
    series = db.get(TaskSeries, row.series_id) if row.series_id else None
    reminders = list(db.scalars(select(TaskReminder).where(TaskReminder.task_id == row.id)))
    source = None
    if row.source_type:
        from . import task_sources
        source = task_sources.source_info(db, user, row.source_type, row.source_id)
    from .main import stash_get
    external_link = stash_get(request, f'task-external-{row.id}', pop=True)
    response = render(request, 'task_detail.html', user, task=row, error=error, posted=data or {}, back=back_path(request.query_params.get('back') or (data or {}).get('back')),
                  ts=ts, external=external, external_link=external_link, series=series, reminders=reminders, repeat_presets=task_schedule.PRESETS, checks=checks, blockers=blockers, visible_blockers=visible_blockers, dependencies=dependencies,
                  candidates=list(db.scalars(ts.visible_query(user).where(Task.id != row.id, Task.status.not_in(['done', 'cancelled']), Task.archived_at.is_(None)).order_by(Task.title).limit(100))),
                  people=people, eligible=eligible, participants=members, source=source,
                  comments=list(db.scalars(select(TaskComment).where(TaskComment.task_id == row.id).order_by(TaskComment.created_at, TaskComment.id))),
                  files=list(db.scalars(select(TaskAttachment).where(TaskAttachment.task_id == row.id, TaskAttachment.removed_at.is_(None)).order_by(TaskAttachment.id))),
                  activity=list(db.scalars(select(TaskActivity).where(TaskActivity.task_id == row.id).order_by(TaskActivity.created_at.desc(), TaskActivity.id.desc()).limit(100))),
                  )
    response.status_code = 422 if error else 200
    return response


@app.get('/aufgaben/{task_id:int}')
def task_detail(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    if row.assignee_id == user.id and not row.seen_at:
        row.seen_at = utcnow()
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            row = ts.get(db, user, task_id)
    return detail(request, db, user, row)


@app.get('/aufgaben/{task_id:int}/bearbeiten')
def task_edit(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    if not ts.may_edit(user, row):
        raise HTTPException(403)
    return editor(request, db, user, ts.form_values(row), row=row, back=request.query_params.get('back'))


@app.post('/aufgaben/{task_id:int}/bearbeiten', dependencies=[Depends(check_csrf)])
async def task_edit_save(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    data = dict(await request.form())
    try:
        ts.update(db, user, row, data)
        db.commit()
    except (ts.Invalid, StaleDataError) as exc:
        db.rollback()
        return editor(request, db, user, data, str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert. Bitte neu laden.', row=row, back=data.get('back'))
    from .main import _badge_cache
    _badge_cache.clear()
    flash(request, 'Änderungen gespeichert.')
    return redirect(f'/aufgaben/{row.id}?' + urlencode({'back': back_path(data.get('back'))}))


@app.post('/aufgaben/{task_id:int}/aktion', dependencies=[Depends(check_csrf)])
async def task_action(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    form = await request.form()
    data = dict(form)
    data['repeat_days'] = ','.join(str(d) for d in form.getlist('repeat_days'))
    action = str(data.get('action', ''))
    external_link_value = None
    try:
        ts.check_version(row, data)
        if action == 'status':
            ts.transition(db, user, row, str(data.get('status', '')), str(data.get('comment', '')))
        elif action == 'comment':
            ts.comment(db, user, row, data.get('comment', ''))
        elif action in {'comment_edit', 'comment_remove'}:
            item = db.get(TaskComment, int(data.get('comment_id', 0)))
            if not item or item.task_id != row.id:
                raise HTTPException(404)
            if item.author_id != user.id and not ts.manager(user):
                raise HTTPException(403)
            if action == 'comment_remove':
                item.removed_at = utcnow()
                ts.audit(db, row, user, 'comment_removed', 'Kommentar entfernt; das Ereignis bleibt im Verlauf erhalten.')
            else:
                body = str(data.get('comment', '')).strip()
                if not body or len(body) > 10000:
                    raise ts.Invalid('Bitte einen Kommentar mit 1 bis 10.000 Zeichen eingeben.')
                if item.removed_at:
                    raise ts.Invalid('Dieser Kommentar wurde bereits entfernt.')
                # Validate mention boundaries with the same policy as new comments.
                mentioned = ts.resolve_mentions(db, row, body)
                ts.ping(db, row, mentioned - {user.id}, 'Sie wurden in einer Aufgabe erwähnt')
                item.body, item.edited_at = body, utcnow()
                ts.audit(db, row, user, 'comment_edited', 'Kommentar bearbeitet.')
        elif action in {'check_add', 'check_toggle', 'check_up', 'check_down', 'check_remove'}:
            if row.status in {'done', 'cancelled'} or row.archived_at:
                raise ts.Invalid('Die Aufgabe ist abgeschlossen. Öffnen Sie sie vor einer Checklistenänderung wieder.')
            if action == 'check_add':
                title = str(data.get('check_title', '')).strip()
                if not title or len(title) > 500:
                    raise ts.Invalid('Geben Sie einen Checklistenpunkt mit höchstens 500 Zeichen ein.')
                pos = db.scalar(select(func.max(TaskCheck.position)).where(TaskCheck.task_id == row.id)) or 0
                db.add(TaskCheck(task_id=row.id, title=title, position=pos + 1))
                ts.audit(db, row, user, 'check', 'Checklistenpunkt hinzugefügt.')
            else:
                item = db.get(TaskCheck, int(data.get('check_id', 0)))
                if not item or item.task_id != row.id:
                    raise HTTPException(404)
                if action == 'check_toggle':
                    item.done = not item.done
                elif action == 'check_remove':
                    db.delete(item)
                else:
                    checks = list(db.scalars(select(TaskCheck).where(TaskCheck.task_id == row.id).order_by(TaskCheck.position, TaskCheck.id)))
                    index = checks.index(item)
                    next_index = index + (-1 if action == 'check_up' else 1)
                    if 0 <= next_index < len(checks):
                        checks[index], checks[next_index] = checks[next_index], checks[index]
                        for i, check in enumerate(checks):
                            check.position = i
                ts.audit(db, row, user, 'check', 'Checkliste aktualisiert.')
        elif action in {'participant_add', 'participant_remove'}:
            if not ts.may_edit(user, row):
                raise HTTPException(403)
            person = db.get(User, int(data.get('user_id', 0)))
            if not person or not person.active:
                raise ts.Invalid('Wählen Sie eine aktive Person.')
            member = db.get(TaskParticipant, (row.id, person.id))
            if action == 'participant_add' and not member:
                db.add(TaskParticipant(task_id=row.id, user_id=person.id))
                ts.audit(db, row, user, 'participant', f'{person.name} wirkt mit.')
            elif member:
                db.delete(member)
                ts.audit(db, row, user, 'participant', f'Mitwirkung von {person.name} beendet.')
        elif action == 'external_link':
            from . import task_external
            from .config import settings
            raw = task_external.issue(db, user, row, days=int(data.get('link_days', 14)), comments=data.get('external_comments') == '1')
            # Raw capabilities use the existing server-side secret stash, never a signed session cookie.
            db.flush()
            external_link_value = settings.portal_base_url + '/aufgaben/gast/' + raw
        elif action == 'external_revoke':
            from .task_models import TaskExternal
            if not ts.may_edit(user, row):
                raise HTTPException(403)
            link = db.get(TaskExternal, row.id)
            if link:
                link.revoked_at = utcnow()
                ts.audit(db, row, user, 'external_link', 'Persönlicher Aufgabenlink widerrufen.')
        elif action in {'share_file', 'share_comment'}:
            if not ts.may_edit(user, row) or not row.external_email:
                raise HTTPException(403)
            model = TaskAttachment if action == 'share_file' else TaskComment
            item = db.get(model, int(data.get('item_id', 0)))
            if not item or item.task_id != row.id:
                raise HTTPException(404)
            if action == 'share_file' and item.is_reference:
                raise ts.Invalid('Interne DMS-Referenzen können nicht extern freigegeben werden.')
            item.external_visible = not item.external_visible
            ts.audit(db, row, user, 'external_share', 'Externe Inhaltsfreigabe geändert.')
        elif action == 'series_save':
            from . import task_schedule
            task_schedule.save_series(db, user, row, data)
        elif action == 'series_stop':
            if not ts.may_edit(user, row):
                raise HTTPException(403)
            from .task_models import TaskSeries
            series = db.get(TaskSeries, row.series_id) if row.series_id else None
            if series:
                series.active = False
                ts.audit(db, row, user, 'series', 'Serie gestoppt. Bestehende Vorkommen bleiben erhalten.')
        elif action == 'reminder_add':
            from . import task_schedule
            task_schedule.set_reminder(db, user, row, data)
        elif action == 'reminder_remove':
            from .task_models import TaskReminder
            reminder = db.get(TaskReminder, int(data.get('reminder_id', 0)))
            if not reminder or reminder.task_id != row.id:
                raise HTTPException(404)
            if not ts.may_edit(user, row) and reminder.recipient_id != user.id:
                raise HTTPException(403)
            db.delete(reminder)
            ts.audit(db, row, user, 'reminder', 'Erinnerung entfernt.')
        elif action in {'archive', 'restore'}:
            if not ts.may_edit(user, row):
                raise HTTPException(403)
            if action == 'archive' and row.status not in {'done', 'cancelled'}:
                raise ts.Invalid('Erledigen oder stornieren Sie die Aufgabe vor dem Archivieren.')
            row.archived_at = utcnow() if action == 'archive' else None
            ts.audit(db, row, user, 'archive', 'Archiviert.' if row.archived_at else 'Aus dem Archiv wiederhergestellt.')
        elif action == 'dependency_add':
            ts.add_dependency(db, user, row, int(data.get('blocker_id', 0)))
        elif action == 'dependency_remove':
            if not ts.may_edit(user, row):
                raise HTTPException(403)
            edge = db.get(TaskDependency, (row.id, int(data.get('blocker_id', 0))))
            if edge:
                db.delete(edge)
                ts.audit(db, row, user, 'dependency', 'Abhängigkeit entfernt.')
        else:
            raise ts.Invalid('Diese Aktion ist nicht verfügbar.')
        db.commit()
        if external_link_value:
            from .main import stash_put
            stash_put(request, f'task-external-{row.id}', external_link_value)
    except (ts.Invalid, StaleDataError, ValueError) as exc:
        db.rollback()
        return detail(request, db, user, ts.get(db, user, task_id), error=str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert oder die Auswahl ist ungültig. Bitte prüfen Sie die aktuelle Fassung.', data=data)
    from .main import _badge_cache
    _badge_cache.clear()
    flash(request, 'Gespeichert.')
    if data.get('return_to_workplace') == '1':
        return redirect(back_path(data.get('back')))
    return redirect(f'/aufgaben/{row.id}?' + urlencode({'back': back_path(data.get('back'))}))


@app.post('/aufgaben/{task_id:int}/dateien', dependencies=[Depends(check_csrf)])
async def task_upload(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    data = await request.form()
    created_paths = []
    try:
        ts.check_version(row, data)
        await ts.attach_files(db, user, row, data.getlist('files'), created_paths, required=True)
        db.commit()
    except (ts.Invalid, StaleDataError, OSError) as exc:
        db.rollback()
        ts.discard_files(created_paths)
        error = str(exc) if isinstance(exc, ts.Invalid) else 'Die Dateien konnten nicht gespeichert werden. Bitte wählen Sie sie erneut aus.'
        return detail(request, db, user, ts.get(db, user, task_id), error=error)
    except Exception:
        db.rollback()
        ts.discard_files(created_paths)
        raise
    flash(request, 'Dateien angehängt.')
    return redirect(f'/aufgaben/{row.id}')


@app.post('/aufgaben/{task_id:int}/dms-datei', dependencies=[Depends(check_csrf)])
async def link_dms(request: Request, task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    data = dict(await request.form())
    try:
        ts.check_version(row, data)
        if 'dms' not in enabled_modules():
            raise HTTPException(404)
        from . import dms
        raw = str(data.get('dms_file_id', ''))
        file = db.get(DmsFile, int(raw)) if raw.isdigit() else None
        record = db.get(DmsRecord, file.record_id) if file else None
        if not record or record.archived_at or not dms.record_level(db, user, record):
            raise ts.Invalid('Diese DMS-Datei ist für Sie nicht verfügbar. Prüfen Sie die Datei-ID und Ihre Berechtigung.')
        db.add(TaskAttachment(task_id=row.id, name='DMS-Dateiverknüpfung', dms_file_id=file.id, is_reference=True,
                              size=0, uploaded_by=user.id))
        ts.audit(db, row, user, 'attachment', 'DMS-Dateireferenz hinzugefügt. Der Zugriff wird beim Öffnen erneut geprüft.')
        db.commit()
    except (ts.Invalid, StaleDataError) as exc:
        db.rollback()
        return detail(request, db, user, ts.get(db, user, task_id), error=str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert.', data=data)
    return redirect(f'/aufgaben/{row.id}')


@app.get('/aufgaben/{task_id:int}/dateien/{file_id:int}')
def download_task_file(task_id: int, file_id: int, preview: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    ts.get(db, user, task_id)
    item = db.get(TaskAttachment, file_id)
    if not item or item.task_id != task_id or item.removed_at:
        raise HTTPException(404)
    if item.is_reference:
        from . import dms
        if 'dms' not in enabled_modules():
            raise HTTPException(404)
        file = db.get(DmsFile, item.dms_file_id) if item.dms_file_id else None
        record = db.get(DmsRecord, file.record_id) if file else None
        if not record or record.archived_at or not dms.record_level(db, user, record):
            raise HTTPException(404, 'Die Quelle ist nicht mehr verfügbar oder Sie haben keinen Zugriff.')
        # Delegate to the existing endpoint, including its current authorization checks.
        return redirect(f'/dms/r/{record.id}/files/{file.id}')
    path = ts.attachment_path(item)
    if not path.is_file():
        raise HTTPException(404, 'Datei nicht mehr verfügbar.')
    inline = preview and item.mime in {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
    return FileResponse(path, filename=item.name, media_type=item.mime if inline else 'application/octet-stream',
                        content_disposition_type='inline' if inline else 'attachment',
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox", 'Cache-Control': 'no-store'})


@app.post('/aufgaben/{task_id:int}/dateien/{file_id:int}/entfernen', dependencies=[Depends(check_csrf)])
async def remove_task_file(request: Request, task_id: int, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    row = ts.get(db, user, task_id)
    item = db.get(TaskAttachment, file_id)
    if not item or item.task_id != row.id or item.removed_at:
        raise HTTPException(404)
    if not ts.may_edit(user, row) and item.uploaded_by != user.id:
        raise HTTPException(403)
    data = await request.form()
    try:
        ts.check_version(row, data)
        item.removed_at = utcnow()
        ts.audit(db, row, user, 'attachment', f'Anhang entfernt: {item.name}')
        db.commit()
    except (ts.Invalid, StaleDataError) as exc:
        db.rollback()
        return detail(request, db, user, ts.get(db, user, task_id), error=str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert.')
    if not item.is_reference:
        ts.attachment_path(item).unlink(missing_ok=True)
    return redirect(f'/aufgaben/{row.id}')


@app.get('/aufgaben/quelle/{kind}/{source_id:int}')
def source_task_form(request: Request, kind: str, source_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    from . import task_sources
    source = task_sources.source_info(db, user, kind, source_id, required=True)
    return render(request, 'task_source.html', user, source=source, kind=kind, source_id=source_id,
                  people=ts.users(db), data={'assignee_id': str(user.id)}, error='')


@app.post('/aufgaben/quelle/{kind}/{source_id:int}', dependencies=[Depends(check_csrf)])
async def source_task_save(request: Request, kind: str, source_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    from . import task_sources
    source = task_sources.source_info(db, user, kind, source_id, required=True)
    data = dict(await request.form())
    try:
        row = task_sources.create_from_source(db, user, kind, source_id, data)
        db.commit()
    except ts.Invalid as exc:
        db.rollback()
        response = render(request, 'task_source.html', user, source=source, kind=kind, source_id=source_id, people=ts.users(db), data=data, error=str(exc))
        response.status_code = 422
        return response
    from .main import _badge_cache
    _badge_cache.clear()
    flash(request, 'Aufgabe mit Rücklink zur Quelle angelegt.')
    return redirect(f'/aufgaben/{row.id}')


@app.get('/aufgaben/aufzeichnung/{rec_id:int}')
def recording_import(request: Request, rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    from . import task_sources
    source = task_sources.source_info(db, user, 'recording', rec_id, required=True)
    return render(request, 'task_recording_import.html', user, source=source, rec_id=rec_id,
                  proposals=task_sources.recording_proposals(db, user, source['row']), people=ts.users(db), error='', posted={})


@app.post('/aufgaben/aufzeichnung/{rec_id:int}', dependencies=[Depends(check_csrf)])
async def recording_import_save(request: Request, rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    if not ts.may_create(user):
        raise HTTPException(403)
    from . import task_sources
    source = task_sources.source_info(db, user, 'recording', rec_id, required=True)
    proposals = task_sources.recording_proposals(db, user, source['row'])
    form = await request.form()
    selected = set(form.getlist('selected'))
    try:
        if not selected or not selected <= {str(p['index']) for p in proposals}:
            raise ts.Invalid('Wählen Sie mindestens einen erkannten Aufgabenpunkt aus.')
        imported = 0
        for proposal in proposals:
            index = str(proposal['index'])
            if index not in selected or proposal['imported']:
                continue
            data = dict(title=str(form.get(f'title_{index}', '')), assignee_id=str(form.get(f'assignee_{index}', '')),
                        due_date=str(form.get(f'due_{index}', '')))
            task_sources.create_from_source(db, user, 'recording', rec_id, data, idempotency_key=proposal['raw_key'])
            imported += 1
        db.commit()
    except ts.Invalid as exc:
        db.rollback()
        response = render(request, 'task_recording_import.html', user, source=source, rec_id=rec_id,
                          proposals=proposals, people=ts.users(db), error=str(exc), posted=dict(form), selected=selected)
        response.status_code = 422
        return response
    from .main import _badge_cache
    _badge_cache.clear()
    flash(request, f'{imported} Aufgaben übernommen. Das Originalprotokoll bleibt erhalten.')
    return redirect('/tasks?perspective=delegated')


def external_response(request, db, token, row, link, *, error='', posted=''):
    comments = list(db.scalars(select(TaskComment).where(TaskComment.task_id == row.id, TaskComment.external_visible.is_(True), TaskComment.removed_at.is_(None)).order_by(TaskComment.created_at, TaskComment.id))) if link.comments_enabled else []
    files = list(db.scalars(select(TaskAttachment).where(TaskAttachment.task_id == row.id, TaskAttachment.external_visible.is_(True), TaskAttachment.is_reference.is_(False), TaskAttachment.removed_at.is_(None))))
    response = render(request, 'task_external.html', task=row, link=link, token=token, ts=ts,
                      comments=comments, files=files, error=error, posted=posted)
    response.status_code = 422 if error else 200
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'})
    return response


@app.get('/aufgaben/gast/{token}')
def external_task(request: Request, token: str, db: Session = Depends(get_db)):
    module_on()
    from .main import rate_limit
    from . import task_external
    rate_limit(request, 'task_guest', 120, 600)
    row, link = task_external.resolve(db, token)
    if not row.seen_at:
        row.seen_at = utcnow()
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            row, link = task_external.resolve(db, token)
    return external_response(request, db, token, row, link)


@app.post('/aufgaben/gast/{token}', dependencies=[Depends(check_csrf)])
async def external_task_action(request: Request, token: str, db: Session = Depends(get_db)):
    module_on()
    from .main import rate_limit
    from . import task_external
    rate_limit(request, 'task_guest_write', 30, 600)
    row, link = task_external.resolve(db, token)
    data = dict(await request.form())
    try:
        ts.check_version(row, data)
        if data.get('action') == 'status':
            target = str(data.get('status', ''))
            if target not in {'in_progress', 'done'} or row.status not in {'open', 'in_progress'}:
                raise ts.Invalid('Dieser Statuswechsel ist nicht verfügbar.')
            ts.transition(db, task_external.actor(row), row, target)
        elif data.get('action') == 'comment' and link.comments_enabled:
            body = str(data.get('comment', '')).strip()
            if not body or len(body) > 10000:
                raise ts.Invalid('Geben Sie einen Kommentar mit 1 bis 10.000 Zeichen ein.')
            db.add(TaskComment(task_id=row.id, author_id=None, external_author=row.external_name,
                               body=body, external_visible=True))
            ts.audit(db, row, task_external.actor(row), 'comment', 'Externer Kommentar hinzugefügt.')
        else:
            raise HTTPException(403)
        db.commit()
    except (ts.Invalid, StaleDataError) as exc:
        db.rollback()
        row, link = task_external.resolve(db, token)
        return external_response(request, db, token, row, link, error=str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert. Bitte prüfen Sie die aktuelle Fassung.', posted=str(data.get('comment','')))
    from .main import _badge_cache
    _badge_cache.clear()
    return redirect(f'/aufgaben/gast/{token}')


@app.get('/aufgaben/gast/{token}/dateien/{file_id:int}')
def external_task_file(request: Request, token: str, file_id: int, db: Session = Depends(get_db)):
    module_on()
    from .main import rate_limit
    from . import task_external
    rate_limit(request, 'task_guest_file', 120, 600)
    row, link = task_external.resolve(db, token)
    item = db.get(TaskAttachment, file_id)
    if not item or item.task_id != row.id or item.removed_at or item.is_reference or not item.external_visible:
        raise HTTPException(404)
    path = ts.attachment_path(item)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=item.name, media_type='application/octet-stream',
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
                                 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'none'; sandbox"})


@app.post('/aufgaben/ansicht-aktion', dependencies=[Depends(check_csrf)])
async def view_action(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module_on()
    data = dict(await request.form())
    raw = str(data.get('task_id', ''))
    row = ts.get(db, user, int(raw)) if raw.isdigit() else None
    if row is None:
        raise HTTPException(404)
    try:
        ts.check_version(row, data)
        if data.get('status'):
            ts.transition(db, user, row, str(data['status']))
        elif data.get('due_date'):
            ts.update(db, user, row, {**ts.form_values(row), 'due_date': data['due_date']})
        else:
            raise ts.Invalid('Bitte einen Status oder eine Fälligkeit auswählen.')
        db.commit()
    except (ts.Invalid, StaleDataError) as exc:
        db.rollback()
        return detail(request, db, user, ts.get(db, user, row.id), error=str(exc) if isinstance(exc, ts.Invalid) else 'Die Aufgabe wurde inzwischen geändert.', data=data)
    from .main import _badge_cache
    _badge_cache.clear()
    return redirect(back_path(data.get('back')))


def rules_page(request,db,user,*,data=None,error='',preview=None,rule=None):
    from . import task_rules
    from .task_models import TaskRule
    rules=list(db.scalars(select(TaskRule).order_by(TaskRule.name)))
    return render(request,'task_rules.html',user,rules=rules,rule=rule,data=data or {},error=error,preview=preview,
                  triggers=task_rules.TRIGGERS,actions=task_rules.ACTIONS,priorities=ts.PRIORITIES,statuses=ts.STATUSES,
                  people=ts.users(db),groups=groups(db,user),
                  examples=list(db.scalars(ts.visible_query(user).where(Task.archived_at.is_(None)).order_by(Task.updated_at.desc()).limit(100))))


@app.get('/aufgaben/regeln')
def task_rules_page(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    module_on()
    if not ts.manager(user):raise HTTPException(403)
    return rules_page(request,db,user)


@app.post('/aufgaben/regeln',dependencies=[Depends(check_csrf)])
async def task_rule_save(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    module_on()
    if not ts.manager(user):raise HTTPException(403)
    from . import task_rules
    from .task_models import TaskRule
    data=dict(await request.form())
    try:
        clean=task_rules.rule_values(data)
        raw=str(data.get('example_id',''))
        if data.get('action')=='preview':
            example=ts.get(db,user,int(raw)) if raw.isdigit() else None
            if not example:raise ts.Invalid('Wählen Sie eine Aufgabe für den Test ohne Änderungen aus.')
            matches=task_rules.allowed(db,user,example) and task_rules.matches(example,__import__('json').loads(clean['conditions_json']))
            return rules_page(request,db,user,data=data,preview=('Bedingungen passen. Die Aktion bleibt im Test unausgeführt; Zielberechtigungen werden bei Ausführung erneut geprüft.' if matches else 'Diese Aufgabe erfüllt die Bedingungen nicht. Es wurde nichts verändert.'))
        rule=TaskRule(creator_id=user.id,**clean)
        db.add(rule);db.commit()
    except ts.Invalid as exc:
        db.rollback()
        response=rules_page(request,db,user,data=data,error=str(exc));response.status_code=422;return response
    flash(request,'Regel gespeichert. '+('Sie ist aktiv.' if rule.active else 'Sie ist zunächst pausiert.'))
    return redirect('/aufgaben/regeln')


@app.post('/aufgaben/regeln/{rule_id:int}',dependencies=[Depends(check_csrf)])
async def task_rule_toggle(request:Request,rule_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    module_on()
    if not ts.manager(user):raise HTTPException(403)
    from .task_models import TaskRule
    rule=db.get(TaskRule,rule_id)
    if not rule:raise HTTPException(404)
    data=dict(await request.form())
    try:
        if str(data.get('version'))!=str(rule.version):raise ts.Invalid('Die Regel wurde inzwischen geändert. Bitte neu laden.')
        rule.active=not rule.active
        db.commit()
    except (ts.Invalid,StaleDataError) as exc:
        db.rollback()
        response=rules_page(request,db,user,error=str(exc) if isinstance(exc,ts.Invalid) else 'Die Regel wurde inzwischen geändert.');response.status_code=422;return response
    return redirect('/aufgaben/regeln')
