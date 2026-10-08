"""Seminars: explicit consent, serialized seat allocation and existing portal integrations."""
import calendar
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select, update
from . import absence, ics, links, notify, profiles, mailtpl
from .db import (LOCAL_TZ, Seminar, SeminarSession, SeminarEnrollment, SeminarEvent,
                 SeminarDelivery, User, get_settings, to_local, utcnow)
from .security import encrypt, decrypt

STATUSES = {'invited':'Eingeladen – Anmeldung erforderlich','unverified':'E-Mail bestätigen',
 'form':'Pflichtformular ausfüllen','pending':'Zulassung ausstehend','confirmed':'Angemeldet',
 'waitlist':'Warteliste','offered':'Platz angeboten – Annahme erforderlich',
 'cancelled':'Abgemeldet','rejected':'Nicht zugelassen'}
BOOKED = {'confirmed','offered'}


def local_input(dt):
    return to_local(dt).strftime('%Y-%m-%dT%H:%M') if dt else ''


def parse_time(value, optional=False):
    if not value and optional:return None
    try:
        dt=datetime.fromisoformat(str(value))
        if dt.tzinfo or dt.second or dt.microsecond:raise ValueError()
        aware=dt.replace(tzinfo=LOCAL_TZ)
        result=aware.astimezone(timezone.utc).replace(tzinfo=None)
        if to_local(result).replace(tzinfo=None)!=dt:raise ValueError()
        return result
    except (ValueError,TypeError):raise HTTPException(422,'Datum oder Uhrzeit ungültig (ggf. Zeitumstellung).')


def integer(value,low=0,high=10000):
    try:
        result=int(value)
        if not low<=result<=high:raise ValueError()
        return result
    except (ValueError,TypeError):raise HTTPException(422,f'Bitte eine Zahl zwischen {low} und {high} eingeben.')


def safe_url(value):
    value=str(value or '').strip()
    try:p=urlsplit(value)
    except ValueError:raise HTTPException(422,'Ungültige Online-Adresse.')
    if value and (p.scheme!='https' or not p.netloc or p.username or p.password or any(c in value for c in '\r\n')):
        raise HTTPException(422,'Online-Adressen müssen vollständige HTTPS-Adressen sein.')
    return value[:1000]


def may_plan(db,user,row):
    if not user or not row:return False
    if user.can('seminars_manage'):return True
    owner=db.get(User,row.owner_id)
    return bool(owner and owner.active and owner.can('seminars') and row.owner_id in absence.acting_ids(db,user))


def may_teach(db,user,row):
    return bool(may_plan(db,user,row) or (user and user.id in json.loads(row.lecturers_json)))


def role(db,user,row):
    return 'planner' if may_plan(db,user,row) else 'lecturer' if may_teach(db,user,row) else ''


def sessions(db,row,active=True):
    q=select(SeminarSession).where(SeminarSession.seminar_id==row.id)
    if active:q=q.where(SeminarSession.cancelled.is_(False))
    return list(db.scalars(q.order_by(SeminarSession.starts_at,SeminarSession.id)))


def enrollment_sessions(db,row,rec):
    return [s for s in sessions(db,row) if not rec.scope_id or s.id==rec.scope_id]


def event(db,row,kind,user=None,detail=''):
    db.add(SeminarEvent(seminar_id=row.id,actor_id=user.id if user else None,kind=kind,detail=detail[:2000]))


def lock(db,row,expected=None):
    # Seat allocation uses a separate lock counter: new registrations do not stale the editor.
    statement=update(Seminar).where(Seminar.id==row.id)
    values={'seat_lock':Seminar.seat_lock+1}
    if expected is not None:
        statement=statement.where(Seminar.revision==expected)
        values['revision']=Seminar.revision+1
    changed=db.execute(statement.values(**values))
    if changed.rowcount!=1:raise HTTPException(409,'Seminar wurde inzwischen geändert. Bitte neu laden.')
    db.flush();db.expire_all()


def recurrence(start,end,kind,count,nth=1,weekday=0):
    count=integer(count,1,52);nth=integer(nth,-1,5);weekday=integer(weekday,0,6)
    if end<=start or end-start>timedelta(days=7):raise HTTPException(422,'Ende muss nach Beginn liegen, Dauer maximal sieben Tage.')
    if kind not in {'once','weekly','fortnightly','monthly','monthly_weekday'}:raise HTTPException(422,'Unbekannte Wiederholung.')
    if kind=='once':count=1
    first=to_local(start).replace(tzinfo=None);duration=to_local(end).replace(tzinfo=None)-first
    result=[]
    for n in range(count):
        if kind in {'weekly','fortnightly'}:dt=first+timedelta(days=n*(14 if kind=='fortnightly' else 7))
        elif kind in {'monthly','monthly_weekday'}:
            month=first.month-1+n;year=first.year+month//12;month=month%12+1
            if kind=='monthly':day=min(first.day,calendar.monthrange(year,month)[1])
            else:
                if nth==0:raise HTTPException(422,'Monatlicher Wochentag: erste bis fünfte oder letzte Woche wählen.')
                days=[d for d in range(1,calendar.monthrange(year,month)[1]+1) if datetime(year,month,d).weekday()==weekday]
                if nth>len(days):continue
                day=days[nth-1] if nth>0 else days[-1]
            dt=first.replace(year=year,month=month,day=day)
            if dt<first:continue
        else:dt=first
        result.append((parse_time(dt.isoformat(timespec='minutes')),parse_time((dt+duration).isoformat(timespec='minutes'))))
    if not result:raise HTTPException(422,'Keine Termine innerhalb der Wiederholung.')
    return result


