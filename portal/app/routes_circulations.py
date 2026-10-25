"""Umläufe & Aushänge: authenticated editing, recipient-bound actions and guest capabilities."""
import hashlib
import io
import json
import mimetypes
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import circulations as cl, csvsafe, dms, circulation_reports as reports, bundle_lifecycle as bl
from .db import (Circulation, CirculationBundle, CirculationDistributor, CirculationEvent, CirculationReceipt,
                 CirculationRecipient, CirculationVersion, DmsFile, Form, Group, LawText, User, to_local, utcnow)
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render, session_user


def module():
    if 'circulations' not in enabled_modules(): raise HTTPException(404)


def row_of(db, cid):
    module()
    row = db.get(Circulation, cid)
    if not row: raise HTTPException(404)
    return row


def edit_of(db, user, cid):
    row = row_of(db, cid)
    if not cl.may_edit(db, user, row) and not cl.may_publish(db, user, row): raise HTTPException(404)
    return row


def new_of(db, user):
    module()
    if not any(user.can(p) for p in ['circulations_create', 'circulations_publish', 'circulations_manage']):
        raise HTTPException(403, 'Das Recht zum Erstellen fehlt.')
    row = Circulation(owner_id=user.id, draft_json=cl.dumps(cl.default()))
    db.add(row); db.flush()
    cl.event(db, row, 'create', user=user)
    return row


def guest_of(db, token):
    module()
    if len(token) > 100: raise HTTPException(404)
    rec = db.scalar(select(CirculationRecipient).where(CirculationRecipient.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                     CirculationRecipient.user_id.is_(None)))
    if not rec or not rec.token_expires_at or rec.token_expires_at <= utcnow():
        raise HTTPException(404, 'Dieser Gastlink ist ungültig oder abgelaufen. Bitte einen neuen Link beim Herausgeber anfordern.')
    ver = db.get(CirculationVersion, rec.version_id)
    row = row_of(db, ver.circulation_id)
    if not cl.readable(db, row, ver, guest=rec): raise HTTPException(404)
    return row, ver, rec


def protect(response):
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'})
    return response


@app.get('/umlaeufe')
def circulation_list(request: Request, db: Session = Depends(get_db)):
    module()
    user = session_user(request, db)
    tab = request.query_params.get('tab', 'mine' if user else 'board')
    q = request.query_params.get('q', '').strip().lower()[:200]
    category = request.query_params.get('category', '')[:80]
    cards = []
    category_options = set(cl.CATEGORIES)
    for row in db.scalars(select(Circulation).order_by(Circulation.updated_at.desc())):
        ver = cl.version(db, row)
        manager = cl.may_edit(db, user, row) or (user and cl.may_publish(db, user, row))
        if tab in {'manage', 'drafts'}:
            if not manager: continue
            if tab == 'drafts' and row.current_version: continue
            c = cl.content(row)
        else:
            if not ver or not cl.readable(db, row, ver, user): continue
            c = cl.content(ver)
            is_archived = row.archived or cl.expired(ver)
            if is_archived != (tab == 'archive'): continue
            if tab == 'mine' and (not user or not cl.own_recipient(db, ver, user)): continue
            if tab == 'open':
                rec = cl.own_recipient(db, ver, user)
                if not rec or rec.decision or c['mode'] == 'info': continue
        category_options.add(c['category'])
        if q and q not in (c['title'] + ' ' + c['body'] + ' ' + c['category']).lower(): continue
        if category and c['category'] != category: continue
        rec = cl.own_recipient(db, ver, user) if ver else None
        cards.append(dict(row=row, can_delete=cl.may_edit(db,user,row), c=c, ver=ver, rec=rec, status=(cl.DECISIONS[rec.decision] if rec.decision else cl.action_label(c) if cl.ready(db, ver, rec) else 'Sie sind später an der Reihe') if rec and c['mode'] != 'info' else ('Entwurf' if not ver else 'Keine Rückmeldung erforderlich'),
                          report=reports.snapshot(db, row, ver) if manager and tab in {'manage','drafts'} else None,
                          author=db.get(User,ver.published_by).name if ver and db.get(User,ver.published_by) else '', excerpt=plain_excerpt(c['body']), overdue=bool(ver and rec and not rec.decision and c['due_on'] and cl.at(c['due_on']) < utcnow())))
    cards.sort(key=lambda x: not x['c']['pinned'])
    return protect(render(request, 'circulations.html', user, cards=cards, tab=tab, q=q, category=category,
                          categories=sorted(category_options), can_create=bool(user and any(user.can(p) for p in ['circulations_create', 'circulations_publish', 'circulations_manage'])),
                          can_review=bool(user and user.can('circulations_publish'))))


