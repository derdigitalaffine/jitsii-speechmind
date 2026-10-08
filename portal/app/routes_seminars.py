"""Responsive seminar planning and participant-bound self-service."""
import json
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import seminar_series, seminars as sm, profiles, shares
from .db import (Seminar, SeminarSession, SeminarEnrollment, SeminarEvent, Poll, Form, Group, Resource, User,
                 to_local, utcnow, get_settings)
from .main import (app, check_csrf, current_user, enabled_modules, flash, get_db,
                   rate_limit, redirect, render, session_user)


def protect(response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})
    return response


def row_of(db,sid):
    if 'seminars' not in enabled_modules():raise HTTPException(404)
    row=db.get(Seminar,sid)
    if not row:raise HTTPException(404)
    return row


def staff_of(db,user,sid,planner=False):
    row=row_of(db,sid)
    if not (sm.may_plan(db,user,row) if planner else sm.may_teach(db,user,row)):raise HTTPException(404)
    return row


def personal_of(request,db,token):
    if 'seminars' not in enabled_modules():raise HTTPException(404)
    rec=sm.by_token(db,token)
    if not rec:raise HTTPException(404,'Persönlicher Link ungültig oder abgelaufen.')
    row=row_of(db,rec.seminar_id);user=session_user(request,db)
    if rec.user_id and (not user or user.id!=rec.user_id):raise HTTPException(403,'Bitte mit dem eingeladenen Benutzerkonto anmelden.')
    return row,rec,user


def can_read(db,user,row):
    return bool(sm.may_teach(db,user,row) or (row.status=='published' and ('public' in row.channels.split(',') or (user and 'internal' in row.channels.split(',')))))


def edit_context(db,user,row):
    forms=list(db.scalars(select(Form).where(Form.owner_id.in_(sm.absence.acting_ids(db,user)),Form.active.is_(True),Form.anonymous.is_(False),Form.kind=='survey')))
    forms=[f for f in forms if f.fee_json in ('','{}') and (not f.internal or user.can('internal_forms'))] if 'forms' in enabled_modules() else []
    polls=list(db.scalars(select(Poll).where(Poll.owner_id.in_(sm.absence.acting_ids(db,user))))) if 'polls' in enabled_modules() else []
    from . import resources
    allowed_resources={r.id:r for r,level in resources.visible(db,user) if level>=3} if 'resources' in enabled_modules() else {}
    conflicts={t.id:resources.conflicts(db,allowed_resources[t.resource_id],None,t.starts_at,t.ends_at) for t in sm.sessions(db,row) if t.resource_id in allowed_resources}
    return dict(row=row,terms=sm.sessions(db,row,False),forms=forms,polls=polls,conflicts=conflicts,
        resources=[r for r,level in resources.visible(db,user) if level>=3] if 'resources' in enabled_modules() else [],
        people=list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))),
        local_input=sm.local_input,selected_lecturers=json.loads(row.lecturers_json),series=seminar_series)


@app.get('/seminare')
def seminar_list(request:Request,db:Session=Depends(get_db)):
    if 'seminars' not in enabled_modules():raise HTTPException(404)
    user=session_user(request,db);tab=request.query_params.get('tab','available');q=request.query_params.get('q','').strip().lower()[:200]
    from . import seminar_series
    from .db import SeminarSubscription
    period=request.query_params.get('period','upcoming')
    cards=[]
    for row in db.scalars(select(Seminar).order_by(Seminar.updated_at.desc())):
        staff=sm.role(db,user,row)
        mine=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.user_id==user.id))) if user else []
        if tab=='manage' and not staff:continue
        sub=db.scalar(select(SeminarSubscription).where(SeminarSubscription.seminar_id==row.id,SeminarSubscription.user_id==user.id)) if user else None
        if tab=='subscribed' and (not sub or not sub.active):continue
        if tab=='mine':
            if period!='all':mine=[r for r in mine if (any(t.ends_at>utcnow() for t in sm.enrollment_sessions(db,row,r)) and r.status not in {'cancelled','rejected'} and row.status!='cancelled')==(period=='upcoming')]
            if not mine:continue
        if tab not in {'manage','mine','subscribed'} and not can_read(db,user,row):continue
        if q and q not in (row.title+' '+row.description).lower():continue
        cards.append(dict(row=row,terms=sm.sessions(db,row),role=staff,mine=mine,subscription=sub))
    return protect(render(request,'seminars.html',user,cards=cards,tab=tab,q=q,statuses=sm.STATUSES,
        subscription_path=seminar_series.subscription_path,period=period,personal_path=sm.personal_path,can_create=bool(user and user.can('seminars'))))


