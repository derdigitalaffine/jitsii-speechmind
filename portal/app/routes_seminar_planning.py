"""A shared compact editor and guided flow for initial seminar planning."""
import json
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import seminars as sm, seminar_planning as plan, seminar_series
from .db import Seminar, SeminarSession, SeminarEnrollment, SeminarExternalLecturer, User, Group, utcnow
from .main import app, current_user, get_db, render, enabled_modules, csrf_valid
from .routes_seminars import staff_of, edit_context, protect


def allowed(user):
    if 'seminars' not in enabled_modules() or not user.can('seminars'):raise HTTPException(403)


async def payload(request):
    try:data=await request.json()
    except (ValueError, TypeError):raise HTTPException(422,'Ungültige Planungsdaten.')
    if not isinstance(data,dict) or not csrf_valid(request.session,data.get('csrf')):raise HTTPException(400,'Sitzung abgelaufen. Bitte neu laden.')
    if len(json.dumps(data))>500000:raise HTTPException(413,'Planung zu groß.')
    return data


def state(db,row):
    if not row:return {}
    data=plan.json_object(row.planning_json)
    data.update(title=row.title,description=row.description,revision=row.revision,booking_mode=row.booking_mode,capacity=row.capacity,manual_admission=row.manual_admission,channels=row.channels.split(','),lecturers=json.loads(row.lecturers_json),guests=json.loads(row.guests_json),lead_id=row.lead_id)
    # An incomplete draft preserves its raw fields. Saved terms always reflect the current database.
    actual=sm.sessions(db,row,False)
    if actual:
        data['terms']=[dict(id=t.id,revision=t.revision,starts_at=sm.local_input(t.starts_at),ends_at=sm.local_input(t.ends_at),title=t.title,location=t.location,include=not t.cancelled,lecturers=json.loads(t.lecturers_json) if t.lecturers_json else None,guests=json.loads(t.guests_json) if t.lecturers_json else None,lead_id=t.lead_id if t.lecturers_json else None,delivery_mode=t.delivery_mode,online_capacity=t.online_capacity,online_url=t.online_url,video_mode={'manual':'external','term':'new','series':'shared'}.get(t.video_kind,'external'),published=t.published and row.status=='published',customized=bool(plan.json_object(t.overrides_json).get('planning_customized'))) for t in actual]
    return data


def page(request,db,user,row=None):
    allowed(user) if row is None else None
    from . import resources as resource_module
    resources=[r for r,level in resource_module.visible(db,user) if level>=3] if 'resources' in enabled_modules() else []
    return protect(render(request,'seminar_planner.html',user,row=row,planner_data=state(db,row),
        people=[dict(id=p.id,name=p.name) for p in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))],
        groups=[dict(id=g.id,name=g.name) for g in db.scalars(select(Group).order_by(Group.name))],
        resources=[dict(id=r.id,name=r.name) for r in resources],
        external_directory=[dict(id=g.id,name=g.name,organization=g.organization,email=g.email) for g in db.scalars(select(SeminarExternalLecturer).order_by(SeminarExternalLecturer.name))]))