def new_enrollment(db,row,scope,name,email,user=None,organization='',status='invited'):
    email=str(email).strip().lower()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email) or len(email)>255 or not str(name).strip():
        raise HTTPException(422,'Name und gültige E-Mail-Adresse erforderlich.')
    token=secrets.token_urlsafe(32);terms=sessions(db,row)
    expiry=datetime.max if not row.guest_days else max([utcnow()+timedelta(days=row.guest_days)]+[s.ends_at+timedelta(days=row.guest_days) for s in terms])
    rec=SeminarEnrollment(seminar_id=row.id,scope_id=scope,name=str(name).strip()[:255],email=email,
        organization=str(organization)[:255],user_id=user.id if user else None,status=status,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),token_enc=encrypt(token),checkin_hash=hashlib.sha256(("check-in:"+token).encode()).hexdigest(),token_expires_at=expiry,
        verified_at=utcnow() if user else None)
    db.add(rec);db.flush();return rec


def personal_path(rec):return '/seminare/p/'+decrypt(rec.token_enc)


def personal_link(db,rec):return links.module_url(db,'seminars',personal_path(rec))


def by_token(db,token):
    if len(token)>100:return None
    return db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.token_hash==hashlib.sha256(token.encode()).hexdigest(),SeminarEnrollment.token_expires_at>utcnow()))


def calendar_text(db,row,rec):
    blocks=[]
    for term in [t for t in sessions(db,row,False) if not rec.scope_id or t.id==rec.scope_id]:
        text=ics.build(method='PUBLISH',uid=f'seminar-{row.id}-{term.id}@portal',sequence=term.revision,
            start=term.starts_at,minutes=int((term.ends_at-term.starts_at).total_seconds()/60),title=row.title+(f' – {term.title}' if term.title else ''),
            description='Persönliche Anmeldung und Unterlagen: '+personal_link(db,rec),location=term.location,
            url=personal_link(db,rec),organizer=None,attendees=[],cancelled=row.status=='cancelled' or term.cancelled)
        blocks.append(text.split('BEGIN:VEVENT\r\n',1)[1].split('END:VEVENT\r\n',1)[0])
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:'+ics.PRODID+'\r\nMETHOD:PUBLISH\r\n'+''.join('BEGIN:VEVENT\r\n'+b+'END:VEVENT\r\n' for b in blocks)+'END:VCALENDAR\r\n'


def mail(db,row,rec,subject,message,key=None,calendar_file=False):
    if key and db.scalar(select(SeminarDelivery.id).where(SeminarDelivery.enrollment_id==rec.id,SeminarDelivery.key==key)):return False
    dates='\n'.join(to_local(t.starts_at).strftime('%d.%m.%Y %H:%M')+' – '+to_local(t.ends_at).strftime('%H:%M')+' · '+t.location+(' · abgesagt' if t.cancelled else '') for t in sessions(db,row,False) if not rec.scope_id or t.id==rec.scope_id)
    rendered_subject,text=mailtpl.render(db,'seminar',{'name':rec.name,'titel':row.title,'aktion':subject,'nachricht':message,'status':STATUSES[rec.status],'termine':dates,'link':personal_link(db,rec)})
    attachments=[{'filename':'seminar.ics','content':calendar_text(db,row,rec),'mime':'text/calendar'}] if calendar_file else None
    queued=notify.enqueue(db,rec.email,rendered_subject,text,'seminar',attachments=attachments,per_hour=20)
    if queued and key:db.add(SeminarDelivery(enrollment_id=rec.id,key=key))
    return queued


def registration_open(db,row,rec):
    now=utcnow();terms=enrollment_sessions(db,row,rec)
    return bool(row.status=='published' and terms and all(s.starts_at>now for s in terms) and (not row.registration_until or row.registration_until>now))


def seats_available(db,row,rec):
    if not row.capacity:return True
    for term in enrollment_sessions(db,row,rec):
        n=len(list(db.scalars(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id,
            SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status.in_(BOOKED),SeminarEnrollment.id!=rec.id))))
        if n>=row.capacity:return False
    return True


def duplicate(db,row,rec):
    scopes=[s.id for s in enrollment_sessions(db,row,rec)]
    return db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.email==rec.email,
        SeminarEnrollment.id!=rec.id,SeminarEnrollment.status.in_(['confirmed','pending','waitlist','offered']),
        SeminarEnrollment.scope_id.in_([0,*scopes]))) is not None


