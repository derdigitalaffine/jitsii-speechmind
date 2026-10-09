"""Teaching material, forms, polls, staff check-in and participant certificates."""
import hashlib
import io
import json
import mimetypes
import secrets
from pathlib import Path
from datetime import timedelta
from fastapi import Depends,HTTPException,Request
from fastapi.responses import FileResponse,Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import seminar_hybrid as hybrid, seminar_series as series, seminar_learning as learning, seminars as sm, circulations as cl, csvsafe, forms as fm, shares, live, votes
from .db import (Seminar,SeminarSession,SeminarEnrollment,SeminarAttendance,SeminarMaterial,SeminarActivity,SeminarCertificate,
                 CirculationBundle,Form,FormInvite,FormResponse,Vote,VoteVoter,LivePoll,User,utcnow,to_local,get_settings)
from .main import app,check_csrf,current_user,get_db,redirect,render,flash,enabled_modules
from .routes_seminars import staff_of,personal_of,protect


def form_of(db,row,rec,activity=None):
    if not rec.verified_at:raise HTTPException(403)
    fid=activity.object_id if activity else row.form_id
    if activity and not learning.activity_active(db,row,rec,activity):raise HTTPException(403)
    if not activity and rec.status!='form':raise HTTPException(409,'Kein ausstehendes Pflichtformular.')
    form=db.get(Form,fid) if fid else None
    if not form or not fm.is_open(form) or form.kind!='survey' or form.fee_json not in ('','{}') or 'forms' not in enabled_modules():raise HTTPException(409,'Dieses Formular ist derzeit nicht verfügbar. Bitte die Planung kontaktieren.')
    return form


def next_form(db,row,rec):
    if row.form_id and not rec.response_id:return None
    return next(iter(learning.required_forms(db,row,rec)),None)


def completion(db,row,rec,activity,resp):
    if activity:
        data=json.loads(rec.activities_json);data[str(activity.id)]=True;rec.activities_json=json.dumps(data)
    else:rec.response_id=resp.id
    if not resp.form.anonymous:resp.name=rec.name;resp.email=rec.email;resp.user_id=rec.user_id
    if rec.status=='form':sm.request_place(db,row,rec)
    sm.event(db,row,'form_completed',detail=f'Teilnahme {rec.id}; Abfrage {activity.id if activity else "Anmeldung"}')
    return redirect(sm.personal_path(rec))


@app.get('/seminare/p/{token}/form')
def seminar_required_form(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);activity=next_form(db,row,rec);form=form_of(db,row,rec,activity)
    from .routes_forms import _fill_page
    return protect(_fill_page(request,form,action=sm.personal_path(rec)+'/form'))


@app.post('/seminare/p/{token}/form',dependencies=[Depends(check_csrf)])
async def seminar_required_submit(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);sm.lock(db,row)
    if not sm.registration_open(db,row,rec):raise HTTPException(409,'Anmeldung geschlossen.')
    activity=next_form(db,row,rec);form=form_of(db,row,rec,activity)
    from .routes_forms import _submit
    return protect(await _submit(request,db,form,None,sm.personal_path(rec)+'/form',on_complete=lambda resp:completion(db,row,rec,activity,resp)))


@app.get('/seminare/{sid:int}/materials')
def seminar_materials(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid)
    tid=sm.integer(request.query_params.get('tid',0));terms=series.staff_terms(db,user,row)
    if not series.whole_staff(db,user,row) and not tid:tid=terms[0].id
    if not series.scope_access(db,user,row,tid):raise HTTPException(404)
    bundles=[b for b in db.scalars(select(CirculationBundle).order_by(CirculationBundle.updated_at.desc())) if learning.bundle_available(db,user,b)]
    objects=[]
    if 'forms' in enabled_modules():
        objects.extend(dict(kind='form',id=f.id,title=f.title,detail='Formular') for f in db.scalars(select(Form).where(Form.active.is_(True),Form.kind=='survey',Form.owner_id.in_(sm.absence.acting_ids(db,user)))) if f.fee_json in ('','{}'))
    if 'polls' in enabled_modules():
        objects.extend(dict(kind='vote',id=v.id,title=v.title,detail='Abstimmung') for v in db.scalars(select(Vote)) if shares.access_level(db,'vote',v,user)>=3)
        objects.extend(dict(kind='live',id=p.id,title=p.title,detail='Live-Umfrage') for p in db.scalars(select(LivePoll).where(LivePoll.owner_id==user.id)))
    return protect(render(request,'seminar_materials.html',user,row=row,role=sm.role(db,user,row),bundles=bundles,content=cl.content,
        tid=tid,terms=terms,whole_staff=series.whole_staff(db,user,row),materials=list(db.scalars(select(SeminarMaterial).where(SeminarMaterial.seminar_id==sid,SeminarMaterial.scope_id==tid).order_by(SeminarMaterial.position,SeminarMaterial.id))),
        activities=list(db.scalars(select(SeminarActivity).where(SeminarActivity.seminar_id==sid,SeminarActivity.scope_id==tid))),objects=objects,phases=learning.PHASES,local_input=sm.local_input,selected_bundle=request.query_params.get('bundle','')))