@app.post('/seminare/new',dependencies=[Depends(check_csrf)])
def seminar_new(user:User=Depends(current_user),db:Session=Depends(get_db)):
    if 'seminars' not in enabled_modules() or not user.can('seminars'):raise HTTPException(403)
    row=Seminar(owner_id=user.id);db.add(row);db.flush();sm.event(db,row,'created',user);db.commit()
    return redirect(f'/seminare/{row.id}/edit')


@app.get('/seminare/{sid:int}/edit')
def seminar_edit(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True)
    return protect(render(request,'seminar_edit.html',user,**edit_context(db,user,row)))


@app.post('/seminare/{sid:int}/edit',dependencies=[Depends(check_csrf)])
async def seminar_save(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form()
    sm.lock(db,row,sm.integer(data.get('revision')))
    title=str(data.get('title','')).strip()[:255]
    if not title:raise HTTPException(422,'Titel erforderlich.')
    channels=[v for v in data.getlist('channels') if v in {'internal','guest','public'}]
    if not channels:raise HTTPException(422,'Mindestens einen Zugang wählen.')
    mode=str(data.get('booking_mode','individual'))
    if mode not in {'individual','series','both'}:raise HTTPException(422,'Ungültiger Buchungsmodus.')
    records=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id)))
    if row.booking_mode!=mode and any(r.status not in {'cancelled','rejected'} for r in records):raise HTTPException(409,'Buchungsmodus bei bestehenden Einladungen/Anmeldungen nicht ändern.')
    capacity=sm.integer(data.get('capacity',0));old_capacity=row.capacity;row.capacity=capacity
    if capacity and any(not sm.seats_available(db,row,r) for r in records if r.status in sm.BOOKED):
        # seats_available excludes this record, so exact occupancy == capacity remains valid.
        raise HTTPException(409,'Kapazität kann nicht unter belegte oder angebotene Plätze sinken.')
    context=edit_context(db,user,row)
    form_id=sm.integer(data.get('form_id') or 0);poll_id=sm.integer(data.get('poll_id') or 0)
    if form_id and form_id not in [f.id for f in context['forms']]:raise HTTPException(422,'Ein aktives eigenes Formular ohne Gebühren und Anonymisierung wählen.')
    if poll_id and poll_id not in [p.id for p in context['polls']]:raise HTTPException(422,'Ungültige Terminumfrage.')
    if records and row.form_id!= (form_id or None):raise HTTPException(409,'Pflichtformular nach Beginn der Einladungen nicht wechseln. Für ergänzende Abfragen Aktivitäten nutzen.')
    lecturers=list(dict.fromkeys(sm.integer(x,1) for x in data.getlist('lecturers')))
    if any(x not in [u.id for u in context['people']] for x in lecturers):raise HTTPException(422,'Ungültige Dozentenauswahl.')
    reminder_days=str(data.get('reminder_days','7,1')).strip()
    row.reminder_days=','.join(str(x) for x in sorted(set(sm.integer(x.strip(),1,365) for x in reminder_days.split(',') if x.strip()),reverse=True))
    contact=str(data.get('contact_email','')).strip().lower()
    if contact and not sm.re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',contact):raise HTTPException(422,'Kontakt-E-Mail ungültig.')
    row.contact_email=contact[:255]
    old_title=row.title
    row.title=title;row.description=str(data.get('description',''))[:100000];row.channels=','.join(dict.fromkeys(channels));row.booking_mode=mode
    for key in ('manual_admission','waitlist','advanced','contact_visible','certificates'):setattr(row,key,data.get(key)=='1')
    for key,lo,hi,default in [('offer_hours',1,720,48),('cancel_hours',0,8760,24),('materials_days',0,3650,0),('guest_days',0,3650,0),('certificate_percent',0,100,80)]:setattr(row,key,sm.integer(data.get(key,default),lo,hi))
    row.form_id=form_id or None;row.poll_id=poll_id or None;row.lecturers_json=json.dumps(lecturers if row.advanced else [])
    from . import seminar_series
    if 'series_options' in data:
        row.subscriptions=data.get('subscriptions')=='1';row.form_once=data.get('form_once')=='1'
        row.digest_mode='immediate' if data.get('digest_mode')=='immediate' else 'daily'
        certscope=data.get('certificate_scope','enrollment')
        if certscope not in {'enrollment','term','series','both'}:raise HTTPException(422)
        row.certificate_scope=certscope;row.certificate_auto=data.get('certificate_auto')=='1'
        row.notifications_json=json.dumps({key:data.get('notify_'+key)=='1' for key in seminar_series.EVENTS})
        options=json.loads(row.certificate_options_json);options['teachers']=data.get('certificate_teachers')=='1';row.certificate_options_json=json.dumps(options)
    row.registration_until=sm.parse_time(data.get('registration_until'),True);row.issuer=str(data.get('issuer',''))[:255];row.updated_at=utcnow()
    action=data.get('save_action','save')
    if action=='publish':
        if not sm.sessions(db,row):raise HTTPException(422,'Vor Veröffentlichung mindestens einen Termin anlegen.')
        row.status='published'
    elif action=='cancel':
        row.status='cancelled'
        for r in records:
            if r.status not in {'cancelled','rejected'}:sm.mail(db,row,r,'Veranstaltung abgesagt','Die Veranstaltung wurde abgesagt.',calendar_file=True)
    elif row.status=='published' and old_title!=row.title:
        for r in records:
            if r.status=='confirmed':sm.mail(db,row,r,'Seminar geändert','Der Titel wurde aktualisiert.',calendar_file=True)
    if old_title!=row.title and row.status=='published':seminar_series.announce(db,row,'changes','Die Seminarreihe wurde geändert: '+row.title)
    sm.event(db,row,'settings',user,action);db.flush();sm.promote(db,row);db.commit();flash(request,'Seminar gespeichert.')
    target=f'/seminare/{sid}'+('' if action in {'publish','close','cancel'} else '/edit')
    if request.headers.get('accept')=='application/json':return JSONResponse({'revision':row.revision,'redirect':target if action!='save' else ''})
    return redirect(target)