def request_place(db,row,rec):
    if rec.status in {'confirmed','pending','waitlist','offered'}:return
    if not registration_open(db,row,rec):raise HTTPException(409,'Anmeldung nicht mehr möglich.')
    if not rec.verified_at:raise HTTPException(409,'Bitte zuerst Ihre E-Mail bestätigen.')
    if duplicate(db,row,rec):raise HTTPException(409,'Sie sind für diesen Termin bereits angemeldet oder auf der Warteliste.')
    rec.requested_at=utcnow()
    from .seminar_learning import required_forms
    if (row.form_id and not rec.response_id) or required_forms(db,row,rec):rec.status='form';return
    if row.manual_admission:rec.status='pending'
    elif seats_available(db,row,rec):rec.status='confirmed'
    elif row.waitlist:rec.status='waitlist'
    else:raise HTTPException(409,'Alle Plätze sind belegt.')
    mail(db,row,rec,'Anmeldung eingegangen',STATUSES[rec.status],calendar_file=rec.status=='confirmed')
    event(db,row,'registration',detail=f'Teilnahme {rec.id}: {rec.status}')


def promote(db,row):
    for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.status=='waitlist').order_by(SeminarEnrollment.requested_at,SeminarEnrollment.id)):
        if registration_open(db,row,rec) and seats_available(db,row,rec):
            rec.status='offered';rec.offer_until=min(utcnow()+timedelta(hours=row.offer_hours),min(s.starts_at for s in enrollment_sessions(db,row,rec)))
            mail(db,row,rec,'Ein Platz ist frei','Bitte nehmen Sie Ihren Platz bis '+to_local(rec.offer_until).strftime('%d.%m.%Y %H:%M')+' ausdrücklich an.')
            db.flush()


def cancel(db,row,rec,staff=False,reason=''):
    if not staff and rec.status in BOOKED:
        terms=enrollment_sessions(db,row,rec)
        if not terms or utcnow()>=min(s.starts_at for s in terms)-timedelta(hours=row.cancel_hours):raise HTTPException(409,'Die Abmeldefrist ist abgelaufen. Bitte wenden Sie sich an die Planung.')
    rec.status='cancelled';rec.reason=reason[:500];rec.offer_until=None
    event(db,row,'cancellation',detail=f'Teilnahme {rec.id}: {reason[:500]}')
    mail(db,row,rec,'Abmeldung bestätigt','Ihre Anmeldung wurde abgemeldet.');db.flush();promote(db,row)


def accept_offer(db,row,rec):
    if rec.status!='offered' or not rec.offer_until or rec.offer_until<=utcnow():raise HTTPException(409,'Das Platzangebot ist abgelaufen.')
    if not registration_open(db,row,rec) or not seats_available(db,row,rec):raise HTTPException(409,'Der angebotene Termin ist nicht mehr verfügbar.')
    rec.status='confirmed';rec.offer_until=None
    mail(db,row,rec,'Platz bestätigt','Ihr Platz ist verbindlich bestätigt.',calendar_file=True)


def tick():
    from .db import SessionLocal
    count=0
    with SessionLocal() as db:
        if get_settings(db).get('module_seminars','1')!='1':return 0
        for row in db.scalars(select(Seminar).where(Seminar.status=='published')):
            if db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.status.in_(['offered','waitlist']))):lock(db,row)
            for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.status=='offered',SeminarEnrollment.offer_until<=utcnow())):
                rec.status='cancelled';rec.reason='Platzangebot abgelaufen';event(db,row,'offer_expired',detail=str(rec.id))
            db.flush();promote(db,row)
            for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,SeminarEnrollment.status=='confirmed')):
                for term in enrollment_sessions(db,row,rec):
                    for days in sorted([int(x) for x in row.reminder_days.split(",") if x],reverse=True):
                        if utcnow()<term.starts_at<=utcnow()+timedelta(days=days):
                            # A late registration receives the nearest reminder, rather than both at once.
                            if any(0<d<days and term.starts_at<=utcnow()+timedelta(days=d) for d in [int(x) for x in row.reminder_days.split(',') if x]):continue
                            if mail(db,row,rec,'Erinnerung',to_local(term.starts_at).strftime('Ihr Termin beginnt am %d.%m.%Y um %H:%M.'),f'reminder:{term.id}:{term.revision}:{days}',True):count+=1
        db.commit()
    return count


def overview(db,user):
    records=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.user_id==user.id,SeminarEnrollment.status.in_(['invited','form','pending','confirmed','waitlist','offered']))))
    items=[]
    for rec in records:
        row=db.get(Seminar,rec.seminar_id);terms=enrollment_sessions(db,row,rec)
        if row.status=='published' and any(s.ends_at>utcnow() for s in terms):items.append({'row':row,'rec':rec,'status':STATUSES[rec.status]})
    return {'items':items[:6],'count':len(items)}
