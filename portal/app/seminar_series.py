"""Series subscriptions, term responsibilities and durable notification history."""
import hashlib
import json
import secrets
from datetime import timedelta
from sqlalchemy import select
from fastapi import HTTPException
from . import seminars as sm, mailtpl, notify, profiles
from .db import (SeminarSession, SeminarEnrollment, SeminarSubscription, SeminarNotice,
                 SeminarNoticeDelivery, SeminarDelivery, SeminarMaterial, User, get_settings, utcnow, to_local)
from .security import encrypt, decrypt

EVENTS = {'registration':'Anmeldungen und Entscheidungen','changes':'Terminänderungen und Absagen',
          'reminders':'Terminerinnerungen','materials':'Neue Lehrunterlagen','certificates':'Bescheinigungen',
          'staff':'Zuständige Betreuung informieren','staff_each':'Jede Anmeldung an Betreuung melden',
          'subscriber':'Neue Termine und wichtige Reihenänderungen'}


def enabled(row, kind):
    return json.loads(row.notifications_json).get(kind, kind != 'staff_each')


def term_of(db, row, tid):
    term=db.get(SeminarSession,tid)
    if not term or term.seminar_id!=row.id:raise HTTPException(404)
    return term


def lecturer_ids(row, term):
    return json.loads(term.lecturers_json or row.lecturers_json)


def whole_staff(db, user, row):
    return bool(sm.may_plan(db,user,row) or (user and user.id in json.loads(row.lecturers_json)))


def may_term(db, user, row, term):
    return bool(whole_staff(db,user,row) or (user and user.id in lecturer_ids(row,term)))


def staff_terms(db, user, row):
    return [t for t in sm.sessions(db,row,False) if may_term(db,user,row,t)]


def scope_access(db,user,row,scope):
    return whole_staff(db,user,row) if not scope else may_term(db,user,row,term_of(db,row,scope))


def setting(row, term, key):
    value=json.loads(term.overrides_json).get(key)
    return getattr(row,key) if value is None else value


def teachers(db,row,term):
    result=[]
    for uid in lecturer_ids(row,term):
        user=db.get(User,uid)
        if user and user.active:result.append({'name':user.name,'email':user.email if term.show_contact else '', 'lead':uid==term.lead_id})
    result += [{'name':g['name'],'email':g.get('email','') if term.show_contact else '', 'lead':bool(g.get('lead'))} for g in json.loads(term.guests_json)]
    return result


def history(db,row,email):
    return list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,
        SeminarEnrollment.email==email).order_by(SeminarEnrollment.created_at.desc())))


def subscription_path(sub):return '/seminare/abo/'+decrypt(sub.token_enc)


def subscription_mail(db,row,sub,action,message):
    subject,text=mailtpl.render(db,'seminar',{'name':sub.name,'titel':row.title,'aktion':action,'nachricht':message,
        'status':'Abonniert – keine Platzreservierung','termine':'','link':sm.links.module_url(db,'seminars',subscription_path(sub))})
    return notify.enqueue(db,sub.email,subject,text,'seminar',per_hour=20)


def subscribe(db,row,user,name,email):
    if not row.subscriptions:raise HTTPException(409,'Abonnement deaktiviert.')
    email=(user.email if user else email).strip().lower();name=(user.name if user else name).strip()
    if not name or len(name)>255 or not sm.re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email) or len(email)>255:raise HTTPException(422,'Name und gültige E-Mail-Adresse erforderlich.')
    sub=db.scalar(select(SeminarSubscription).where(SeminarSubscription.seminar_id==row.id,SeminarSubscription.email==email))
    if not sub:
        token=secrets.token_urlsafe(32)
        sub=SeminarSubscription(seminar_id=row.id,name=name,email=email,user_id=user.id if user else None,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),token_enc=encrypt(token));db.add(sub);db.flush()
    if user:
        if sub.user_id not in (None,user.id):raise HTTPException(409)
        sub.user_id=user.id;sub.active=True;sub.confirmed_at=sub.confirmed_at or utcnow()
    else:
        if not notify.mail_configured(get_settings(db)):raise HTTPException(503,'E-Mail-Versand zuerst einrichten.')
        subscription_mail(db,row,sub,'Reihenabonnement bestätigen','Bitte bestätigen Sie das Abonnement ausdrücklich. Es reserviert keine Seminarplätze.')
    return sub


def book(db,row,identity,data):
    scopes=[0] if row.booking_mode=='series' or data.get('whole')=='1' else list(dict.fromkeys(sm.integer(v,1) for v in data.getlist('sessions')))
    if data.get('whole')=='1' and row.booking_mode not in {'series','both'}:raise HTTPException(422)
    if not scopes or any(s and s not in [t.id for t in sm.sessions(db,row)] for s in scopes):raise HTTPException(422,'Verfügbare Termine auswählen.')
    user=db.get(User,identity.user_id) if identity.user_id else None
    records=[]
    for scope in scopes:
        rec=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.email==identity.email,SeminarEnrollment.scope_id==scope))
        if json.loads(row.fixed_groups_json or '[]') and not rec:raise HTTPException(403,'Diese Reihe ist für einen festen Teilnehmerkreis. Bitte eine persönliche Einladung verwenden.')
        if not rec:rec=sm.new_enrollment(db,row,scope,identity.name,identity.email,user, str(data.get('organization','')))
        if not rec.verified_at:rec.verified_at=utcnow()
        from . import seminar_hybrid
        if rec.status not in sm.BOOKED:seminar_hybrid.set_modes(db,row,rec,data)
        sm.request_place(db,row,rec);records.append(rec)
    return records


