import io
import json
import secrets
from datetime import timedelta
from sqlalchemy import select
from pypdf import PdfReader
from app import seminars as sm,seminar_learning as learning,circulations as cl
from app.db import (Form,FormResponse,SeminarActivity,SeminarMaterial,SeminarAttendance,SeminarCertificate,CirculationBundle,LawText,utcnow)
from conftest import login,client,csrf_of
from test_seminars import people,make,rec


def test_required_form_validation_real_response_and_admission(db,people):
    row,t=make(db,people)
    f=Form(owner_id=people[0].id,title='Vorabfragen',schema_json=json.dumps([{'id':'purpose','type':'short','title':'Erwartungen','required':True}]),notify=False);db.add(f);db.flush();row.form_id=f.id;db.commit()
    e=rec(db,row,t,people[1]);sm.request_place(db,row,e);db.commit();assert e.status=='form'
    c=login(people[1].email,'passwort-test-123');path=sm.personal_path(e)+'/form';p=c.get(path);assert p.status_code==200
    assert c.post(path,data={'csrf':csrf_of(p.text)}).status_code==422
    db.refresh(e);assert not e.response_id and e.status=='form'
    assert c.post(path,data={'csrf':csrf_of(p.text),'q_purpose':'Praktische Beispiele'}).status_code==303
    db.refresh(e);assert e.response_id and e.status=='confirmed'
    r=db.get(FormResponse,e.response_id);assert r.user_id==people[1].id and json.loads(r.answers_json)['purpose']=='Praktische Beispiele'
    row.form_id=None;db.flush();db.delete(r);db.delete(f);db.commit()


def test_required_anonymous_activity_stores_completion_without_identity(db,people):
    row,t=make(db,people);f=Form(owner_id=people[0].id,title='Anonyme Erwartungen',anonymous=True,notify=False,schema_json='[]');db.add(f);db.flush()
    a=SeminarActivity(seminar_id=row.id,kind='form',object_id=f.id,title=f.title,phase='before',required=True);db.add(a);db.commit()
    e=rec(db,row,t,people[1]);sm.request_place(db,row,e);db.commit();assert e.status=='form'
    c=login(people[1].email,'passwort-test-123');path=sm.personal_path(e)+'/form';p=c.get(path)
    assert c.post(path,data={'csrf':csrf_of(p.text)}).status_code==303
    db.refresh(e);assert e.status=='confirmed' and json.loads(e.activities_json)[str(a.id)] is True
    response=db.scalar(select(FormResponse).where(FormResponse.form_id==f.id));assert response.user_id is None and response.email=='' and e.response_id is None
    db.delete(a);db.delete(response);db.delete(f);db.commit()


def test_planned_materials_guest_rights_and_bundle_copy(db,people):
    row,t=make(db,people);e=sm.new_enrollment(db,row,t.id,'Gast','guest@example.org',status='confirmed');e.verified_at=utcnow()
    bundle_data=cl.default();bundle_data.update(title='Lehrmappe',items=[{'kind':'markdown','title':'Einführung','key':'m1','body':'**Hallo**','file':'intro.md'}])
    b=CirculationBundle(owner_id=people[0].id,draft_json=json.dumps(bundle_data));db.add(b);db.flush();cl.files_dir(b).joinpath('intro.md').write_text('**Hallo**')
    learning.import_bundle(db,people[0],row,b,utcnow()+timedelta(days=1));db.commit();m=db.scalar(select(SeminarMaterial).where(SeminarMaterial.seminar_id==row.id))
    c=client();assert c.get(sm.personal_path(e)+f'/materials/{m.id}').status_code==404
    m.release_at=utcnow()-timedelta(minutes=1);db.commit();p=c.get(sm.personal_path(e)+f'/materials/{m.id}');assert p.status_code==200 and '<strong>Hallo</strong>' in p.text
    assert 'intro.md'!=json.loads(m.item_json)['file'] and learning.files_dir(row).joinpath(json.loads(m.item_json)['file']).exists()
    law=LawText(title='Interne Anweisung',slug='sem-'+secrets.token_hex(4),published=True,internal=True);db.add(law);db.flush()
    protected=SeminarMaterial(seminar_id=row.id,title=law.title,item_json=json.dumps({'kind':'law','id':law.id,'title':law.title}));db.add(protected);db.commit()
    assert c.get(sm.personal_path(e)+f'/materials/{protected.id}').status_code==404
    db.delete(protected);db.delete(law);db.delete(b);db.commit()