@app.post('/umlaeufe/new', dependencies=[Depends(check_csrf)])
def circulation_new(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = new_of(db, user); db.commit()
    return redirect(f'/umlaeufe/{row.id}/edit')


def editor_context(db, user, row):
    distributors = db.scalars(select(CirculationDistributor).where(CirculationDistributor.owner_id.in_(
        cl.absence.acting_ids(db, user)))).all()
    people = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    groups = db.scalars(select(Group).order_by(Group.name)).all()
    laws = db.scalars(select(LawText).where(LawText.published.is_(True)).order_by(LawText.title)).all() if 'laws' in enabled_modules() else []
    forms = db.scalars(select(Form).where(Form.active.is_(True), Form.public_token.is_not(None), True if user.can('internal_forms') else Form.internal.is_(False)).order_by(Form.title)).all() if 'forms' in enabled_modules() else []
    files = list(db.scalars(select(DmsFile).where(DmsFile.record_id.in_(select(cl.DmsRecord.id).where(cl.DmsRecord.area_id.in_(list(dms.levels(db,user))),cl.DmsRecord.archived_at.is_(None)))).order_by(DmsFile.name))) if 'dms' in enabled_modules() else []
    objects = []
    for law in laws:
        objects.append(dict(ref=f'law:{law.id}', kind='law', id=law.id, title=law.title,
                            detail='Interner Rechtstext / Dienstanweisung' if law.internal else 'Öffentlicher Rechtstext', protected=law.internal))
    for form in forms:
        objects.append(dict(ref=f'form:{form.id}', kind='form', id=form.id, title=form.title,
                            detail='Internes Formular' if form.internal else 'Formular', protected=form.internal))
    for file in files:
        objects.append(dict(ref=f'dms:{file.id}',kind='dms',id=file.id,title=file.name,
                            detail='DMS · '+file.record.title, protected=True))
    c = cl.content(row)
    bundles = available_bundles(db,user) if not isinstance(row,CirculationBundle) else []
    bundle_data = {}
    for bundle in bundles:
        body = cl.content(bundle)
        accessible = all(cl.item_access(db,user,i) for i in body['items'])
        bundle_data[str(bundle.id)] = {'title':body['title'], 'accessible':accessible, 'items':body['items'] if accessible else []}
    existing_refs = {f"{i['kind']}:{i.get('id')}" for i in c['items'] if i['kind'] in {'law','form','dms'}}
    return dict(row=row, c=c, can_edit_draft=cl.may_edit(db,user,row), categories=cl.CATEGORIES, people=people, groups=groups, distributors=distributors,
                objects=objects, existing_refs=existing_refs, bundles=bundles, bundle_content=cl.content, bundle_data=bundle_data, bundle_editable={b.id:bundle_may_edit(db,user,b) for b in bundles},
                editor_data={'items':c['items'], 'users':c['audience']['users'], 'groups':c['audience']['groups'],
                             'bundles':bundle_data, 'group_members':{str(g.id):[u.id for u in g.members if u.active] for g in groups}, 'user_count':len(people)},
                item_labels={'law':'Rechtstext','form':'Formular','dms':'DMS-Dokument','file':'Datei','markdown':'Markdown'},
                can_publish=False if isinstance(row,CirculationBundle) else cl.may_publish(db, user, row), date_input=lambda value: to_local(cl.at(value)).strftime('%Y-%m-%dT%H:%M') if value else '')


@app.get('/umlaeufe/{cid:int}/edit')
def circulation_edit(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid)
    context=editor_context(db,user,row)
    candidate=request.query_params.get('bundle','')
    context['selected_bundle']=int(candidate) if candidate.isdigit() and candidate in context['bundle_data'] and context['bundle_data'][candidate]['accessible'] else None
    return protect(render(request, 'circulation_edit.html', user, **context))


@app.post('/umlaeufe/preview', dependencies=[Depends(check_csrf)])
async def circulation_preview(request: Request, user: User = Depends(current_user)):
    module()
    if not any(user.can(p) for p in ['circulations_create', 'circulations_publish', 'circulations_manage']):
        raise HTTPException(403)
    data = await request.form()
    return HTMLResponse(cl.markdown(str(data.get('body', ''))[:100000]))


async def save_documents(db, user, row, data, c, staged):
    item_refs = {'item:'+i['key']:i for i in c['items']}
    if isinstance(row,CirculationBundle):
        if data.getlist('add_bundle'):
            raise HTTPException(422,'Mappen enthalten Dokumente, keine verschachtelten Mappen.')
        for item in c['items']:
            key='markdown_body_'+item['key']
            if item['kind']=='markdown' and key in data:
                body=str(data[key]);blob=body.encode('utf-8')
                if len(blob)>100000:raise HTTPException(413,'Markdown-Dokumente dürfen maximal 100 kB groß sein.')
                filename=secrets.token_hex(16)+'.md';path=cl.files_dir(row)/filename
                path.write_bytes(blob);staged.append(path)
                item.update(body=body,file=filename,size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),title=str(data.get('markdown_title_'+item['key']) or item['title']).strip()[:255])
    for kind in ['law', 'form', 'dms']:
        for value in data.getlist('add_' + kind):
            if not str(value).isdigit(): continue
            item = dict(key=secrets.token_hex(12), kind=kind, id=int(value), title='')
            item['title'], item['url'] = cl.source(db, user, item)
            existing = next((i for i in c['items'] if i['kind']==kind and i.get('id')==item['id']), None)
            if existing is None:
                c['items'].append(item)
            item_refs[f'{kind}:{item["id"]}'] = existing or item
    for value in dict.fromkeys(data.getlist('add_bundle')):
        if not str(value).isdigit():
            raise HTTPException(422, 'Ungültige Sammelmappe.')
        bundle = bundle_of(db, user, int(value))
        if bundle.archived:raise HTTPException(409,'Archivierte Sammelmappen bitte zuerst reaktivieren.')
        for original in cl.content(bundle)['items']:
            if original['kind'] in {'law','form','dms'}:
                cl.source(db,user,original)
                if any(i['kind']==original['kind'] and i.get('id')==original.get('id') for i in c['items']):
                    continue
            item = copy_document(bundle,row,original,staged)
            item.update(bundle_id=bundle.id,bundle_title=cl.content(bundle)['title'],bundle_updated_at=bundle.updated_at.isoformat())
            c['items'].append(item)
            item_refs[f'bundle:{bundle.id}:{original["key"]}'] = item
    markdown_body = str(data.get('new_markdown_body') or '').strip()
    if markdown_body:
        blob = markdown_body.encode('utf-8')
        if len(blob)>100000:
            raise HTTPException(413,'Markdown-Dokumente dürfen maximal 100 kB groß sein.')
        title = str(data.get('new_markdown_title') or 'Textdokument').strip()[:255]
        filename = secrets.token_hex(16)+'.md'
        path = cl.files_dir(row)/filename
        path.write_bytes(blob);staged.append(path)
        item = dict(key=secrets.token_hex(12),kind='markdown',title=title,file=filename,mime='text/markdown',size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),body=markdown_body)
        c['items'].append(item);item_refs['markdown:new']=item
    uploads = [f for f in data.getlist('files') if getattr(f, 'filename', '')]
    if len(c['items']) + len(uploads) > 100: raise HTTPException(422, 'Maximal 100 Dokumente pro Sammelmappe.')
    for index, f in enumerate(uploads):
        name = Path(f.filename.replace('\\', '/')).name[:255]
        ext = Path(name).suffix.lower()
        if ext not in {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.txt', '.md', '.docx', '.xlsx', '.odt', '.ods', '.eml'}:
            raise HTTPException(422, 'Dieser Dateityp ist nicht zugelassen.')
        blob = await f.read(25 * 1024 * 1024 + 1)
        if not blob or len(blob) > 25 * 1024 * 1024: raise HTTPException(413, 'Pro Datei sind maximal 25 MB erlaubt.')
        if ext == '.pdf' and not blob.startswith(b'%PDF-'): raise HTTPException(422, 'Die Datei ist kein PDF.')
        file = secrets.token_hex(16) + ext
        path = cl.files_dir(row) / file
        path.write_bytes(blob); staged.append(path)
        item = dict(key=secrets.token_hex(12), kind='markdown' if ext=='.md' else 'file', title=name, file=file,
            mime=mimetypes.guess_type(name)[0] or 'application/octet-stream', size=len(blob), sha256=hashlib.sha256(blob).hexdigest())
        c['items'].append(item)
        item_refs[f'upload:{index}'] = item
    if data.get('item_sequence'):
        c['items'] = cl.ordered_items(c['items'], item_refs, str(data['item_sequence']))
    for item in c['items']:
        if item['kind']=='markdown' and 'body' not in item:
            blob = cl.file_path(row,item).read_bytes()
            if len(blob)>100000: raise HTTPException(413, 'Markdown-Dokumente dürfen maximal 100 kB groß sein.')
            try: item['body'] = blob.decode('utf-8-sig')
            except UnicodeDecodeError: raise HTTPException(422, 'Markdown bitte als UTF-8 speichern.')


@app.post('/umlaeufe/{cid:int}/save', dependencies=[Depends(check_csrf)])
async def circulation_save(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid)
    data = await request.form()
    if str(data.get('revision', '')) != row.updated_at.isoformat():
        raise HTTPException(409, 'Der Entwurf wurde zwischenzeitlich geändert. Bitte neu laden.')
    c = cl.form_data(data, cl.content(row))
    for group in c['audience']['groups']:
        if not db.get(Group, group): raise HTTPException(422, 'Unbekannte Gruppe.')
    for uid in c['audience']['users']:
        if not db.get(User, uid) or not db.get(User, uid).active: raise HTTPException(422, 'Unbekannter oder inaktiver Benutzer.')
    if c['escalate_id'] and not db.get(User, c['escalate_id']): raise HTTPException(422, 'Unbekannte Führungskraft.')
    distributor_id = str(data.get('distributor', ''))
    if distributor_id.isdigit():
        distributor = db.get(CirculationDistributor, int(distributor_id))
        if not distributor or (distributor.owner_id not in cl.absence.acting_ids(db, user) and not user.can('circulations_manage')):
            raise HTTPException(403)
        saved = json.loads(distributor.audience_json)
        for key in ['users', 'groups']: c['audience'][key] = list(dict.fromkeys(c['audience'][key] + saved[key]))
        c['audience']['all'] |= saved['all']
        c['audience']['guests'] = list({g['email']: g for g in c['audience']['guests'] + saved['guests']}.values())
    staged = []
    try:
        await save_documents(db,user,row,data,c,staged)
        row.draft_json, row.updated_at = cl.dumps(c), utcnow()
        cl.event(db, row, 'edit', user=user)
        if data.get('save_distributor'):
            db.add(CirculationDistributor(owner_id=user.id, name=str(data['save_distributor'])[:120], audience_json=cl.dumps(c['audience'])))
        db.commit()
    except Exception:
        db.rollback()
        for path in staged: path.unlink(missing_ok=True)
        raise
    flash(request, 'Entwurf gespeichert. Veröffentlichte Fassungen bleiben unverändert.')
    return redirect(f'/umlaeufe/{cid}/edit')


@app.post('/umlaeufe/{cid:int}/publish', dependencies=[Depends(check_csrf)])
async def circulation_publish(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid)
    data = await request.form()
    if str(data.get('revision', '')) != row.updated_at.isoformat(): raise HTTPException(409, 'Bitte den aktuellen Entwurf neu laden.')
    try:
        cl.publish(db, row, user, data.get('reack') != '0'); db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, 'Diese Fassung wurde bereits veröffentlicht. Bitte neu laden.')
    from . import public_nav
    public_nav.invalidate()
    flash(request, 'Fassung veröffentlicht. Der vorhandene Portal-Mailversand übernimmt die Einladungen.')
    return redirect(f'/umlaeufe/{cid}')