def announce(db,row,kind,message):
    if enabled(row,'subscriber'):
        db.add(SeminarNotice(seminar_id=row.id,kind=kind,message=message[:10000]))


def staff_message(db,row,action,message,terms=None,only_owner=False,include_external=False):
    if not enabled(row,'staff'):return
    ids={row.owner_id}
    if not only_owner:
        ids.update(json.loads(row.lecturers_json))
        for term in (terms or sm.sessions(db,row)):ids.update(lecturer_ids(row,term))
    for uid in ids:
        user=db.get(User,uid)
        if user and user.active:
            notify.enqueue(db,user.email,row.title+' · '+action,message+'\n'+sm.links.module_url(db,'seminars',f'/seminare/{row.id}/participants'), 'seminar',per_hour=20)


    if include_external and not only_owner:
        external={}
        for term in terms or sm.sessions(db,row):
            for guest in json.loads(term.guests_json or row.guests_json or '[]'):
                email=guest.get('email','').strip().lower()
                if email:external.setdefault(email,[]).append(term)
        for email,assigned in external.items():
            dates='\n'.join(to_local(t.starts_at).strftime('%d.%m.%Y %H:%M')+' · '+(t.title or row.title)+' · '+t.location for t in assigned)
            from . import seminar_hybrid
            # Each explicitly invited guest gets only their own term's conference access.
            private='\n'.join('Persönlicher Dozentenzugang: '+seminar_hybrid.invite_teacher(db,row,t,email) for t in assigned if t.delivery_mode!='onsite')
            notify.enqueue(db,email,row.title+' · '+action,message+'\n'+dates+('\n'+private if private else '')+'\nBitte geben Sie persönliche Links nicht weiter.', 'seminar',per_hour=20)


def registration_staff(db,row,rec):
    if rec.status=='pending' or enabled(row,'staff_each'):
        staff_message(db,row,'Anmeldung bearbeiten',rec.name+' · '+sm.STATUSES[rec.status],sm.enrollment_sessions(db,row,rec),only_owner=rec.status=='pending')


def tick(db,row):
    now=utcnow()
    for sub in db.scalars(select(SeminarSubscription).where(SeminarSubscription.seminar_id==row.id,SeminarSubscription.active.is_(True))):
        notices=list(db.scalars(select(SeminarNotice).where(SeminarNotice.seminar_id==row.id,
            SeminarNotice.created_at>=sub.confirmed_at)))
        sent=set(db.scalars(select(SeminarNoticeDelivery.notice_id).where(SeminarNoticeDelivery.subscription_id==sub.id)))
        due=[n for n in notices if n.id not in sent and (row.digest_mode=='immediate' or n.kind!='new_terms' or to_local(n.created_at).date()<to_local(now).date())]
        if due and subscription_mail(db,row,sub,'Neuigkeiten zur Seminarreihe','\n\n'.join(n.message for n in due)):
            for n in due:db.add(SeminarNoticeDelivery(subscription_id=sub.id,notice_id=n.id))
    for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.status=='confirmed')):
        for m in db.scalars(select(SeminarMaterial).where(SeminarMaterial.seminar_id==row.id)):
            from . import seminar_learning as learning
            if m.id in [item.id for item in learning.available_materials(db,row,rec,db.get(User,rec.user_id) if rec.user_id else None)] and enabled(row,'materials'):
                sm.mail(db,row,rec,'Lehrunterlage verfügbar',m.title,f'material:{m.id}')
        for term in sm.enrollment_sessions(db,row,rec):
            key=f'staff-list:{term.id}:{term.revision}'
            if now<term.starts_at<=now+timedelta(days=1) and enabled(row,'staff') and not db.scalar(select(SeminarDelivery.id).where(SeminarDelivery.enrollment_id==rec.id,SeminarDelivery.key==key)):
                # One summary per term, anchored to the first confirmed enrollment.
                anchor=db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status=='confirmed').order_by(SeminarEnrollment.id))
                if anchor==rec.id:
                    staff_message(db,row,'Teilnehmerübersicht vor Termin',to_local(term.starts_at).strftime('%d.%m.%Y %H:%M')+'\n'+sm.links.module_url(db,'seminars',f'/seminare/{row.id}/participants?tid={term.id}'),[term])
                    if notify.mail_configured(get_settings(db)):db.add(SeminarDelivery(enrollment_id=rec.id,key=key))
        if row.certificate_auto and row.certificates and db.get(User,row.owner_id) and db.get(User,row.owner_id).active:
            from . import seminar_learning as learning
            scopes=[t.id for t in sm.enrollment_sessions(db,row,rec) if t.ends_at<=now] if row.certificate_scope in {'term','both'} else []
            if row.certificate_scope in {'series','both','enrollment'}:scopes.append(0)
            for scope in scopes:
                try:learning.issue_certificate(db,row,rec,db.get(User,row.owner_id),scope)
                except HTTPException as error:
                    if error.status_code!=409:raise


def certificate_teachers(row):return bool(json.loads(row.certificate_options_json).get('teachers'))


def places(db,row,term):
    capacity=setting(row,term,'capacity')
    occupied=len(list(db.scalars(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status.in_(sm.BOOKED)))))
    return 'Ohne Platzbegrenzung' if not capacity else f'{max(0,capacity-occupied)} freie Plätze · {capacity} insgesamt'