def test_material_admin_editor_and_scheduled_access(db,people):
    row,t=make(db,people);owner=login(people[0].email,'passwort-test-123');p=owner.get(f'/seminare/{row.id}/materials');assert p.status_code==200 and 'Sammelmappe suchen' in p.text
    assert owner.post(f'/seminare/{row.id}/materials',data={'csrf':csrf_of(p.text),'action':'markdown','title':'Lehrtext','body':'## Grundlagen'}).status_code==303
    m=db.scalar(select(SeminarMaterial).where(SeminarMaterial.seminar_id==row.id));p=owner.get(f'/seminare/{row.id}/materials');token=csrf_of(p.text)
    assert owner.post(f'/seminare/{row.id}/materials/{m.id}',data={'csrf':token,'action':'save','mode':'manual','position':'1'}).status_code==303
    db.refresh(m);assert not learning.released(m)
    assert owner.post(f'/seminare/{row.id}/materials/{m.id}',data={'csrf':token,'action':'release'}).status_code==303
    db.refresh(m);assert learning.released(m)
    assert owner.get(f'/seminare/{row.id}/materials/{m.id}/preview').status_code==200


def test_attendance_qr_staff_only_and_immutable_certificates(db,people):
    row,t=make(db,people,certificates=True);e=rec(db,row,t,people[1]);sm.request_place(db,row,e);t.starts_at=utcnow()-timedelta(hours=2);t.ends_at=utcnow()-timedelta(hours=1);db.commit()
    member=login(people[1].email,'passwort-test-123');ticket=member.get(sm.personal_path(e)+'/ticket');assert ticket.status_code==200 and 'data:image/png' in ticket.text
    assert sm.decrypt(e.token_enc) not in ticket.text
    assert client().get('/seminare/check-in/'+e.checkin_hash).status_code==303
    outsider=login(people[3].email,'passwort-test-123');assert outsider.get('/seminare/check-in/'+e.checkin_hash).status_code==404
    owner=login(people[0].email,'passwort-test-123');p=owner.get(f'/seminare/{row.id}/participants');token=csrf_of(p.text)
    assert owner.post(f'/seminare/{row.id}/certificates/{e.id}',data={'csrf':token,'action':'issue'}).status_code==409
    check=owner.get('/seminare/check-in/'+e.checkin_hash);assert check.status_code==200
    assert owner.post(f'/seminare/{row.id}/attendance/{e.id}/{t.id}',data={'csrf':token,'present':'1'}).status_code==303
    assert owner.post(f'/seminare/{row.id}/certificates/{e.id}',data={'csrf':token,'action':'issue'}).status_code==303
    certificate=db.scalar(select(SeminarCertificate).where(SeminarCertificate.enrollment_id==e.id));snapshot=certificate.snapshot_json
    row.title='Geänderter Titel';db.commit();pdf=member.get(sm.personal_path(e)+'/certificate.pdf');assert pdf.status_code==200
    text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages);assert 'Testseminar' in text and 'Geänderter Titel' not in text
    assert certificate.snapshot_json==snapshot
    assert owner.post(f'/seminare/{row.id}/attendance/{e.id}/{t.id}',data={'csrf':token,'present':'0'}).status_code==409
    assert owner.post(f'/seminare/{row.id}/certificates/{e.id}',data={'csrf':token,'action':'revoke'}).status_code==303
    assert member.get(sm.personal_path(e)+'/certificate.pdf').status_code==404
    assert owner.post(f'/seminare/{row.id}/certificates/{e.id}',data={'csrf':token,'action':'issue'}).status_code==303
    assert len(list(db.scalars(select(SeminarCertificate).where(SeminarCertificate.enrollment_id==e.id))))==2


def test_csv_formula_safety_contact_policy_and_pdf_print(db,people):
    row,t=make(db,people,advanced=True,lecturers_json=json.dumps([people[2].id]));e=rec(db,row,t,people[1]);e.name='=HYPERLINK("bad")';sm.request_place(db,row,e);db.commit()
    teacher=login(people[2].email,'passwort-test-123');csv=teacher.get(f'/seminare/{row.id}/participants.csv');assert csv.status_code==200 and "'=HYPERLINK" in csv.text and e.email not in csv.text
    pdf=teacher.get(f'/seminare/{row.id}/participants.pdf');assert pdf.status_code==200
    text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages);assert 'Unterschrift' in text and e.email not in text
    assert teacher.get(f'/seminare/{row.id}/participants.pdf?tid=999999').status_code==404