@app.get('/seminare/planen')
def new_planner(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return page(request,db,user)


@app.get('/seminare/{sid:int}/planen')
def edit_planner(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return page(request,db,user,staff_of(db,user,sid,True))


@app.post('/seminare/planen/vorschau')
async def preview_planner(request:Request,user:User=Depends(current_user)):
    allowed(user);return JSONResponse(plan.preview(await payload(request)))


def user_ids(db,raw):
    if not isinstance(raw,list) or len(raw)>100:raise HTTPException(422,'Ungültige Dozentenauswahl.')
    ids=list(dict.fromkeys(sm.integer(x,1) for x in raw))
    if ids and set(db.scalars(select(User.id).where(User.id.in_(ids),User.active.is_(True))))!=set(ids):raise HTTPException(422,'Dozent nicht mehr verfügbar.')
    return ids


def save(db,user,data,row=None):
    from . import seminar_hybrid, seminar_fixed
    action=data.get('action','draft')
    if action not in {'draft','save','publish'}:raise HTTPException(422)
    if row is None:row=Seminar(owner_id=user.id);db.add(row);db.flush()
    else:sm.lock(db,row,sm.integer(data.get('revision',-1),-1))
    if row.status=='cancelled':raise HTTPException(409,'Abgesagte Veranstaltungen können nicht neu geplant werden.')
    previous_lecturers=json.loads(row.lecturers_json);previous_guests=json.loads(row.guests_json);previous_lead=row.lead_id
    title=str(data.get('title','')).strip()[:255]
    if not title and action!='draft':raise HTTPException(422,'Bitte einen Titel eingeben.')
    row.title=title or 'Neues Seminar';row.description=str(data.get('description',''))[:100000]
    ids=user_ids(db,data.get('lecturers',[]));external=plan.guests(data.get('guests',[]));lead=sm.integer(data.get('lead_id') or 0)
    if lead and lead not in ids:raise HTTPException(422,'Hauptdozent muss ausgewählt sein.')
    if sum(g['lead'] for g in external)+bool(lead)>1:raise HTTPException(422,'Bitte nur einen Hauptdozenten auswählen.')
    row.lecturers_json=json.dumps(ids);row.guests_json=json.dumps(external);row.lead_id=lead or None
    mode=data.get('booking_mode','individual');channels=data.get('channels',['internal'])
    if mode not in {'individual','series','both'} or not isinstance(channels,list) or not channels or any(x not in {'internal','guest','public'} for x in channels):raise HTTPException(422,'Bitte gültige Anmeldeoptionen auswählen.')
    records=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id)))
    if records and row.booking_mode!=mode:raise HTTPException(409,'Buchungsmodus nach Beginn der Anmeldungen nicht ändern.')
    seminar_fixed.configure(db,row,[data['participant_group']] if data.get('participant_group') else [],bool(data.get('participant_confirmation',False)))
    row.booking_mode=mode;row.channels=','.join(dict.fromkeys(channels));row.capacity=sm.integer(data.get('capacity',0),0,10000);row.manual_admission=bool(data.get('manual_admission'))
    if row.capacity and any(not sm.seats_available(db,row,r) for r in records if r.status in sm.BOOKED):raise HTTPException(409,'Platzlimit liegt unter bereits belegten Plätzen.')
    terms=data.get('terms',[])
    if not isinstance(terms,list) or len(terms)>100:raise HTTPException(422,'Maximal 100 Termine je Reihe.')
    existing={t.id:t for t in sm.sessions(db,row,False)};seen=set();changed=[]
    for value in terms:
        if not isinstance(value,dict):raise HTTPException(422,'Ungültiger Termin.')
        tid=sm.integer(value.get('id') or 0)
        if tid and (tid not in existing or tid in seen):raise HTTPException(422,'Ungültiger oder doppelter Termin.')
        if tid:seen.add(tid)
        if value.get('include') is False:
            if tid and ((existing[tid].published and row.status=='published') or records):raise HTTPException(409,'Bestehende veröffentlichte Termine bitte ausdrücklich über die Terminverwaltung absagen.')
            if tid:db.delete(existing[tid])
            continue
        start=sm.parse_time(value.get('starts_at'));end=sm.parse_time(value.get('ends_at'))
        if end<=start or end-start>sm.timedelta(days=7):raise HTTPException(422,'Terminende muss nach Beginn liegen, Dauer maximal sieben Tage.')
        t=existing.get(tid)
        if t and sm.integer(value.get('revision',-1),-1)!=t.revision:raise HTTPException(409,'Ein Termin wurde zwischenzeitlich geändert. Bitte neu laden.')
        if not t:
            if any(not r.scope_id and r.status in sm.BOOKED for r in records):raise HTTPException(409,'Neue Termine würden eine bereits gebuchte ganze Reihe erweitern. Bitte eine neue Reihe anlegen.')
            t=SeminarSession(seminar_id=row.id,published=row.status!='published');db.add(t)
        before=(t.starts_at,t.ends_at,t.title,t.location,t.lecturers_json,t.guests_json,t.delivery_mode,t.online_url,t.video_kind)
        t.starts_at=start;t.ends_at=end;t.title=str(value.get('title',''))[:255];t.location=str(value.get('location',''))[:500]
        override=value.get('lecturers')
        keep_previous=bool(tid and override is None and not value.get('inherit_new') and (ids!=previous_lecturers or external!=previous_guests or (lead or None)!=previous_lead))
        if keep_previous:override=previous_lecturers
        t.lecturers_json='' if override is None else json.dumps(user_ids(db,override))
        t.guests_json=json.dumps(previous_guests if keep_previous else plan.guests(value.get('guests') if override is not None and value.get('guests') is not None else external))
        t.lead_id=previous_lead if keep_previous else sm.integer((value.get('lead_id') if override is not None else lead) or 0) or None
        effective=ids if override is None else json.loads(t.lecturers_json)
        if t.lead_id and t.lead_id not in effective:t.lead_id=None
        opts=plan.json_object(t.overrides_json);opts['planning_customized']=bool(value.get('customized'));t.overrides_json=json.dumps(opts)
        db.flush()
        merged={**data,**value};merged['video_kind']={'external':'manual','new':'term','shared':'series'}.get(merged.get('video_mode','external'),'manual')
        seminar_hybrid.configure_term(db,row,t,merged)
        if tid and before!=(t.starts_at,t.ends_at,t.title,t.location,t.lecturers_json,t.guests_json,t.delivery_mode,t.online_url,t.video_kind):changed.append(t)
        t.revision=(t.revision or 0)+1
    if existing.keys()-seen:raise HTTPException(409,'Bestehende Termine fehlen. Bitte die Planung neu laden; Termine werden nicht stillschweigend entfernt.')
    if action!='draft' and not any(v.get('include') is not False for v in terms):raise HTTPException(422,'Bitte zuerst Termine in der Vorschau zusammenstellen.')
    row.planning_json=json.dumps({k:v for k,v in data.items() if k not in {'csrf','action','revision'}},ensure_ascii=False)
    for g in external:
        if g['save'] and not db.scalar(select(SeminarExternalLecturer.id).where(SeminarExternalLecturer.name==g['name'],SeminarExternalLecturer.email==g['email'],SeminarExternalLecturer.organization==g['organization'])):
            db.add(SeminarExternalLecturer(name=g['name'],email=g['email'],organization=g['organization'],created_by=user.id))
    if action=='publish':
        if not any(v.get('include') is not False for v in terms):raise HTTPException(422,'Mindestens einen Termin auswählen.')
        row.status='published'
        for t in sm.sessions(db,row,False):
            if not t.cancelled:t.published=True;t.published_at=t.published_at or utcnow()
    if changed and row.status=='published':
        for rec in records:
            if rec.status not in {'cancelled','rejected'} and (not rec.scope_id or rec.scope_id in [t.id for t in changed]):sm.mail(db,row,rec,'Termin geändert','Bitte prüfen Sie die aktualisierten Termine, Themen und Orte.',calendar_file=True)
    if action=='publish':seminar_fixed.enroll_published(db,row,sm.sessions(db,row),user)
    if action=='publish' and data.get('notify_lecturers'):seminar_series.staff_message(db,row,'Seminar veröffentlicht','Bitte prüfen Sie Ihre zugeordneten Termine.',sm.sessions(db,row),include_external=True)
    row.updated_at=utcnow();sm.event(db,row,'planning_saved',user,action);db.flush()
    return row


@app.post('/seminare/planen')
async def create_planner(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    allowed(user);data=await payload(request);row=save(db,user,data);db.commit()
    from . import access
    access.sync(db)
    return JSONResponse({'redirect':f'/seminare/{row.id}'+('' if data.get('action')=='publish' else '/planen'),'revision':row.revision})


@app.post('/seminare/{sid:int}/planen')
async def update_planner(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await payload(request);row=save(db,user,data,row);db.commit()
    from . import access
    access.sync(db)
    return JSONResponse({'redirect':f'/seminare/{row.id}'+('' if data.get('action')=='publish' else '/planen'),'revision':row.revision})