@app.post('/seminare/{sid:int}/sessions',dependencies=[Depends(check_csrf)])
async def seminar_sessions_add(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row)
    if row.status=='cancelled':raise HTTPException(409,'Abgesagte Veranstaltung.')
    if db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id==0,SeminarEnrollment.status.in_(sm.BOOKED))):raise HTTPException(409,'Neue Termine verändern eine bereits gebuchte ganze Reihe. Neue Reihe anlegen.')
    if row.booking_mode=='series' and db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.status.in_(sm.BOOKED))):raise HTTPException(409,'Reihe hat bereits verbindliche Teilnahmen. Neue Termine als eigene Reihe planen.')
    start=sm.parse_time(data.get('starts_at'));end=sm.parse_time(data.get('ends_at'))
    terms=sm.recurrence(start,end,data.get('repeat','once'),data.get('count',1),data.get('nth',1),data.get('weekday',0))
    if len(sm.sessions(db,row,False))+len(terms)>100:raise HTTPException(422,'Maximal 100 Termine je Reihe.')
    rid=sm.integer(data.get('resource_id') or 0)
    resources=edit_context(db,user,row)['resources']
    if rid and rid not in [r.id for r in resources]:raise HTTPException(404)
    location=str(data.get('location','')).strip()[:500]
    if rid and not location:location=next(r.name for r in resources if r.id==rid)
    url=sm.safe_url(data.get('online_url'))
    for start,end in terms:db.add(SeminarSession(seminar_id=sid,title=str(data.get('session_title',''))[:255],starts_at=start,ends_at=end,location=location,online_url=url,resource_id=rid or None,published=row.status!='published'))
    row.revision+=1;row.updated_at=utcnow();sm.event(db,row,'sessions_created',user,str(len(terms)));db.commit();flash(request,'Termine angelegt. Räume sind noch nicht gebucht.')
    return redirect(f'/seminare/{sid}/edit#termine')


