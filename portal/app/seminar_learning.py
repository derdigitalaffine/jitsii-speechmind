"""Reuse portal collections/forms/polls; preserve document rights and immutable certificate evidence."""
import io
import json
import secrets
import shutil
from pathlib import Path
from datetime import timedelta
from xml.sax.saxutils import escape
from fastapi import HTTPException
from sqlalchemy import select
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from . import circulations as cl, seminars as sm, forms as fm, shares
from .config import settings
from .db import (SeminarAttendance,SeminarMaterial,SeminarActivity,SeminarCertificate,SeminarEnrollment,
                 CirculationBundle,Form,Vote,VoteVoter,LivePoll,Poll,to_local,utcnow,get_settings)

# Embedded Unicode fonts avoid dependence on fonts installed on the PDF viewer/server.
_font_dir=Path(reportlab.__file__).parent/'fonts'
pdfmetrics.registerFont(TTFont('SeminarRegular',str(_font_dir/'Vera.ttf')))
pdfmetrics.registerFont(TTFont('SeminarBold',str(_font_dir/'VeraBd.ttf')))

PHASES={'before':'Vor dem Seminar','live':'Während des Seminars','after':'Nach dem Seminar'}


def required_forms(db,row,rec):
    completed=json.loads(rec.activities_json)
    return [a for a in db.scalars(select(SeminarActivity).where(SeminarActivity.seminar_id==row.id,SeminarActivity.required.is_(True),SeminarActivity.kind=='form',SeminarActivity.phase=='before')) if not completed.get(str(a.id))]


def materials_open(db,row,rec):
    terms=sm.enrollment_sessions(db,row,rec)
    return bool(rec.status=='confirmed' and row.status=='published' and terms and (not row.materials_days or utcnow()<max(t.ends_at for t in terms)+timedelta(days=row.materials_days)))


def released(material):
    return bool(material.published and (material.manual_release or not material.release_at or material.release_at<=utcnow()))


def available_materials(db,row,rec,user):
    if not materials_open(db,row,rec):return []
    return [m for m in db.scalars(select(SeminarMaterial).where(SeminarMaterial.seminar_id==row.id).order_by(SeminarMaterial.position,SeminarMaterial.id)) if released(m) and cl.item_access(db,user,json.loads(m.item_json))]


def activity_active(db,row,rec,a):
    if a.opens_at and a.opens_at>utcnow() or a.closes_at and a.closes_at<=utcnow():return False
    terms=sm.enrollment_sessions(db,row,rec)
    if not terms:return False
    if a.required and a.kind=='form' and a.phase=='before':return rec.status in {'form','confirmed'}
    if rec.status!='confirmed' or row.status!='published':return False
    now=utcnow()
    if a.phase=='before':return now<max(t.starts_at for t in terms)
    if a.phase=='live':return any(t.starts_at-timedelta(minutes=30)<=now<=t.ends_at+timedelta(minutes=30) for t in terms)
    return now>=min(t.ends_at for t in terms)


def participant_context(db,row,rec,user):
    activities=[]
    for a in db.scalars(select(SeminarActivity).where(SeminarActivity.seminar_id==row.id).order_by(SeminarActivity.id)):
        if not activity_active(db,row,rec,a):continue
        module='forms' if a.kind=='form' else 'polls'
        if get_settings(db).get('module_'+module,'1')!='1':continue
        if a.kind=='form':
            f=db.get(Form,a.object_id)
            if not f or (f.internal and (not user or not user.can('internal_forms'))):continue
        activities.append(dict(title=a.title,phase_label=PHASES[a.phase],url=sm.personal_path(rec)+f'/activities/{a.id}',required=a.required))
    cert=db.scalar(select(SeminarCertificate).where(SeminarCertificate.enrollment_id==rec.id,SeminarCertificate.revoked_at.is_(None)))
    return {'materials':available_materials(db,row,rec,user),'activities':activities,'certificate':cert}


def staff_context(db,row):
    ids=select(SeminarEnrollment.id).where(SeminarEnrollment.seminar_id==row.id)
    return {'attendance':{(a.enrollment_id,a.session_id):a.present for a in db.scalars(select(SeminarAttendance).where(SeminarAttendance.enrollment_id.in_(ids)))},
        'certificates':{c.enrollment_id:c for c in db.scalars(select(SeminarCertificate).where(SeminarCertificate.enrollment_id.in_(ids),SeminarCertificate.revoked_at.is_(None)))}}


def files_dir(row):
    folder=settings.data_dir/'seminars'/str(row.id);folder.mkdir(parents=True,exist_ok=True);return folder


def bundle_available(db,user,b):
    if get_settings(db).get('module_circulations','1')!='1':return False
    return bool(b and (user.is_admin or b.shared or b.owner_id in sm.absence.acting_ids(db,user)) and all(cl.item_access(db,user,i) for i in cl.content(b)['items']))