@app.post('/umlaeufe/{cid:int}/copy', dependencies=[Depends(check_csrf)])
def circulation_copy(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source_row = edit_of(db, user, cid)
    row = new_of(db, user)
    c = cl.content(source_row); c['title'] += ' (Kopie)'
    c.update(publish_on='', due_on='', expires_on='', review_requested=False)
    for item in c['items']:
        if item['kind'] in {'file','markdown'}:
            shutil.copyfile(cl.file_path(source_row, item), cl.file_path(row, item))
    row.draft_json = cl.dumps(c); db.commit()
    return redirect(f'/umlaeufe/{row.id}/edit')


def view(request, db, row, ver, user=None, guest=None, token=None):
    if not cl.readable(db, row, ver, user, guest): raise HTTPException(404)
    if not ver: return redirect(f'/umlaeufe/{row.id}/edit')
    c = cl.content(ver)
    choices = cl.acting_recipients(db, ver, user)
    rid = request.query_params.get('recipient', '')
    rec = guest or next((r for r in choices if str(r.id) == rid), cl.own_recipient(db, ver, user) or (choices[0] if choices else None))
    manager = cl.may_edit(db, user, row) or bool(user and cl.may_publish(db, user, row))
    base = f'/umlaeufe/g/{token}' if token else f'/umlaeufe/{row.id}'
    items = [{**i, 'accessible': cl.item_access(db, user, i)} for i in c['items']]
    return protect(render(request, 'circulation_detail.html', user, row=row, ver=ver, c=c, items=items,
        recipient=rec, recipient_choices=choices, proxy=bool(rec and user and rec.user_id and rec.user_id != user.id), manager=manager, base=base, guest=guest, markdown=cl.markdown,
        personal_progress=len(set(cl.requirement_keys(c)) & {r.item_key for r in cl.receipts(db, rec)}),
        required_count=len(cl.requirement_keys(c)), next_key=next((k for k in cl.requirement_keys(c) if k not in {r.item_key for r in cl.receipts(db, rec)}), None),
        shared_report=reports.snapshot(db, row, ver) if manager or (rec and c.get('share_progress')) else None,
        can_act=bool(rec and cl.ready(db, ver, rec) and not row.archived and not cl.expired(ver)
                     and row.current_version == ver.number and cl.active(row, ver) and c['mode'] != 'info'),
        acknowledged={r.item_key for r in cl.receipts(db, rec)},
        people=cl.recipients(db, ver) if manager else [], decisions=cl.DECISIONS,
        versions=db.scalars(select(CirculationVersion).where(CirculationVersion.circulation_id == row.id).order_by(CirculationVersion.number.desc())).all() if manager else [],
        events=db.scalars(select(CirculationEvent).where(CirculationEvent.circulation_id == row.id).order_by(CirculationEvent.created_at.desc()).limit(100)).all() if manager else [],
        questions=db.scalars(select(CirculationEvent).where(CirculationEvent.circulation_id == row.id,
                    CirculationEvent.recipient_id == rec.id, CirculationEvent.kind.in_(['question', 'reply'])).order_by(CirculationEvent.created_at)).all() if rec else [],
        now=utcnow(), expired=cl.expired(ver), mail_ready=cl.notify.mail_configured(cl.get_settings(db))))


@app.get('/umlaeufe/g/{token}')
def circulation_guest(request: Request, token: str, db: Session = Depends(get_db)):
    row, ver, rec = guest_of(db, token)
    return view(request, db, row, ver, guest=rec, token=token)


@app.get('/umlaeufe/{cid:int}')
def circulation_detail(request: Request, cid: int, v: int = 0, db: Session = Depends(get_db)):
    row = row_of(db, cid); user = session_user(request, db)
    ver = cl.version(db, row, v)
    return view(request, db, row, ver, user)


def act(db, row, ver, rec, user, data):
    key = str(data.get('key', 'all'))
    item = next((i for i in cl.content(ver)['items'] if i['key'] == key), None)
    if item and not cl.item_access(db, user, item): raise HTTPException(403, 'Keine Leserechte für dieses Dokument.')
    if key == 'all' and any(not cl.item_access(db, user, i) for i in cl.content(ver)['items']):
        raise HTTPException(403, 'Für mindestens ein Dokument fehlen Leserechte. Bitte den Herausgeber kontaktieren.')
    if data.get('decision') != 'rejected' and data.get('confirm') != '1': raise HTTPException(422, 'Bitte die Kenntnisnahme ausdrücklich bestätigen.')
    cl.acknowledge(db, row, ver, rec, user, key, str(data.get('decision', 'ack')), str(data.get('reason', '')))
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, 'Bereits bestätigt. Bitte neu laden.')


