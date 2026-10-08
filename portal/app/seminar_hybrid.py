"""Per-term participation modes and private video access, under the seminar seat lock."""
import json
import secrets
import re
import hashlib
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from . import seminars as sm, seminar_series as series
from .db import Meeting, Seminar, SeminarLecturerAccess, SeminarEnrollment, SeminarSession, get_settings, utcnow

LABELS = {'onsite': 'Vor Ort', 'online': 'Online', 'hybrid': 'Hybrid: vor Ort oder online'}


def mode(rec, term):
    return json.loads(rec.modes_json or '{}').get(str(term.id), 'online' if term.delivery_mode == 'online' else 'onsite')


def set_modes(db, row, rec, data):
    values=json.loads(rec.modes_json or '{}')
    for term in sm.enrollment_sessions(db,row,rec):
        selected=str(data.get('mode_'+str(term.id),mode(rec,term)))
        if selected not in {'onsite','online'} or (term.delivery_mode!='hybrid' and selected!=term.delivery_mode):
            raise HTTPException(422,'Bitte eine verfügbare Teilnahmeart wählen.')
        values[str(term.id)]=selected
    rec.modes_json=json.dumps(values)


def capacity(row,term,selected):
    return term.online_capacity if selected=='online' else series.setting(row,term,'capacity')


def seats_available(db,row,rec,strict=True):
    for term in sm.enrollment_sessions(db,row,rec):
        selected=mode(rec,term);limit=capacity(row,term,selected)
        if selected not in {'onsite','online'} or (term.delivery_mode!='hybrid' and selected!=term.delivery_mode):return False
        if not limit:continue
        records=db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,
            SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status.in_(sm.BOOKED),SeminarEnrollment.id!=rec.id))
        occupied=sum(mode(other,term)==selected for other in records)
        if occupied>=limit if strict else occupied+1>limit:return False
    return True


def configure_term(db,row,term,data):
    delivery=str(data.get('delivery_mode',term.delivery_mode or 'onsite'))
    kind=str(data.get('video_kind',term.video_kind or 'manual'))
    if delivery not in LABELS or kind not in {'manual','term','series'}:raise HTTPException(422,'Ungültige Durchführung.')
    online_capacity=sm.integer(data.get('online_capacity',term.online_capacity or 0))
    url=sm.safe_url(data.get('online_url',term.online_url or '')) if kind=='manual' else ''
    existing=list(db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,
        SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status.in_(sm.BOOKED))))
    if any(delivery!='hybrid' and mode(r,term)!=delivery for r in existing):
        raise HTTPException(409,'Gebuchte Teilnahmearten zuerst mit den Teilnehmern klären.')
    term.delivery_mode=delivery;term.online_capacity=online_capacity;term.video_kind=kind
    if delivery=='onsite':term.meeting_id=None;term.online_url=''
    elif kind=='manual':term.meeting_id=None;term.online_url=url
    else:
        if get_settings(db).get('module_video','1')!='1':raise HTTPException(409,'Das Videokonferenzmodul ist deaktiviert.')
        meeting=db.get(Meeting,term.meeting_id) if term.meeting_id else None
        if kind=='series':
            if not row.video_room:row.video_room='seminar-'+secrets.token_hex(16)
            meeting=db.scalar(select(Meeting).where(Meeting.room==row.video_room))
        if not meeting or (kind=='term' and meeting.room==row.video_room):
            meeting=Meeting(owner_id=row.owner_id,title=row.title+((' · '+term.title) if term.title else ''),
                room=row.video_room if kind=='series' else 'seminar-'+secrets.token_hex(16),
                starts_at=term.starts_at if kind=='term' else None,
                duration_minutes=int((term.ends_at-term.starts_at).total_seconds()/60) if kind=='term' else None)
            db.add(meeting);db.flush()
        term.meeting_id=meeting.id;term.online_url=''
    db.flush()
    if any(not seats_available(db,row,r,strict=False) for r in existing):raise HTTPException(409,'Kapazität liegt unter den belegten Plätzen.')


def configure(db,user,row,term,payload):
    if not sm.may_plan(db,user,row):raise HTTPException(403)
    return configure_term(db,row,term,payload)


