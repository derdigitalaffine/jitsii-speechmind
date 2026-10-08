"""Term detail pages, explicit subscription consent and personal booking history."""
import hashlib
import json
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import seminars as sm, seminar_series as series, seminar_learning as learning
from .db import (Seminar, SeminarSession, SeminarEnrollment, SeminarSubscription, SeminarCertificate,
                 SeminarEvent, User, utcnow)
from .main import app, check_csrf, current_user, get_db, render, redirect, session_user, rate_limit, flash
from .routes_seminars import staff_of, row_of, can_read, personal_of, protect


def sub_of(request,db,token):
    if len(token)>100:raise HTTPException(404)
    sub=db.scalar(select(SeminarSubscription).where(SeminarSubscription.token_hash==hashlib.sha256(token.encode()).hexdigest()))
    if not sub:raise HTTPException(404)
    row=row_of(db,sub.seminar_id);user=session_user(request,db)
    if sub.user_id and (not user or user.id!=sub.user_id):raise HTTPException(403,'Bitte mit Ihrem Benutzerkonto anmelden.')
    return row,sub,user


@app.post('/seminare/{sid:int}/subscribe',dependencies=[Depends(check_csrf)])
async def seminar_subscribe(request:Request,sid:int,db:Session=Depends(get_db)):
    row=row_of(db,sid);user=session_user(request,db)
    if row.status!='published' or not can_read(db,user,row):raise HTTPException(404)
    data=await request.form();rate_limit(request,'seminar-subscribe',limit=10);sm.lock(db,row)
    sub=series.subscribe(db,row,user,str(data.get('name','')),str(data.get('email','')));db.commit()
    if user:return redirect(series.subscription_path(sub))
    return protect(render(request,'seminar_message.html',None,message='Bitte bestätigen Sie das Reihenabonnement über den Link in Ihrem E-Mail-Postfach. Es reserviert keine Plätze.'))


@app.post('/seminare/p/{token}/subscribe',dependencies=[Depends(check_csrf)])
def seminar_invited_subscribe(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);sm.lock(db,row)
    if not rec.verified_at and not user:raise HTTPException(403,'Bitte zuerst die Einladung bestätigen.')
    sub=series.subscribe(db,row,user,rec.name,rec.email)
    if not user:sub.active=True;sub.confirmed_at=sub.confirmed_at or utcnow()
    db.commit();return redirect(series.subscription_path(sub))


@app.get('/seminare/abo/{token}')
def seminar_subscription(request:Request,token:str,db:Session=Depends(get_db)):
    row,sub,user=sub_of(request,db,token)
    return protect(render(request,'seminar_subscription.html',user,row=row,sub=sub,token=token,
        terms=sm.sessions(db,row),records=series.history(db,row,sub.email),statuses=sm.STATUSES,now=utcnow(),personal_path=sm.personal_path))


@app.post('/seminare/abo/{token}',dependencies=[Depends(check_csrf)])
async def seminar_subscription_action(request:Request,token:str,db:Session=Depends(get_db)):
    row,sub,user=sub_of(request,db,token);data=await request.form();sm.lock(db,row)
    action=data.get('action')
    if action=='confirm':
        if not row.subscriptions or row.status!='published':raise HTTPException(409)
        sub.active=True;sub.confirmed_at=sub.confirmed_at or utcnow();sm.event(db,row,'subscribed',user,str(sub.id))
    elif action=='unsubscribe':sub.active=False;sm.event(db,row,'unsubscribed',user,str(sub.id))
    elif action=='book':
        if not sub.confirmed_at:raise HTTPException(403,'Zuerst E-Mail-Adresse bestätigen.')
        records=series.book(db,row,sub,data);db.commit()
        if len(records)==1:return redirect(sm.personal_path(records[0]))
    else:raise HTTPException(422)
    db.commit();return redirect(series.subscription_path(sub))


@app.get('/seminare/{sid:int}/terms/{tid:int}')
def seminar_term(request:Request,sid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);term=series.term_of(db,row,tid)
    if not series.may_term(db,user,row,term):raise HTTPException(404)
    return protect(render(request,'seminar_term.html',user,row=row,term=term,planner=sm.may_plan(db,user,row),
        series=series,teachers=series.teachers(db,row,term),selected=series.lecturer_ids(row,term),
        people=list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))),
        deadline_input=sm.local_input(__import__('datetime').datetime.fromisoformat(json.loads(term.overrides_json)['registration_until'])) if json.loads(term.overrides_json).get('registration_until') else '',overrides=json.loads(term.overrides_json),local_input=sm.local_input,guests=json.loads(term.guests_json)))