@app.post('/seminare/{sid:int}/sessions/{tid:int}',dependencies=[Depends(check_csrf)])
async def seminar_session_update(request:Request,sid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row);term=db.get(SeminarSession,tid)
    if not term or term.seminar_id!=sid:raise HTTPException(404)
    if sm.integer(data.get('revision'))!=term.revision:raise HTTPException(409,'Termin wurde inzwischen geändert.')
    targets=[t for t in sm.sessions(db,row,False) if (t.starts_at>=term.starts_at if data.get('scope')=='following' else t.id==tid)]
    cancel=data.get('action')=='cancel';reason=str(data.get('reason','')).strip()[:500]
    if cancel and not reason:raise HTTPException(422,'Bitte einen Absagegrund angeben.')
    start=sm.parse_time(data.get('starts_at')) if not cancel else term.starts_at;end=sm.parse_time(data.get('ends_at')) if not cancel else term.ends_at
    if end<=start:raise HTTPException(422,'Ende muss nach Beginn liegen.')
    delta=to_local(start).replace(tzinfo=None)-to_local(term.starts_at).replace(tzinfo=None)
    duration=to_local(end).replace(tzinfo=None)-to_local(start).replace(tzinfo=None)
    for t in targets:
        if cancel:t.cancelled=True;t.reason=reason
        else:
            dt=to_local(t.starts_at).replace(tzinfo=None)+delta
            t.starts_at=sm.parse_time(dt.isoformat(timespec='minutes'));t.ends_at=sm.parse_time((dt+duration).isoformat(timespec='minutes'))
            t.location=str(data.get('location',''))[:500];t.online_url=sm.safe_url(data.get('online_url'))
        t.revision+=1
    target_ids={t.id for t in targets}
    for r in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.status.in_(['confirmed','offered','waitlist','pending','invited']))):
        if not r.scope_id or r.scope_id in target_ids:
            sm.mail(db,row,r,'Termin abgesagt' if cancel else 'Termin geändert',reason if cancel else 'Bitte beachten Sie den aktualisierten Termin und Ihre Kalenderdatei.',calendar_file=True)
    from . import seminar_series
    seminar_series.staff_message(db,row,'Termin abgesagt' if cancel else 'Termin geändert',reason or 'Bitte den aktualisierten Termin prüfen.',targets)
    row.revision+=1;row.updated_at=utcnow()
    sm.event(db,row,'session_cancelled' if cancel else 'session_changed',user,reason or str(tid));db.commit()
    return redirect(f'/seminare/{sid}/edit#termine')


@app.post('/seminare/{sid:int}/poll-date',dependencies=[Depends(check_csrf)])
def seminar_adopt_date(sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);poll=db.get(Poll,row.poll_id) if row.poll_id else None
    if not poll or poll.owner_id not in sm.absence.acting_ids(db,user) or not poll.final_option:raise HTTPException(409,'Zuerst in Ihrer Terminumfrage einen endgültigen Termin festlegen.')
    if sm.sessions(db,row):raise HTTPException(409,'Termine bereits vorhanden. Änderungen im Terminbereich vornehmen.')
    option=poll.final_option
    db.add(SeminarSession(seminar_id=sid,starts_at=option.starts_at,ends_at=option.ends_at or option.starts_at+timedelta(minutes=poll.duration_minutes),location=poll.location))
    sm.event(db,row,'poll_date_adopted',user,str(poll.id));db.commit();return redirect(f'/seminare/{sid}/edit#termine')


@app.get('/seminare/{sid:int}')
def seminar_detail(request:Request,sid:int,db:Session=Depends(get_db)):
    row=row_of(db,sid);user=session_user(request,db)
    if not can_read(db,user,row):raise HTTPException(404)
    profile=profiles.read(user) if user else {}
    from . import seminar_series
    teachers={t.id:seminar_series.teachers(db,row,t) for t in sm.sessions(db,row)}
    places={t.id:seminar_series.places(db,row,t) for t in sm.sessions(db,row)}
    return protect(render(request,'seminar.html',user,row=row,terms=sm.sessions(db,row),role=sm.role(db,user,row),teachers=teachers,places=places,organization=profile.get('organization','') if profile.get('prefill_enabled') else '',open_registration=bool(row.status=='published' and sm.sessions(db,row) and (not row.registration_until or row.registration_until>utcnow()) and (all(t.starts_at>utcnow() for t in sm.sessions(db,row)) if row.booking_mode=='series' else any(t.starts_at>utcnow() for t in sm.sessions(db,row)))),now=utcnow()))