def switch(db,row,rec,term,selected,staff=False):
    if rec.status not in {'confirmed','pending','waitlist','offered','invited','form'}:raise HTTPException(409,'Teilnahmeart kann hier nicht geändert werden.')
    if term not in sm.enrollment_sessions(db,row,rec):raise HTTPException(404)
    if not staff and not can_switch(db,row,term):raise HTTPException(409,'Die Anmeldefrist ist abgelaufen. Bitte die Planung kontaktieren.')
    old=rec.modes_json
    set_modes(db,row,rec,{'mode_'+str(term.id):selected})
    if not seats_available(db,row,rec):
        rec.modes_json=old
        raise HTTPException(409,'Für diese Teilnahmeart sind keine Plätze frei.')
    sm.event(db,row,'participation_mode',detail=f'Teilnahme {rec.id}: {term.title or "Termin"} · {LABELS[selected]}')
    sm.mail(db,row,rec,'Teilnahmeart geändert',f'{term.title or row.title}: {LABELS[selected]}',calendar_file=rec.status=='confirmed')
    db.flush();sm.promote(db,row)


def context(db,row,rec):
    terms=sm.enrollment_sessions(db,row,rec)
    return {'participation_modes':{t.id:mode(rec,t) for t in terms}, 'mode_labels':LABELS,
            'may_switch_mode':{t.id:can_switch(db,row,t) for t in terms}}


def can_switch(db,row,term):
    from datetime import datetime
    deadline=series.setting(row,term,'registration_until')
    if isinstance(deadline,str):deadline=datetime.fromisoformat(deadline) if deadline else None
    return row.status=='published' and term.published and not term.cancelled and term.starts_at>utcnow() and (not deadline or deadline>utcnow())


def room_terms(db,meeting):
    return list(db.scalars(select(SeminarSession).where(SeminarSession.meeting_id==meeting.id)))


def is_seminar_room(db,meeting):
    return bool(re.fullmatch(r'seminar-[0-9a-f]{32}',meeting.room) or room_terms(db,meeting))


def authorized_room(db,user,meeting):
    """Apply seminar authorization before generic room entry; unrelated rooms are allowed."""
    terms=room_terms(db,meeting)
    if not terms:return not is_seminar_room(db,meeting)
    if not user or not user.active or get_settings(db).get('module_seminars','1')!='1':return False
    for term in terms:
        row=db.get(Seminar,term.seminar_id)
        if not row or row.status!='published' or not term.published or term.cancelled or term.delivery_mode=='onsite':continue
        if series.may_term(db,user,row,term):return True
        records=db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==row.id,
            SeminarEnrollment.user_id==user.id,SeminarEnrollment.scope_id.in_([0,term.id]),SeminarEnrollment.status=='confirmed'))
        if any(mode(rec,term)=='online' for rec in records):return True
    return False


def invite_teacher(db,row,term,email):
    """Only explicit publication notifications create this separate guest entitlement."""
    from .security import encrypt, decrypt
    email=email.strip().lower()
    access=db.scalar(select(SeminarLecturerAccess).where(SeminarLecturerAccess.term_id==term.id,SeminarLecturerAccess.email==email))
    if not access:
        token=secrets.token_urlsafe(32)
        access=SeminarLecturerAccess(term_id=term.id,email=email,token_hash=hashlib.sha256(token.encode()).hexdigest(),token_enc=encrypt(token),expires_at=term.ends_at+timedelta(days=1))
        db.add(access)
    else:access.expires_at=term.ends_at+timedelta(days=1)
    db.flush()
    return sm.links.module_url(db,'seminars','/seminare/dozent/'+decrypt(access.token_enc))


def guest_teacher(db,token):
    if len(token)>100:raise HTTPException(404)
    access=db.scalar(select(SeminarLecturerAccess).where(SeminarLecturerAccess.token_hash==hashlib.sha256(token.encode()).hexdigest(),SeminarLecturerAccess.expires_at>utcnow()))
    term=db.get(SeminarSession,access.term_id) if access else None
    row=db.get(Seminar,term.seminar_id) if term else None
    if not row or row.status!='published' or not term.published or term.cancelled or get_settings(db).get('module_seminars','1')!='1':raise HTTPException(404)
    guests=json.loads(term.guests_json or '[]')
    teacher=next((g for g in guests if g.get('email','').strip().lower()==access.email),None)
    if not teacher:raise HTTPException(404)
    return row,term,access,teacher