@app.post('/seminare/{sid:int}/terms/{tid:int}',dependencies=[Depends(check_csrf)])
async def seminar_term_settings(request:Request,sid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row);term=series.term_of(db,row,tid)
    if sm.integer(data.get('revision'))!=term.revision:raise HTTPException(409,'Termin wurde inzwischen geändert.')
    old_ids=series.lecturer_ids(row,term);old_title=term.title
    ids=list(dict.fromkeys(sm.integer(v,1) for v in data.getlist('lecturers')))
    if any(not db.get(User,uid) or not db.get(User,uid).active for uid in ids):raise HTTPException(422)
    lead=sm.integer(data.get('lead_id') or 0)
    if lead and lead not in ids:raise HTTPException(422,'Hauptdozent muss ausgewählt sein.')
    guests=[]
    for line in str(data.get('guests','')).splitlines():
        parts=line.strip().split(';',1)
        if not parts[0]:continue
        email=parts[1].strip() if len(parts)>1 else ''
        if email and not sm.re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email):raise HTTPException(422,'Ungültige Dozenten-E-Mail.')
        guests.append({'name':parts[0][:255],'email':email[:255]})
    if len(guests)>20:raise HTTPException(422,'Maximal 20 externe Dozenten.')
    term.lecturers_json='' if data.get('inherit')=='1' else json.dumps(ids);term.lead_id=lead or None
    term.guests_json=json.dumps(guests,ensure_ascii=False);term.lecturer_description=str(data.get('lecturer_description',''))[:10000]
    term.show_contact=data.get('show_contact')=='1';term.participants_visible=data.get('participants_visible')=='1'
    term.title=str(data.get('title','')).strip()[:255]
    overrides={}
    for key,high in [('capacity',10000),('cancel_hours',8760)]:
        if str(data.get(key,'')).strip():overrides[key]=sm.integer(data[key],0,high)
    if data.get('manual_admission') in ('yes','no'):overrides['manual_admission']=data.get('manual_admission')=='yes'
    deadline=sm.parse_time(data.get('registration_until'),True)
    if deadline:overrides['registration_until']=deadline.isoformat()
    term.overrides_json=json.dumps(overrides)
    for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id.in_([0,tid]),SeminarEnrollment.status.in_(sm.BOOKED))):
        if not sm.seats_available(db,row,rec):raise HTTPException(409,'Kapazität liegt unter den gebuchten/angebotenen Plätzen.')
    publish=data.get('action')=='publish'
    if publish and not term.published:
        if term.cancelled:raise HTTPException(409,'Abgesagten Termin nicht veröffentlichen.')
        term.published=True;term.published_at=utcnow()
        if row.status=='published':series.announce(db,row,'new_terms',term.title+' · '+to_date(term)+'\nJetzt einzeln buchen.')
    if term.published and row.status=='published' and (old_title!=term.title or old_ids!=series.lecturer_ids(row,term)):
        names=', '.join(p['name'] for p in series.teachers(db,row,term))
        for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id.in_([0,tid]),SeminarEnrollment.status.in_(['confirmed','pending','waitlist','offered','invited']))):
            sm.mail(db,row,rec,'Termin geändert',term.title+' · '+to_date(term)+' · Dozenten: '+names,calendar_file=True)
    if old_ids!=series.lecturer_ids(row,term):series.staff_message(db,row,'Dozentenzuordnung',term.title+' · '+to_date(term),[term])
    term.revision+=1;row.revision+=1;row.updated_at=utcnow();sm.event(db,row,'term_settings',user,str(tid));db.commit()
    flash(request,'Termin gespeichert.');return redirect(f'/seminare/{sid}/terms/{tid}')


def to_date(term):return sm.local_input(term.starts_at).replace('T',' ')


@app.post('/seminare/{sid:int}/publish-terms',dependencies=[Depends(check_csrf)])
async def seminar_publish_terms(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row)
    terms=[series.term_of(db,row,sm.integer(v,1)) for v in data.getlist('terms')]
    published=[]
    for term in terms:
        if not term.published and not term.cancelled:
            term.published=True;term.published_at=utcnow();term.revision+=1;published.append(term)
    if published and row.status=='published':series.announce(db,row,'new_terms','Neue Termine:\n'+'\n'.join(t.title+' · '+to_date(t) for t in published))
    row.revision+=1;db.commit();return redirect(f'/seminare/{sid}/edit#termine')


@app.get('/seminare/p/{token}/participants/{tid:int}')
def seminar_public_participants(request:Request,token:str,tid:int,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);term=series.term_of(db,row,tid)
    if not term.participants_visible or rec.status!='confirmed' or tid not in [t.id for t in sm.enrollment_sessions(db,row,rec)]:raise HTTPException(404)
    names=list(db.scalars(select(SeminarEnrollment.name).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.scope_id.in_([0,tid]),SeminarEnrollment.status=='confirmed').order_by(SeminarEnrollment.name)))
    return protect(render(request,'seminar_names.html',user,row=row,term=term,names=names,back=sm.personal_path(rec)))


@app.post('/seminare/{sid:int}/certificate-assets',dependencies=[Depends(check_csrf)])
async def seminar_certificate_assets(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row)
    options=json.loads(row.certificate_options_json)
    from PIL import Image
    import io, secrets
    for key in ('logo','signature'):
        if data.get('remove_'+key)=='1':options.pop(key,None)
        upload=data.get(key)
        if not getattr(upload,'filename',''):continue
        body=await upload.read(2*1024*1024+1)
        if len(body)>2*1024*1024:raise HTTPException(413,'Bilder maximal 2 MB.')
        try:
            with Image.open(io.BytesIO(body)) as image:
                if image.width>4000 or image.height>4000:raise ValueError()
                image.load();converted=image.convert('RGBA');converted.thumbnail((1200,400))
                filename=secrets.token_hex(16)+'.png';converted.save(learning.files_dir(row)/filename,'PNG')
        except (ValueError,OSError,Image.DecompressionBombError):raise HTTPException(422,'Bitte ein gültiges PNG- oder JPEG-Bild bis 4000 × 4000 Pixel verwenden.')
        options[key]=str(row.id)+'/'+filename
    row.certificate_options_json=json.dumps(options);sm.event(db,row,'certificate_assets',user);db.commit();return redirect(f'/seminare/{sid}/edit')