def import_bundle(db,user,row,bundle,release_at=None):
    if not bundle_available(db,user,bundle):raise HTTPException(404)
    source=cl.files_dir(bundle)
    for original in cl.content(bundle)['items']:
        item=dict(original)
        if item['kind'] in {'file','markdown'}:
            source_path=source/Path(item['file']).name
            if not source_path.is_file():raise HTTPException(409,'Eine Datei der Sammelmappe fehlt.')
            item['file']=secrets.token_hex(16)+source_path.suffix;shutil.copyfile(source_path,files_dir(row)/item['file'])
        else:cl.source(db,user,item)
        item.update(bundle_id=bundle.id,bundle_title=cl.content(bundle)['title'])
        db.add(SeminarMaterial(seminar_id=row.id,title=item['title'],item_json=json.dumps(item,ensure_ascii=False),release_at=release_at))
    sm.event(db,row,'bundle_imported',user,str(bundle.id))


def mark_attendance(db,row,rec,term,user,present):
    if rec.status!='confirmed' or term not in sm.enrollment_sessions(db,row,rec):raise HTTPException(409,'Nur bestätigte Teilnahme am passenden aktiven Termin erfassen.')
    if utcnow()<term.starts_at-timedelta(minutes=30):raise HTTPException(409,'Anwesenheit frühestens 30 Minuten vor Beginn erfassen.')
    if not present and db.scalar(select(SeminarCertificate.id).where(SeminarCertificate.enrollment_id==rec.id,SeminarCertificate.revoked_at.is_(None))):raise HTTPException(409,'Zuerst die ausgestellte Bescheinigung widerrufen.')
    a=db.scalar(select(SeminarAttendance).where(SeminarAttendance.enrollment_id==rec.id,SeminarAttendance.session_id==term.id))
    if not a:a=SeminarAttendance(enrollment_id=rec.id,session_id=term.id,recorded_by=user.id);db.add(a)
    a.present=present;a.recorded_by=user.id;a.recorded_at=utcnow();sm.event(db,row,'attendance',user,f'{rec.id}/{term.id}: {present}')


def issue_certificate(db,row,rec,user):
    if not row.certificates or rec.status!='confirmed' or row.status!='published':raise HTTPException(409,'Bescheinigungen nur für bestätigte Teilnahmen an aktiven Veranstaltungen.')
    terms=sm.enrollment_sessions(db,row,rec)
    if not terms or any(t.ends_at>utcnow() for t in terms):raise HTTPException(409,'Erst nach Ende der gebuchten Termine ausstellen.')
    present={a.session_id for a in db.scalars(select(SeminarAttendance).where(SeminarAttendance.enrollment_id==rec.id,SeminarAttendance.present.is_(True)))}
    total=sum((t.ends_at-t.starts_at).total_seconds() for t in terms)
    attended=sum((t.ends_at-t.starts_at).total_seconds() for t in terms if t.id in present)
    if not attended or attended*100<total*row.certificate_percent:raise HTTPException(409,'Erfasste Anwesenheit erfüllt die Mindestteilnahme noch nicht.')
    cert=db.scalar(select(SeminarCertificate).where(SeminarCertificate.enrollment_id==rec.id,SeminarCertificate.revoked_at.is_(None)))
    if cert:
        return cert
    from . import branding
    snap=dict(name=rec.name,organization=rec.organization,title=row.title,issuer=row.issuer or branding.load()['name'],minutes=round(attended/60),
        dates=[{'start':t.starts_at.isoformat(),'end':t.ends_at.isoformat(),'title':t.title} for t in terms if t.id in present])
    cert=SeminarCertificate(enrollment_id=rec.id,snapshot_json=json.dumps(snap,ensure_ascii=False),issued_by=user.id)
    db.add(cert);sm.event(db,row,'certificate_issued',user,str(rec.id));sm.mail(db,row,rec,'Teilnahmebescheinigung verfügbar','Ihre Teilnahmebescheinigung steht im persönlichen Bereich zum Download bereit.')
    return cert


def pdf_document(title,paragraphs,table=None):
    output=io.BytesIO();styles=getSampleStyleSheet();styles['Title'].fontName='SeminarBold';styles['BodyText'].fontName='SeminarRegular';story=[Paragraph(escape(title),styles['Title']),Spacer(1,18)]
    for p in paragraphs:story.extend([Paragraph(escape(str(p)),styles['BodyText']),Spacer(1,10)])
    if table:
        rows=[[Paragraph(escape(str(x)),styles['BodyText']) for x in r] for r in table]
        grid=Table(rows,repeatRows=1,colWidths=[180,180,150]);grid.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.lightgrey),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),14)]));story.append(grid)
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('SeminarRegular',8);canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(40,25,'Seminare und Lehrgänge');canvas.drawRightString(doc.pagesize[0]-40,25,f'Seite {doc.page}');canvas.restoreState()
    SimpleDocTemplate(output,title=title,rightMargin=40,leftMargin=40,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()


def certificate_pdf(cert):
    data=json.loads(cert.snapshot_json)
    return pdf_document('Teilnahmebescheinigung',[data['issuer'],data['name']+((' · '+data['organization']) if data['organization'] else ''),
        'hat an „'+data['title']+'“ teilgenommen.',f'Bestätigter Umfang: {data["minutes"]} Minuten.',
        *[to_local(__import__('datetime').datetime.fromisoformat(d['start'])).strftime('%d.%m.%Y %H:%M')+' – '+to_local(__import__('datetime').datetime.fromisoformat(d['end'])).strftime('%H:%M') for d in data['dates']],
        'Ausgestellt am '+to_local(cert.issued_at).strftime('%d.%m.%Y')+f' · Nachweis {cert.id}'])