@app.post('/seminare/{sid:int}/register',dependencies=[Depends(check_csrf)])
async def seminar_register(request:Request,sid:int,db:Session=Depends(get_db)):
    row=row_of(db,sid);user=session_user(request,db)
    if not can_read(db,user,row) or row.status!='published':raise HTTPException(404)
    rate_limit(request,'seminar-register',limit=20);data=await request.form();sm.lock(db,row)
    terms=sm.sessions(db,row);ids=[0] if row.booking_mode=='series' or (row.booking_mode=='both' and data.get('whole')=='1') else list(dict.fromkeys(sm.integer(v,1) for v in data.getlist('sessions')))
    if not ids or any(i and i not in [s.id for s in terms] for i in ids):raise HTTPException(422,'Bitte einen verfügbaren Termin auswählen.')
    email=user.email.strip().lower() if user else str(data.get('email','')).strip().lower();name=user.name if user else str(data.get('name','')).strip()
    if not user and 'public' not in row.channels.split(','):raise HTTPException(403)
    if data.get('website'):return protect(render(request,'seminar_message.html',user,message='Bitte prüfen Sie Ihr E-Mail-Postfach.'))
    recs=[]
    for scope in ids:
        rec=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id==scope,SeminarEnrollment.email==email))
        if rec and user and rec.user_id not in (None,user.id):raise HTTPException(409)
        if not rec:rec=sm.new_enrollment(db,row,scope,name,email,user,str(data.get('organization','')))
        if not sm.registration_open(db,row,rec):raise HTTPException(409,'Anmeldung geschlossen.')
        if user:
            rec.user_id=user.id;rec.verified_at=utcnow();sm.request_place(db,row,rec)
        else:
            # A known address gets no identity disclosure and no reservation before email confirmation.
            if rec.status in {'invited','cancelled','rejected','unverified'}:rec.status='unverified'
            if not sm.mail(db,row,rec,'E-Mail bestätigen','Bitte öffnen Sie den persönlichen Link und bestätigen Sie Ihre Anmeldung.',f'verify:{utcnow().strftime("%Y%m%d%H")}'):
                from . import notify
                if not notify.mail_configured(get_settings(db)):raise HTTPException(503,'Öffentliche Anmeldung benötigt eingerichteten E-Mail-Versand.')
        recs.append(rec)
    db.commit()
    if user and len(recs)==1:return redirect(sm.personal_path(recs[0]))
    if user:return redirect('/seminare?tab=mine')
    return protect(render(request,'seminar_message.html',None,message='Bitte prüfen Sie Ihr E-Mail-Postfach. Über Ihren persönlichen Link bestätigen Sie die Anmeldung und sehen deren Stand.'))


@app.get('/seminare/p/{token}')
def seminar_personal(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token)
    extras={}
    from . import seminar_learning
    extras=seminar_learning.participant_context(db,row,rec,user)
    from . import seminar_series
    events=list(db.scalars(select(SeminarEvent).where(SeminarEvent.seminar_id==row.id).order_by(SeminarEvent.created_at.desc())))
    own_events=[e for e in events if e.detail.startswith(f'Teilnahme {rec.id}:') or e.detail==str(rec.id) or e.detail.startswith(f'{rec.id}:')]
    return protect(render(request,'seminar_personal.html',user,history=own_events,row=row,rec=rec,terms=[t for t in sm.sessions(db,row,False) if not rec.scope_id or t.id==rec.scope_id],statuses=sm.STATUSES,token=token,**extras))


@app.post('/seminare/p/{token}/action',dependencies=[Depends(check_csrf)])
async def seminar_personal_action(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);data=await request.form();sm.lock(db,row);action=data.get('action')
    if action=='register':
        if rec.status=='unverified' or (rec.status=='invited' and not rec.verified_at):rec.verified_at=utcnow()
        sm.request_place(db,row,rec)
    elif action=='accept':sm.accept_offer(db,row,rec)
    elif action=='cancel':sm.cancel(db,row,rec,reason=str(data.get('reason','')))
    else:raise HTTPException(422)
    db.commit();return redirect(sm.personal_path(rec))


@app.get('/seminare/p/{token}/calendar.ics')
def seminar_calendar(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token)
    if rec.status!='confirmed':raise HTTPException(403)
    return protect(Response(sm.calendar_text(db,row,rec),media_type='text/calendar',headers={'Content-Disposition':'attachment; filename="seminar.ics"'}))


