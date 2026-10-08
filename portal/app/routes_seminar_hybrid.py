"""Authenticated and personal-token seminar video access and participation changes."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from . import seminar_hybrid as hybrid, seminar_series as series, seminars as sm
from .db import Meeting, SeminarEnrollment, User, get_settings
from .main import app, check_csrf, current_user, get_db, redirect, guest_join_url, join_url
from .routes_seminars import personal_of, staff_of, protect


def video_target(db,row,term,name,email,uid,user=None):
    if row.status!='published' or not term.published or term.cancelled or term.delivery_mode=='onsite':raise HTTPException(404)
    if term.meeting_id:
        if get_settings(db).get('module_video','1')!='1':raise HTTPException(404)
        meeting=db.get(Meeting,term.meeting_id)
        if not meeting or meeting.cancelled_at:raise HTTPException(404)
        return join_url(user,meeting.room,recording=False,moderator=True) if user else guest_join_url(name,meeting.room,uid,email)
    if not term.online_url:raise HTTPException(404,'Noch kein Konferenzzugang hinterlegt.')
    return sm.safe_url(term.online_url)


@app.get('/seminare/p/{token}/video/{tid:int}')
def participant_video(request:Request,token:str,tid:int,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);term=series.term_of(db,row,tid)
    if rec.status!='confirmed' or term not in sm.enrollment_sessions(db,row,rec) or hybrid.mode(rec,term)!='online':raise HTTPException(403)
    return protect(redirect(video_target(db,row,term,rec.name,rec.email,'seminar-'+str(rec.id))))


@app.get('/seminare/{sid:int}/terms/{tid:int}/video')
def staff_video(request:Request,sid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);term=series.term_of(db,row,tid)
    if not series.may_term(db,user,row,term):raise HTTPException(404)
    return protect(redirect(video_target(db,row,term,user.name,user.email,'staff-'+str(user.id),user)))


@app.post('/seminare/p/{token}/mode/{tid:int}',dependencies=[Depends(check_csrf)])
async def participant_mode(request:Request,token:str,tid:int,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);data=await request.form();sm.lock(db,row)
    hybrid.switch(db,row,rec,series.term_of(db,row,tid),str(data.get('mode','')))
    db.commit();return redirect(sm.personal_path(rec))


@app.post('/seminare/{sid:int}/participants/{eid:int}/mode/{tid:int}',dependencies=[Depends(check_csrf)])
async def staff_mode(request:Request,sid:int,eid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid,True);data=await request.form();sm.lock(db,row);rec=db.get(SeminarEnrollment,eid)
    if not rec or rec.seminar_id!=sid:raise HTTPException(404)
    hybrid.switch(db,row,rec,series.term_of(db,row,tid),str(data.get('mode','')),staff=True)
    db.commit();return redirect(f'/seminare/{sid}/participants?tid={tid}')


@app.get('/seminare/dozent/{token}')
def guest_teacher_page(request:Request,token:str,db:Session=Depends(get_db)):
    from .main import render
    row,term,access,teacher=hybrid.guest_teacher(db,token)
    return protect(render(request,'seminar_guest_teacher.html',None,row=row,term=term,teacher=teacher,token=token))


@app.post('/seminare/dozent/{token}/video',dependencies=[Depends(check_csrf)])
def guest_teacher_video(request:Request,token:str,db:Session=Depends(get_db)):
    from urllib.parse import urlencode
    from .config import settings
    from .security import _jitsi_jwt
    row,term,access,teacher=hybrid.guest_teacher(db,token)
    if term.delivery_mode=='onsite':raise HTTPException(404)
    if term.meeting_id:
        if get_settings(db).get('module_video','1')!='1':raise HTTPException(404)
        meeting=db.get(Meeting,term.meeting_id)
        if not meeting or meeting.cancelled_at:raise HTTPException(404)
        jwt=_jitsi_jwt(meeting.room,'seminar-teacher-'+str(access.id),teacher['name'],access.email,False,True)
        target=settings.meet_base_url+'/'+meeting.room+'?'+urlencode({'jwt':jwt})
    else:
        if not term.online_url:raise HTTPException(404)
        target=sm.safe_url(term.online_url)
    return protect(redirect(target))