@app.post('/seminare/{sid:int}/materials',dependencies=[Depends(check_csrf)])
async def seminar_material_add(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);data=await request.form();sm.lock(db,row)
    scope=sm.integer(data.get('scope_id',0))
    if not series.scope_access(db,user,row,scope):raise HTTPException(404)
    release=sm.parse_time(data.get('release_at'),True);action=data.get('action')
    if action=='bundle':
        bundle=db.get(CirculationBundle,sm.integer(data.get('bundle_id'),1));learning.import_bundle(db,user,row,bundle,release,scope)
    elif action in {'markdown','upload'}:
        title=str(data.get('title','')).strip()[:255]
        if not title:raise HTTPException(422,'Dokumenttitel erforderlich.')
        if action=='markdown':
            body=str(data.get('body',''))
            if len(body.encode())>100000 or not body.strip():raise HTTPException(422,'Text erforderlich, maximal 100 kB.')
            item=dict(kind='markdown',title=title,body=body)
        else:
            upload=data.get('file')
            if not getattr(upload,'filename',''):raise HTTPException(422,'Datei auswählen.')
            suffix=Path(upload.filename).suffix.lower()
            allowed={'.pdf','.txt','.md','.png','.jpg','.jpeg','.docx','.xlsx','.pptx','.odt','.ods','.odp'}
            if suffix not in allowed:raise HTTPException(422,'Dateityp nicht unterstützt.')
            body=await upload.read(20*1024*1024+1)
            if len(body)>20*1024*1024:raise HTTPException(413,'Dateien maximal 20 MB.')
            filename=secrets.token_hex(16)+suffix;learning.files_dir(row).joinpath(filename).write_bytes(body)
            item=dict(kind='file',title=title,file=filename,mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream',sha256=hashlib.sha256(body).hexdigest())
        db.add(SeminarMaterial(seminar_id=sid,scope_id=scope,title=title,item_json=json.dumps(item,ensure_ascii=False),release_at=release))
    else:raise HTTPException(422)
    sm.event(db,row,'material_added',user);db.commit();return redirect(f'/seminare/{sid}/materials?tid={scope}')


@app.post('/seminare/{sid:int}/materials/{mid:int}',dependencies=[Depends(check_csrf)])
async def seminar_material_update(request:Request,sid:int,mid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);data=await request.form();sm.lock(db,row);m=db.get(SeminarMaterial,mid)
    if not m or m.seminar_id!=sid or not series.scope_access(db,user,row,m.scope_id):raise HTTPException(404)
    action=data.get('action')
    if action=='remove':db.delete(m)
    elif action=='release':m.published=True;m.manual_release=True
    else:
        mode=data.get('mode')
        if mode not in {'immediate','scheduled','manual'}:raise HTTPException(422)
        m.position=sm.integer(data.get('position',0),0,1000);m.manual_release=mode=='manual';m.published=mode!='manual';m.release_at=sm.parse_time(data.get('release_at'),True) if mode=='scheduled' else None
        if mode=='scheduled' and not m.release_at:raise HTTPException(422,'Veröffentlichungszeit erforderlich.')
    sm.event(db,row,'material_'+str(action),user,str(mid));db.commit();return redirect(f'/seminare/{sid}/materials?tid={m.scope_id}')


def material_response(db,row,m,user,back):
    item=json.loads(m.item_json)
    if not cl.item_access(db,user,item):raise HTTPException(403,'Bestehende Leserechte für dieses Portalobjekt fehlen.')
    if item['kind'] in {'law','form','dms'}:
        title,url=cl.source(db,user,item,allow_archived=True)
        return protect(render(back['request'],'seminar_material_view.html',user,row=row,title=title,url=url,kind=item['kind'],body='',back=back['url']))
    if item['kind']=='markdown':
        return protect(render(back['request'],'seminar_material_view.html',user,row=row,title=m.title,url='',kind='markdown',body=cl.markdown(item.get('body','')),back=back['url']))
    if item.get('mime')=='application/pdf':
        return protect(render(back['request'],'seminar_material_view.html',user,row=row,title=m.title,url=back['file_url'],kind='pdf',body='',back=back['url']))
    return material_file(row,m)


def material_file(row,m):
    item=json.loads(m.item_json);path=learning.files_dir(row)/Path(item.get('file','')).name
    if not path.is_file():raise HTTPException(404)
    media='application/pdf' if item.get('mime')=='application/pdf' else 'application/octet-stream'
    return protect(FileResponse(path,media_type=media,filename=m.title+(path.suffix if not m.title.lower().endswith(path.suffix) else ''),content_disposition_type='inline' if media=='application/pdf' else 'attachment',headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"}))


@app.get('/seminare/p/{token}/materials/{mid:int}')
def seminar_material_view(request:Request,token:str,mid:int,download:str='',db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);m=next((m for m in learning.available_materials(db,row,rec,user) if m.id==mid),None)
    if not m:raise HTTPException(404)
    if download:return material_file(row,m)
    return material_response(db,row,m,user,{'request':request,'url':sm.personal_path(rec),'file_url':sm.personal_path(rec)+f'/materials/{mid}?download=1'})


@app.get('/seminare/{sid:int}/materials/{mid:int}/preview')
def seminar_material_preview(request:Request,sid:int,mid:int,download:str='',user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);m=db.get(SeminarMaterial,mid)
    if not m or m.seminar_id!=sid or not series.scope_access(db,user,row,m.scope_id):raise HTTPException(404)
    if download:return material_file(row,m)
    return material_response(db,row,m,user,{'request':request,'url':f'/seminare/{sid}/materials','file_url':f'/seminare/{sid}/materials/{mid}/preview?download=1'})


@app.post('/seminare/{sid:int}/activities',dependencies=[Depends(check_csrf)])
async def seminar_activity_add(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);data=await request.form();sm.lock(db,row);key=str(data.get('object','')).split(':')
    scope=sm.integer(data.get('scope_id',0))
    if not series.scope_access(db,user,row,scope):raise HTTPException(404)
    if len(key)!=2:raise HTTPException(422)
    kind=key[0];ident=sm.integer(key[1],1);phase=data.get('phase','before')
    if phase not in learning.PHASES:raise HTTPException(422)
    model={'form':Form,'vote':Vote,'live':LivePoll}.get(kind);obj=db.get(model,ident) if model else None
    if not obj or (obj.owner_id not in sm.absence.acting_ids(db,user) and not (kind=='vote' and shares.access_level(db,'vote',obj,user)>=3)):raise HTTPException(404)
    if kind=='form' and (not obj.active or obj.kind!='survey' or obj.fee_json not in ('','{}')):raise HTTPException(422)
    required=data.get('required')=='1'
    if required and (kind!='form' or phase!='before'):raise HTTPException(422,'Verpflichtend vor Anmeldung ist für Vorabformulare möglich.')
    if required and db.scalar(select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.scope_id.in_([0,scope]) if scope else True,SeminarEnrollment.status.in_(['confirmed','offered','pending','waitlist']))):raise HTTPException(409,'Pflichtabfragen vor Beginn der Anmeldungen festlegen.')
    start=sm.parse_time(data.get('opens_at'),True);end=sm.parse_time(data.get('closes_at'),True)
    if start and end and end<=start:raise HTTPException(422,'Ende muss nach Beginn liegen.')
    db.add(SeminarActivity(seminar_id=sid,scope_id=scope,once_per_series=data.get('once_per_series')=='1' and not scope,kind=kind,object_id=ident,title=obj.title,phase=phase,required=required,opens_at=start,closes_at=end));sm.event(db,row,'activity_added',user,kind);db.commit();return redirect(f'/seminare/{sid}/materials?tid={scope}')


@app.post('/seminare/{sid:int}/activities/{aid:int}/remove',dependencies=[Depends(check_csrf)])
def seminar_activity_remove(sid:int,aid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);a=db.get(SeminarActivity,aid)
    if not a or a.seminar_id!=sid or not series.scope_access(db,user,row,a.scope_id):raise HTTPException(404)
    db.delete(a);sm.event(db,row,'activity_removed',user,str(aid));db.commit();return redirect(f'/seminare/{sid}/materials?tid={a.scope_id}')


def activity_of(db,row,rec,aid):
    a=db.get(SeminarActivity,aid)
    if not a or a.seminar_id!=row.id or not learning.activity_active(db,row,rec,a):raise HTTPException(404)
    if ('forms' if a.kind=='form' else 'polls') not in enabled_modules():raise HTTPException(404)
    return a


@app.get('/seminare/p/{token}/activities/{aid:int}')
def seminar_activity_view(request:Request,token:str,aid:int,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);a=activity_of(db,row,rec,aid)
    if a.kind=='form':
        from .routes_forms import _fill_page
        return protect(_fill_page(request,form_of(db,row,rec,a),action=sm.personal_path(rec)+f'/activities/{aid}'))
    if a.kind=='live':
        obj=db.get(LivePoll,a.object_id)
        if not obj or obj.status!='open':raise HTTPException(409,'Live-Umfrage noch nicht geöffnet.')
        return redirect('/l/'+obj.public_token)
    return protect(render(request,'seminar_activity.html',user,row=row,a=a,token=token))


@app.post('/seminare/p/{token}/activities/{aid:int}',dependencies=[Depends(check_csrf)])
async def seminar_activity_submit(request:Request,token:str,aid:int,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);sm.lock(db,row);a=activity_of(db,row,rec,aid)
    if a.kind=='form':
        from .routes_forms import _submit
        return protect(await _submit(request,db,form_of(db,row,rec,a),None,sm.personal_path(rec)+f'/activities/{aid}',on_complete=lambda resp:completion(db,row,rec,a,resp)))
    obj=db.get(Vote,a.object_id) if a.kind=='vote' else None
    if not obj or obj.status!='open':raise HTTPException(409,'Abstimmung nicht geöffnet.')
    voter=db.scalar(select(VoteVoter).where(VoteVoter.vote_id==obj.id,VoteVoter.email==rec.email))
    if not voter:
        from .security import new_link_token
        voter=VoteVoter(vote_id=obj.id,source='invite',email=rec.email,name=rec.name,user_id=rec.user_id,token=new_link_token(),confirmed=True);db.add(voter);db.flush()
    db.commit();return redirect('/v/p/'+voter.token)


@app.post('/seminare/{sid:int}/attendance/{eid:int}/{tid:int}',dependencies=[Depends(check_csrf)])
async def seminar_attendance(request:Request,sid:int,eid:int,tid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);data=await request.form();sm.lock(db,row);rec=db.get(SeminarEnrollment,eid);term=db.get(SeminarSession,tid)
    if not rec or rec.seminar_id!=sid or not term or term.seminar_id!=sid:raise HTTPException(404)
    learning.mark_attendance(db,row,rec,term,user,data.get('present')=='1');db.commit();return redirect(f'/seminare/{sid}/participants')


@app.get('/seminare/p/{token}/ticket')
def seminar_ticket(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token)
    if rec.status!='confirmed' or row.status!='published':raise HTTPException(403)
    import base64
    from . import shortlinks
    ticket=hashlib.sha256(('check-in:'+token).encode()).hexdigest()
    url=sm.links.module_url(db,'seminars',f'/seminare/check-in/{ticket}')
    png,media=shortlinks.qr_image(url,shortlinks.qr_options('png',8,'#000000','#ffffff','m',2))
    return protect(render(request,'seminar_ticket.html',user,row=row,rec=rec,qr='data:image/png;base64,'+base64.b64encode(png).decode(),url=url))


@app.get('/seminare/check-in/{ticket}')
def seminar_checkin(request:Request,ticket:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    # The QR contains a check-in-only hash, never the participant's management token.
    if len(ticket)!=64:raise HTTPException(404)
    rec=db.scalar(select(SeminarEnrollment).where(SeminarEnrollment.checkin_hash==ticket,SeminarEnrollment.status=='confirmed',SeminarEnrollment.token_expires_at>utcnow()))
    if not rec:raise HTTPException(404)
    row=db.get(Seminar,rec.seminar_id)
    row=staff_of(db,user,row.id)
    return protect(render(request,'seminar_checkin.html',user,row=row,rec=rec,terms=[t for t in sm.enrollment_sessions(db,row,rec) if series.may_term(db,user,row,t)]))


@app.post('/seminare/{sid:int}/certificates/{eid:int}',dependencies=[Depends(check_csrf)])
async def seminar_certificate_issue(request:Request,sid:int,eid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);data=await request.form();sm.lock(db,row);rec=db.get(SeminarEnrollment,eid)
    if not rec or rec.seminar_id!=sid:raise HTTPException(404)
    scope=sm.integer(data.get('scope_id',0))
    if not series.scope_access(db,user,row,scope):raise HTTPException(404)
    if data.get('action')=='revoke':
        c=db.scalar(select(SeminarCertificate).where(SeminarCertificate.enrollment_id==eid,SeminarCertificate.scope_id==scope,SeminarCertificate.revoked_at.is_(None)))
        if not c:raise HTTPException(404)
        c.revoked_at=utcnow();sm.event(db,row,'certificate_revoked',user,str(eid))
    else:learning.issue_certificate(db,row,rec,user,scope)
    db.commit();return redirect(f'/seminare/{sid}/participants')


@app.get('/seminare/p/{token}/certificate.pdf')
def seminar_certificate_download(request:Request,token:str,db:Session=Depends(get_db)):
    row,rec,user=personal_of(request,db,token);cid=sm.integer(request.query_params.get('cid',0));ids=[r.id for r in series.history(db,row,rec.email)]
    c=db.scalar(select(SeminarCertificate).where(SeminarCertificate.enrollment_id.in_(ids),SeminarCertificate.revoked_at.is_(None),SeminarCertificate.id==cid if cid else True))
    if not c:raise HTTPException(404)
    return protect(Response(learning.certificate_pdf(c),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="teilnahmebescheinigung.pdf"'}))


@app.get('/seminare/{sid:int}/participants.csv')
def seminar_participants_csv(sid:int,tid:int=0,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);context=learning.staff_context(db,row);contacts=sm.may_plan(db,user,row) or row.contact_visible
    terms=series.staff_terms(db,user,row)
    if tid and tid not in [t.id for t in terms]:raise HTTPException(404)
    allowed={t.id for t in terms if not tid or t.id==tid}
    output=io.StringIO();writer=csvsafe.writer(output,delimiter=';');writer.writerow(['Seminar','Name','Organisation','E-Mail' if contacts else '','Termin-ID','Thema','Ort','Teilnahmeart','Status','Anwesenheit','Bescheinigung'])
    for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid)):
        for term in [t for t in sm.enrollment_sessions(db,row,rec) if t.id in allowed]:writer.writerow([row.title,rec.name,rec.organization,rec.email if contacts else '',term.id,term.title,term.location,hybrid.LABELS[hybrid.mode(rec,term)],sm.STATUSES[rec.status],bool(context['attendance'].get((rec.id,term.id))),bool(context['certificates'].get(rec.id))])
    return protect(Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="seminarteilnahmen.csv"'}))


@app.get('/seminare/{sid:int}/participants.pdf')
def seminar_participants_pdf(sid:int,tid:int=0,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=staff_of(db,user,sid);terms=series.staff_terms(db,user,row)
    if tid and tid not in [t.id for t in terms]:raise HTTPException(404)
    rows=[['Name','Organisation','Teilnahmeart','Unterschrift']]
    for rec in db.scalars(select(SeminarEnrollment).where(SeminarEnrollment.seminar_id==sid,SeminarEnrollment.status=='confirmed').order_by(SeminarEnrollment.name)):
        if (not rec.scope_id or rec.scope_id in [t.id for t in terms]) and (not tid or not rec.scope_id or rec.scope_id==tid):rows.append([rec.name,rec.organization,hybrid.LABELS[hybrid.mode(rec,series.term_of(db,row,tid))] if tid else 'Siehe Einzeltermine',''])
    paragraphs=[to_local(t.starts_at).strftime('%d.%m.%Y %H:%M')+' · '+t.location for t in terms if not tid or t.id==tid]
    return protect(Response(learning.pdf_document(row.title+' · Teilnehmerliste',paragraphs,rows),media_type='application/pdf',headers={'Content-Disposition':'inline; filename="teilnehmerliste.pdf"'}))

@app.post('/seminare/{sid:int}/preview',dependencies=[Depends(check_csrf)])
async def seminar_markdown_preview(request:Request,sid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    staff_of(db,user,sid);data=await request.form()
    from fastapi.responses import HTMLResponse
    return HTMLResponse(cl.markdown(str(data.get('body',''))[:100000]))