@app.get('/seminare/{sid:int}/participants')
def seminar_participants(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid)
    records=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid).order_by(SeminarEnrollment.created_at)))
    planner=sm.may_plan(db,user,row)
    from . import seminar_series, seminar_learning
    terms=seminar_series.staff_terms(db,user,row);tid=sm.integer(request.query_params.get('tid',0))
    if tid and tid not in [t.id for t in terms]:raise HTTPException(404)
    if tid:terms=[t for t in terms if t.id==tid]
    records=[r for r in records if not r.scope_id or r.scope_id in [t.id for t in terms]]
    return protect(render(request,'seminar_participants.html',user,row=row,records=records,statuses=sm.STATUSES,planner=planner,
        terms=terms,tid=tid,whole_staff=seminar_series.whole_staff(db,user,row),people=list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))) if planner else [],
        groups=list(db.scalars(select(Group).order_by(Group.name))) if planner else [],**seminar_learning.staff_context(db,row)))


@app.post('/seminare/{sid:int}/invite',dependencies=[Depends(check_csrf)])
async def seminar_invite(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row)
    if row.status!='published':raise HTTPException(409,'Zuerst veröffentlichen.')
    scope=0 if row.booking_mode=='series' else sm.integer(data.get('scope_id'),1)
    if scope and scope not in [s.id for s in sm.sessions(db,row)]:raise HTTPException(422)
    targets={}
    ids=[sm.integer(x,1) for x in data.getlist('users')]
    for gid in data.getlist('groups'):
        group=db.get(Group,sm.integer(gid,1))
        if not group:raise HTTPException(422)
        ids.extend(u.id for u in group.members if u.active)
    for uid in set(ids):
        member=db.get(User,uid)
        if not member or not member.active:raise HTTPException(422)
        targets[member.email.lower()]=(member.name,member)
    if targets and 'internal' not in row.channels.split(','):raise HTTPException(422,'Internen Zugang zuerst aktivieren.')
    guests=str(data.get('guests','')).strip()
    if guests and 'guest' not in row.channels.split(','):raise HTTPException(422,'Externe Einladungen zuerst aktivieren.')
    if guests and not sm.notify.mail_configured(get_settings(db)):raise HTTPException(503,'Für externe Einladungen muss der E-Mail-Versand eingerichtet sein.')
    for line in guests.splitlines():
        parts=line.split(';',1);name,email=parts if len(parts)==2 else (parts[0],parts[0]);targets[email.strip().lower()]=(name.strip(),None)
    if len(targets)>500:raise HTTPException(422,'Maximal 500 Einladungen gleichzeitig.')
    for email,(name,member) in targets.items():
        rec=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id==scope,SeminarEnrollment.email==email))
        if not rec:rec=sm.new_enrollment(db,row,scope,name,email,member)
        sm.mail(db,row,rec,'Einladung','Bitte melden Sie sich über Ihren persönlichen Link ausdrücklich an. Die Einladung reserviert noch keinen Platz.')
    sm.event(db,row,'invited',user,str(len(targets)));db.commit();flash(request,f'{len(targets)} Einladungen eingereiht (E-Mail-Versand muss eingerichtet sein).')
    return redirect(f'/seminare/{sid}/participants')


@app.post('/seminare/{sid:int}/participants/{eid:int}/decision',dependencies=[Depends(check_csrf)])
async def seminar_decision(request:Request,sid:int,eid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row);rec=db.get(SeminarEnrollment,eid)
    if not rec or rec.seminar_id!=sid:raise HTTPException(404)
    action=data.get('action');reason=str(data.get('reason',''))[:500]
    if action=='cancel':sm.cancel(db,row,rec,True,reason)
    elif action in {'approve','reject'}:
        if rec.status!='pending':raise HTTPException(409,'Nur ausstehende Zulassungen entscheiden.')
        if action=='reject':rec.status='rejected';rec.reason=reason
        elif not sm.registration_open(db,row,rec):raise HTTPException(409,'Anmeldung geschlossen.')
        elif sm.seats_available(db,row,rec):rec.status='confirmed'
        elif row.waitlist:rec.status='waitlist'
        else:raise HTTPException(409,'Keine Plätze frei.')
        sm.mail(db,row,rec,'Zulassung entschieden',sm.STATUSES[rec.status],calendar_file=rec.status=='confirmed')
    else:raise HTTPException(422)
    sm.event(db,row,'decision',user,f'{eid}: {action}');db.commit();return redirect(f'/seminare/{sid}/participants')