@app.post('/umlaeufe/g/{token}/ack', dependencies=[Depends(check_csrf)])
async def circulation_guest_ack(request: Request, token: str, db: Session = Depends(get_db)):
    row, ver, rec = guest_of(db, token)
    act(db, row, ver, rec, None, await request.form())
    return redirect(f'/umlaeufe/g/{token}')


@app.post('/umlaeufe/{cid:int}/ack', dependencies=[Depends(check_csrf)])
async def circulation_ack(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = row_of(db, cid); data = await request.form()
    number = str(data.get('version', ''))
    if not number.isdigit(): raise HTTPException(422, 'Ungültige Fassung.')
    ver = cl.version(db, row, int(number))
    if not ver: raise HTTPException(404)
    rec = next((r for r in cl.acting_recipients(db, ver, user) if str(r.id) == str(data.get('recipient', ''))), cl.own_recipient(db, ver, user))
    act(db, row, ver, rec, user, data)
    return redirect(f'/umlaeufe/{cid}?recipient={rec.id}')


def file_send(db, row, ver, key, user=None):
    item = next((i for i in cl.content(ver)['items'] if i['key'] == key and i['kind'] in {'file','markdown'}), None)
    if not item: raise HTTPException(404)
    path = cl.file_path(row, item)
    if not path.is_file(): raise HTTPException(404)
    safe = item['mime'] in {'application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'}
    return protect(FileResponse(path, filename=item['title'], media_type=item['mime'] if safe else 'application/octet-stream',
        content_disposition_type='inline' if safe else 'attachment',
        headers={'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN' if safe else 'DENY', 'Content-Security-Policy': "default-src 'none'; frame-ancestors 'self'; sandbox"}))


@app.get('/umlaeufe/g/{token}/files/{key}')
def circulation_guest_file(token: str, key: str, db: Session = Depends(get_db)):
    row, ver, rec = guest_of(db, token)
    return file_send(db, row, ver, key)


@app.get('/umlaeufe/{cid:int}/files/{key}')
def circulation_file(request: Request, cid: int, key: str, v: int = 0, db: Session = Depends(get_db)):
    row = row_of(db, cid); ver = cl.version(db, row, v); user = session_user(request, db)
    if not ver or not cl.readable(db, row, ver, user): raise HTTPException(404)
    return file_send(db, row, ver, key, user)


async def question(db, row, ver, rec, user, data):
    text = str(data.get('text', '')).strip()[:4000]
    if not cl.readable(db,row,ver,user,rec if rec and rec.user_id is None else None): raise HTTPException(404)
    if not rec or not text: raise HTTPException(422, 'Bitte eine Rückfrage eingeben.')
    cl.event(db, row, 'question', text, user, ver, rec)
    owner = db.get(User, row.owner_id)
    cl.notify.enqueue(db, owner.email, 'Rückfrage: ' + cl.content(ver)['title'],
        f'{rec.name} fragt:\n\n{text}\n\n' + cl.settings.portal_base_url.rstrip('/') + f'/umlaeufe/{row.id}', 'circulation_question')
    db.commit()


@app.post('/umlaeufe/{cid:int}/question', dependencies=[Depends(check_csrf)])
async def circulation_question(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = row_of(db, cid); ver = cl.version(db, row)
    if not ver: raise HTTPException(404)
    await question(db, row, ver, cl.own_recipient(db, ver, user), user, await request.form())
    return redirect(f'/umlaeufe/{cid}')


@app.post('/umlaeufe/g/{token}/question', dependencies=[Depends(check_csrf)])
async def circulation_guest_question(request: Request, token: str, db: Session = Depends(get_db)):
    row, ver, rec = guest_of(db, token)
    await question(db, row, ver, rec, None, await request.form())
    return redirect(f'/umlaeufe/g/{token}')


@app.post('/umlaeufe/{cid:int}/recipient/{rid:int}', dependencies=[Depends(check_csrf)])
async def circulation_recipient_manage(request: Request, cid: int, rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid); rec = db.get(CirculationRecipient, rid)
    ver = db.get(CirculationVersion, rec.version_id) if rec else None
    if not ver or ver.circulation_id != cid: raise HTTPException(404)
    data = await request.form(); action = str(data.get('action', '')); reason = str(data.get('reason', '')).strip()[:4000]
    if action in {'exempt', 'offline'}:
        if rec.decision or ver.number != row.current_version: raise HTTPException(409, 'Bereits abgeschlossen oder alte Fassung.')
        if not reason: raise HTTPException(422, 'Ein dokumentierter Grund oder Nachweis ist erforderlich.')
        rec.decision, rec.reason, rec.decided_at, rec.recorded_by = action, reason, utcnow(), user.id
        if action == 'offline':
            for key in cl.requirement_keys(cl.content(ver)):
                if key not in {r.item_key for r in cl.receipts(db, rec)}:
                    db.add(CirculationReceipt(recipient_id=rec.id, item_key=key, method='offline', recorded_by=user.id, evidence=reason))
    elif action == 'revoke': rec.token_hash, rec.token_expires_at = None, utcnow()
    elif action == 'resend':
        if rec.user_id is not None: raise HTTPException(422, 'Nur Gastlinks können neu ausgestellt werden.')
        if not cl.notify.mail_configured(cl.get_settings(db)): raise HTTPException(422, 'Zuerst den Portal-Mailversand konfigurieren.')
        if not cl.active(row, ver) or row.archived or cl.expired(ver): raise HTTPException(409, 'Diese Fassung ist nicht geöffnet.')
        url = cl.guest_url(db, row, ver, rec)
        cl.notify.enqueue(db, rec.email, cl.content(ver)['title'], 'Ihr neuer persönlicher Gastlink:\n' + url, 'circulation_personal')
        rec.notified_at = utcnow()
    elif action == 'reply':
        if not reason: raise HTTPException(422, 'Bitte eine Antwort eingeben.')
        cl.notify.enqueue(db, rec.email, 'Antwort: ' + cl.content(ver)['title'], reason, 'circulation_reply')
    else: raise HTTPException(422)
    cl.event(db, row, action, reason, user, ver, rec)
    db.flush(); cl.dispatch(db, row, ver); db.commit()
    return redirect(f'/umlaeufe/{cid}?v={ver.number}#nachweise')


@app.post('/umlaeufe/{cid:int}/archive', dependencies=[Depends(check_csrf)])
def circulation_archive(request: Request, cid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid); row.archived = not row.archived
    cl.event(db, row, 'archive' if row.archived else 'restore', user=user); db.commit()
    from . import public_nav
    public_nav.invalidate()
    return redirect(f'/umlaeufe/{cid}')


def evidence(db, row, ver):
    labels = {'body':'Informationstext','all':'Gesamte Fassung', **{i['key']: i['title'] for i in cl.content(ver)['items']}}
    return dict(title=cl.content(ver)['title'], version=ver.number, digest=ver.digest,
        published_at=ver.published_at.isoformat(), recipients=[dict(name=r.name, email=r.email, decision=cl.DECISIONS[r.decision],
        decided_at=r.decided_at.isoformat() if r.decided_at else '', reason=r.reason, recorded_by=r.recorded_by,
        receipts=[dict(item=x.item_key, title=labels.get(x.item_key,x.item_key), at=x.acknowledged_at.isoformat(), method=x.method, recorded_by=x.recorded_by, evidence=x.evidence)
                  for x in cl.receipts(db, r)]) for r in cl.recipients(db, ver)])


@app.get('/umlaeufe/{cid:int}/export/{fmt}')
def circulation_export(request: Request, cid: int, fmt: str, v: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = edit_of(db, user, cid); ver = cl.version(db, row, v)
    if not ver: raise HTTPException(404)
    data = evidence(db, row, ver)
    if fmt == 'json': body, mime = cl.dumps(data), 'application/json'
    elif fmt == 'csv':
        buf = io.StringIO(); w = csvsafe.writer(buf, delimiter=';')
        w.writerow(['Umlauf', 'Fassung', 'Name', 'E-Mail', 'Status', 'Zeitpunkt UTC', 'Begründung', 'Erfasst durch', 'Dokumentnachweise'])
        for r in data['recipients']: w.writerow([data['title'], ver.number, r['name'], r['email'], r['decision'], r['decided_at'], r['reason'], r['recorded_by'], cl.dumps(r['receipts'])])
        body, mime = '\ufeff' + buf.getvalue(), 'text/csv; charset=utf-8'
    elif fmt in {'pdf', 'signatures'}:
        buf = io.BytesIO(); styles = getSampleStyleSheet(); story = []
        def para(text, style='BodyText'):
            story.append(Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])); story.append(Spacer(1, 8))
        para(data['title'], 'Title'); para(f'Fassung {ver.number} · {to_local(ver.published_at):%d.%m.%Y %H:%M}')
        para('Unterschriftenliste' if fmt == 'signatures' else 'Kenntnisnahme- und Freigabenachweise', 'Heading2')
        for r in data['recipients']:
            para(r['name'], 'Heading3')
            if fmt == 'signatures': para('Datum: ____________________    Unterschrift: ______________________________')
            else:
                para(f'{r["decision"]} · {r["decided_at"]} UTC\n{r["reason"]}')
                for receipt in r['receipts']: para(f'{receipt["title"]} · {receipt["method"]} · {receipt["at"]} UTC · {receipt["evidence"]}')
        para('Fassungsprüfsumme SHA-256: ' + ver.digest)
        SimpleDocTemplate(buf, title=data['title']).build(story); body, mime = buf.getvalue(), 'application/pdf'
    else: raise HTTPException(404)
    ext = 'pdf' if fmt == 'signatures' else fmt
    return protect(Response(body, media_type=mime, headers={'Content-Disposition': f'attachment; filename="umlauf-{cid}-v{ver.number}.{ext}"'}))


# --- Reusable document collections --------------------------------------------

def plain_excerpt(body):
    from html.parser import HTMLParser
    class Excerpt(HTMLParser):
        def handle_data(self,data):
            self.parts.append(data)
    parser=Excerpt();parser.parts=[];parser.feed(str(cl.markdown(body)))
    return ' '.join(' '.join(parser.parts).split())[:280]


def bundle_creator(user):
    return any(user.can(p) for p in ('circulations_create','circulations_publish','circulations_manage','seminars','seminars_manage'))


def bundle_may_edit(db,user,bundle):
    return bool(user and (user.can('circulations_manage') or bundle.owner_id==user.id or bundle.owner_id in cl.absence.acting_ids(db,user)))


def bundle_of(db,user,bid,editing=False):
    module()
    row=db.get(CirculationBundle,bid)
    if not row:raise HTTPException(404)
    editable=bundle_may_edit(db,user,row)
    owner=db.get(User,row.owner_id)
    delegated=bool(editable and owner and owner.active and bundle_creator(owner))
    if not ((editable and (bundle_creator(user) or delegated)) or (not editing and row.shared and bundle_creator(user))):
        raise HTTPException(404)
    return row


def available_bundles(db,user,include_archived=False):
    result=[]
    for row in db.scalars(select(CirculationBundle).order_by(CirculationBundle.updated_at.desc())):
        if row.archived and not include_archived:continue
        try:bundle_of(db,user,row.id)
        except HTTPException:continue
        result.append(row)
    return result


def return_path(value):
    value=str(value or '')
    return value if re.fullmatch(r'/(?:umlaeufe/[0-9]+/edit|seminare/[0-9]+/materials)',value) else ''


def copy_document(source,target,original,staged):
    item=dict(original);item['key']=secrets.token_hex(12)
    if original['kind'] in {'file','markdown'}:
        source_path=cl.file_path(source,original)
        if not source_path.is_file():
            raise HTTPException(422,'Eine Datei der Mappe fehlt. Bitte die Mappe bearbeiten.')
        item['file']=secrets.token_hex(16)+source_path.suffix
        path=cl.file_path(target,item)
        shutil.copyfile(source_path,path);staged.append(path)
    return item


@app.get('/sammelmappen')
def bundle_list(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    module()
    if not bundle_creator(user) and not available_bundles(db,user):raise HTTPException(403)
    q=request.query_params.get('q','').strip()[:200]
    tab=request.query_params.get('tab','active')
    if tab not in {'active','archive','trash'}:tab='active'
    if tab=='trash':
        from .db import TrashItem
        items=[i for i in db.scalars(select(TrashItem).where(TrashItem.kind=='circulation_bundle').order_by(TrashItem.deleted_at.desc())) if bl.trash_access(user,i)]
        return protect(render(request,'circulation_bundle_trash.html',user,items=items))
    bundles=[b for b in available_bundles(db,user,include_archived=True) if b.archived==(tab=='archive') and q.casefold() in (cl.content(b)['title']+' '+cl.content(b)['body']).casefold()]
    all_reports = reports.overview(db,user,'allowed')
    references=bl.used_ids(db)
    return protect(render(request,'circulation_bundles.html',user,bundles=bundles,content=cl.content,q=q,tab=tab, removable={b.id:bl.removable(db,b,references) for b in bundles}, may_remove={b.id:bl.may_remove(user,b) for b in bundles}, may_archive={b.id:bundle_may_edit(db,user,b) for b in bundles},
                   usage={b.id:[r for r in all_reports if str(b.id) in r['bundle_ids']] for b in bundles}, editable={b.id:bundle_may_edit(db,user,b) for b in bundles},can_create=bundle_creator(user),return_to=return_path(request.query_params.get('return_to'))))


@app.post('/sammelmappen/new',dependencies=[Depends(check_csrf)])
async def bundle_new(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    module()
    if not bundle_creator(user):raise HTTPException(403)
    data=await request.form();row=CirculationBundle(owner_id=user.id,draft_json=cl.dumps(cl.default()))
    db.add(row);db.commit()
    from urllib.parse import urlencode
    suffix='?'+urlencode({'return_to':return_path(data.get('return_to'))}) if return_path(data.get('return_to')) else ''
    return redirect(f'/sammelmappen/{row.id}/edit'+suffix)


@app.get('/sammelmappen/{bid:int}/edit')
def bundle_edit(request:Request,bid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=bundle_of(db,user,bid,editing=True)
    if row.archived:return redirect(f'/sammelmappen/{bid}')
    return protect(render(request,'circulation_bundle_edit.html',user,**editor_context(db,user,row),may_remove=bl.may_remove(user,row),may_archive=bundle_may_edit(db,user,row),removable=bl.removable(db,row),return_to=return_path(request.query_params.get('return_to'))))


@app.post('/sammelmappen/{bid:int}/save',dependencies=[Depends(check_csrf)])
async def bundle_save(request:Request,bid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=bundle_of(db,user,bid,editing=True)
    if row.archived:raise HTTPException(409,'Archivierte Sammelmappen bitte zuerst reaktivieren.')
    data=await request.form()
    if str(data.get('revision',''))!=row.updated_at.isoformat():raise HTTPException(409,'Die Mappe wurde zwischenzeitlich geändert. Bitte neu laden.')
    c=cl.form_data(data,cl.content(row))
    if not c['title']:raise HTTPException(422,'Bitte einen Titel für die Mappe angeben.')
    staged=[]
    try:
        await save_documents(db,user,row,data,c,staged)
        row.draft_json=cl.dumps(c);row.shared=data.get('shared')=='1';row.updated_at=utcnow()
        db.commit()
    except Exception:
        db.rollback()
        for path in staged:path.unlink(missing_ok=True)
        raise
    flash(request,'Sammelmappe gespeichert. Bereits verwendete Kopien in Umläufen bleiben erhalten.')
    from urllib.parse import urlencode
    back=return_path(data.get('return_to'))
    return redirect(f'/sammelmappen/{bid}/edit'+('?' + urlencode({'return_to':back}) if back else ''))


@app.get('/sammelmappen/{bid:int}')
def bundle_view(request:Request,bid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=bundle_of(db,user,bid)
    c=cl.content(row)
    items=[{**i,'accessible':cl.item_access(db,user,i)} for i in c['items']]
    return protect(render(request,'circulation_bundle_view.html',user,row=row,c=c,items=items,markdown=cl.markdown,
                   editable=bundle_may_edit(db,user,row),return_to=return_path(request.query_params.get('return_to'))))


@app.get('/sammelmappen/{bid:int}/files/{key}')
def bundle_file(bid:int,key:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=bundle_of(db,user,bid)
    item=next((i for i in cl.content(row)['items'] if i['key']==key and i['kind'] in {'file','markdown'}),None)
    if item is None:raise HTTPException(404)
    path=cl.file_path(row,item)
    if not path.is_file():raise HTTPException(404)
    inline=item.get('mime')=='application/pdf' or str(item.get('mime','')).startswith('image/')
    return protect(FileResponse(path,media_type=item.get('mime') if inline else 'application/octet-stream',filename=item['title'],content_disposition_type='inline' if inline else 'attachment',
                   headers={'X-Content-Type-Options':'nosniff','X-Frame-Options':'SAMEORIGIN' if inline else 'DENY',
                            'Content-Security-Policy':"default-src 'none'; frame-ancestors 'self'; sandbox"}))


@app.post('/sammelmappen/{bid:int}/archive',dependencies=[Depends(check_csrf)])
def bundle_archive(request:Request,bid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=bundle_of(db,user,bid)
    if not bundle_may_edit(db,user,row):raise HTTPException(404)
    row.archived=not row.archived;row.updated_at=utcnow();db.commit()
    flash(request,'Sammelmappe archiviert. Bereits übernommene Inhalte bleiben erhalten.' if row.archived else 'Sammelmappe reaktiviert.')
    return redirect('/sammelmappen?tab='+('archive' if row.archived else 'active'))


@app.post('/sammelmappen/{bid:int}/delete',dependencies=[Depends(check_csrf)])
def bundle_delete(request:Request,bid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from . import trash
    row=bundle_of(db,user,bid)
    if not bl.may_remove(user,row):raise HTTPException(404)
    if not bl.removable(db,row):raise HTTPException(409,'Diese Mappe ist geteilt oder wurde bereits verwendet. Bitte archivieren: übernommene Dokumente und historische Verweise bleiben erhalten.')
    trash.delete_obj(db,'circulation_bundle',row,user.email);trash.log(db,user.email,'delete','circulation_bundle',1,'Eigene ungenutzte Sammelmappe');db.commit()
    flash(request,'Sammelmappe mit ihren Dokumenten für 30 Tage in den Papierkorb verschoben.')
    return redirect('/sammelmappen?tab=trash')


@app.post('/sammelmappen/papierkorb/{tid:int}/restore',dependencies=[Depends(check_csrf)])
def bundle_restore(request:Request,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .db import TrashItem
    from . import trash
    module();item=db.get(TrashItem,tid)
    if not bl.trash_access(user,item):raise HTTPException(404)
    error=trash.restore(db,item,user.email)
    if error:raise HTTPException(409,error)
    db.commit();flash(request,'Sammelmappe mit ihren Dokumenten wiederhergestellt.')
    return redirect('/sammelmappen')


@app.post('/umlaeufe/{cid:int}/bundle',dependencies=[Depends(check_csrf)])
def circulation_to_bundle(request:Request,cid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    original=edit_of(db,user,cid)
    if not bundle_creator(user):raise HTTPException(403)
    row=CirculationBundle(owner_id=user.id,draft_json=cl.dumps(cl.default()));db.add(row);db.flush()
    source=cl.content(original);c=cl.default();c.update(title=source['title'] or 'Sammelmappe',body=source['body'])
    staged=[]
    try:
        for item in source['items']:
            if item['kind'] in {'law','form','dms'}:cl.source(db,user,item)
            c['items'].append(copy_document(original,row,item,staged))
        row.draft_json=cl.dumps(c);db.commit()
    except Exception:
        db.rollback()
        for path in staged:path.unlink(missing_ok=True)
        raise
    return redirect(f'/sammelmappen/{row.id}/edit?return_to=/umlaeufe/{cid}/edit')


@app.get('/umlaeufe/auswertung')
def circulation_reports(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module()
    scope = 'allowed' if request.query_params.get('scope') == 'allowed' else 'mine'
    all_reports = reports.overview(db, user, scope)
    rows = reports.filtered(all_reports, request.query_params)
    return protect(render(request, 'circulation_reports.html', user, reports=rows, totals=reports.totals(rows), scope=scope,
        phases=sorted({r['phase'] for r in all_reports}), params=request.query_params))


@app.get('/umlaeufe/auswertung/export/{fmt}')
def circulation_reports_export(request: Request, fmt: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module()
    scope = 'allowed' if request.query_params.get('scope') == 'allowed' else 'mine'
    rows = reports.filtered(reports.overview(db, user, scope), request.query_params)
    data = [reports.export_data(r) for r in rows]
    if fmt == 'json': body, mime = cl.dumps(data), 'application/json'
    elif fmt == 'csv':
        buf = io.StringIO(); w = csvsafe.writer(buf, delimiter=';')
        w.writerow(['Umlauf', 'ID', 'Fassung', 'Phase', 'Modus', 'Frist UTC', 'Empfänger', 'Erledigt', 'Offen', 'Überfällig', 'Abgelehnt', 'Kenntnisnahmen', 'Freigaben', 'Ausgenommen', 'Extern dokumentiert', 'Übernommen', 'Offene Rückfragen'])
        for r in data: w.writerow([r['title'], r['id'], r['version'], r['phase'], r['mode'], r['due_on'], r['total'], r['completed'], r['pending'], r['overdue'], *[r['counts'].get(k,0) for k in ['rejected','ack','approved','exempt','offline','carried']], r['questions']])
        body, mime = '\ufeff' + buf.getvalue(), 'text/csv; charset=utf-8'
    else: raise HTTPException(404)
    return protect(Response(body, media_type=mime, headers={'Content-Disposition':f'attachment; filename="umlauf-auswertung.{fmt}"'}))


@app.get('/umlaeufe/{cid:int}/auswertung')
def circulation_report(request: Request, cid: int, v: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    module(); row = row_of(db, cid)
    if not reports.may_report(db, user, row): raise HTTPException(404)
    ver = cl.version(db, row, v)
    if v and not ver: raise HTTPException(404)
    report = reports.snapshot(db, row, ver)
    q = request.query_params.get('q','').casefold()[:200]
    state = request.query_params.get('status','')
    kind = request.query_params.get('kind','')
    people = [p for p in report['people'] if (not q or q in (p['rec'].name+' '+p['rec'].email).casefold())
        and (not state or (state == 'pending' and not p['rec'].decision and p['required']) or (state == 'overdue' and p['overdue']) or (state == 'questions' and p['question']) or p['rec'].decision == state)
        and (not kind or (kind == 'guest') == (p['rec'].user_id is None))]
    versions = list(db.scalars(select(CirculationVersion).where(CirculationVersion.circulation_id == cid).order_by(CirculationVersion.number.desc())))
    return protect(render(request, 'circulation_report.html', user, report=report, people=people, versions=versions, q=q, state=state, kind=kind, decisions=cl.DECISIONS))


# Draft deletion uses the portal's existing 30-day trash and restore mechanism.
def draft_trash_access(db,user,item):
    if not item or item.kind != 'circulation_draft' or item.expires_at <= utcnow():return False
    data=json.loads(item.data_json)
    original=next((r['data'] for r in data['rows'] if r['table']=='circulations'),None)
    return bool(original and cl.may_edit(db,user,Circulation(owner_id=original.get('owner_id'),current_version=0)))


@app.post('/umlaeufe/entwuerfe/delete',dependencies=[Depends(check_csrf)])
async def circulation_drafts_delete(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from . import trash
    module();data=await request.form()
    ids=list(dict.fromkeys(int(v) for v in data.getlist('ids') if str(v).isdigit() and len(str(v))<10))
    if not ids or len(ids)>500:raise HTTPException(422,'Bitte 1 bis 500 Entwürfe auswählen.')
    rows=[]
    for cid in ids:
        row=row_of(db,cid)
        if not cl.may_edit(db,user,row):raise HTTPException(404)
        if row.current_version or db.scalar(select(CirculationVersion.id).where(CirculationVersion.circulation_id==cid)):raise HTTPException(409,'Veröffentlichte Umläufe bleiben erhalten. Nur Entwürfe können gelöscht werden.')
        rows.append(row)
    batch=secrets.token_hex(8)
    for row in rows:trash.delete_obj(db,'circulation_draft',row,user.email,batch)
    trash.log(db,user.email,'bulk','circulation_draft',len(rows),'Ausgewählte Umlaufentwürfe');db.commit()
    flash(request,f'{len(rows)} Entwurf/Entwürfe für 30 Tage in den Papierkorb verschoben.')
    return redirect('/umlaeufe?tab=drafts')


@app.get('/umlaeufe/entwuerfe/papierkorb')
def circulation_draft_trash(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .db import TrashItem
    module()
    items=[i for i in db.scalars(select(TrashItem).where(TrashItem.kind=='circulation_draft').order_by(TrashItem.deleted_at.desc())) if draft_trash_access(db,user,i)]
    return protect(render(request,'circulation_trash.html',user,items=items))


@app.post('/umlaeufe/entwuerfe/papierkorb/{tid:int}/restore',dependencies=[Depends(check_csrf)])
def circulation_draft_restore(request:Request,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .db import TrashItem
    from . import trash
    module();item=db.get(TrashItem,tid)
    if not draft_trash_access(db,user,item):raise HTTPException(404)
    error=trash.restore(db,item,user.email)
    if error:raise HTTPException(409,error)
    db.commit();flash(request,'Entwurf mit seinen Dokumenten wiederhergestellt.')
    return redirect('/umlaeufe?tab=drafts')


@app.post('/umlaeufe/{cid:int}/discard',dependencies=[Depends(check_csrf)])
async def circulation_discard(request:Request,cid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=row_of(db,cid)
    if not cl.may_edit(db,user,row):raise HTTPException(404)
    data=await request.form()
    if str(data.get('revision')) != row.updated_at.isoformat():raise HTTPException(409,'Der Entwurf wurde inzwischen geändert. Bitte neu laden.')
    ver=cl.version(db,row)
    if not ver:raise HTTPException(409,'Noch nicht veröffentlicht. Diesen Entwurf können Sie in den Papierkorb verschieben.')
    row.draft_json=cl.dumps(cl.content(ver));row.updated_at=utcnow()
    cl.event(db,row,'discard_draft','Entwurf auf veröffentlichte Fassung zurückgesetzt.',user,ver)
    db.commit();flash(request,'Entwurfsänderungen verworfen. Veröffentlichte Fassungen und Rückmeldungen bleiben erhalten.')
    return redirect(f'/umlaeufe/{cid}/edit')
