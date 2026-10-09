import secrets
from datetime import timedelta
from app import dms, dms_lifecycle as lifecycle, trash
from app.db import DmsArea, DmsFile, DmsRecord, CirculationBundle, User, utcnow


def test_archive_filter_and_owner_identity(db):
    area=DmsArea(name='Lifecycle '+secrets.token_hex(4));db.add(area);db.flush()
    record=DmsRecord(area_id=area.id,title='Archived lifecycle',archived_at=utcnow());db.add(record);db.flush()
    admin=User(id=987654,name='Admin',is_admin=True)
    other=User(id=987653,name=record.created_by,is_admin=False)
    assert lifecycle.owns(admin,record)
    assert not lifecycle.owns(other,record)
    assert record.id not in [r.id for r in dms.search(db,admin,{})[0]]
    assert record.id in [r.id for r in dms.search(db,admin,{'state':'archive'})[0]]
    db.delete(record);db.flush();db.delete(area);db.commit()


def test_retention_and_bundle_dependency_protect_whole_record(db):
    area=DmsArea(name='Dependency '+secrets.token_hex(4));db.add(area);db.flush()
    record=DmsRecord(area_id=area.id,title='Protected',retention_until=utcnow()+timedelta(days=2));db.add(record);db.flush()
    file=DmsFile(name='Proof.pdf',file='proof.pdf');record.files.append(file);db.flush()
    owner=db.query(User).first()
    bundle=CirculationBundle(owner_id=owner.id,draft_json='{"items":[{"kind":"dms","id":'+str(file.id)+'}]}');db.add(bundle);db.flush()
    reasons=lifecycle.protection(db,record)
    assert any('Aufbewahrungsfrist' in r for r in reasons)
    assert any('Sammelmappe' in r for r in reasons)
    preview=lifecycle.folder_preview(db,area.id)
    assert preview['blocked'] and preview['count']==2
    first=preview['fingerprint'];file.sha256='changed';db.flush()
    assert lifecycle.folder_preview(db,area.id)['fingerprint']!=first
    db.delete(bundle);db.delete(record);db.flush();db.delete(area);db.commit()


def test_missing_restore_folder_requires_target_and_nested_snapshot_allowed(db):
    import json
    from types import SimpleNamespace
    missing=987654321
    record={'table':'dms_records','data':{'id':987654321,'area_id':missing}}
    item=SimpleNamespace(kind='dms',data_json=json.dumps({'rows':[record]}))
    assert 'Zielordner' in lifecycle.restore_error(db,item)
    item.kind='dms_area';item.data_json=json.dumps({'rows':[{'table':'dms_areas','data':{'id':missing}},record]})
    assert lifecycle.restore_error(db,item) is None


def test_recursive_delete_client_guard_and_restore_files_and_acl(db):
    import re
    from sqlalchemy import select
    from app.db import DmsAccess, TrashItem
    from conftest import csrf_of, login, settings
    settings(module_dms='1')
    admin=db.scalar(select(User).where(User.email=='admin@example.org'))
    root=DmsArea(name='Recursive root '+secrets.token_hex(4));db.add(root);db.flush()
    child=DmsArea(name='Child',parent_id=root.id);db.add(child);db.flush()
    record=DmsRecord(area_id=child.id,owner_id=admin.id,title='Recursive proof');db.add(record);db.flush()
    file=DmsFile(name='Proof.pdf',file='proof.pdf',uploaded_by_id=admin.id);record.files.append(file)
    db.add(DmsAccess(area_id=child.id,user_id=admin.id,level=1));db.commit()
    rid,cid,record_id,file_id=root.id,child.id,record.id,file.id
    folder=dms.files_dir(record_id);folder.mkdir(parents=True,exist_ok=True);(folder/'proof.pdf').write_bytes(b'preserved')
    c=login('admin@example.org','admin-passwort-123')
    url=f'/dms/areas/{rid}/delete-preview'
    def confirmation(page):
        return {'csrf':csrf_of(page.text),'confirm':'LÖSCHEN',
                'fingerprint':re.search(r'name="fingerprint" value="([^"]+)"',page.text).group(1),
                'count':re.search(r'name="count" value="([^"]+)"',page.text).group(1)}
    page=c.get(url);assert page.status_code==200 and 'Proof.pdf' in page.text
    data=confirmation(page);data['confirm']='delete'
    assert c.post(f'/dms/areas/{rid}/delete-recursive',data=data).status_code==409
    data=confirmation(page);record.title='Changed title';record.updated_at=utcnow();db.commit()
    assert c.post(f'/dms/areas/{rid}/delete-recursive',data=data).status_code==409
    record.retention_until=utcnow()+timedelta(days=1);db.commit()
    page=c.get(url);assert 'gesperrt' in page.text
    # Reuse earlier proof: protection must be enforced by POST too.
    assert c.post(f'/dms/areas/{rid}/delete-recursive',data=confirmation(c.get(url)) if 'name="fingerprint"' in c.get(url).text else data).status_code==409
    record.retention_until=None;db.commit()
    page=c.get(url);data=confirmation(page)
    assert c.post(f'/dms/areas/{rid}/delete-recursive',data=data).status_code==303
    db.expire_all();assert db.get(DmsArea,rid) is None and db.get(DmsRecord,record_id) is None
    item=db.scalar(select(TrashItem).where(TrashItem.kind=='dms_area',TrashItem.row_id==rid));item_id=item.id
    assert not folder.exists()
    page=c.get('/dms/trash');assert c.post(f'/dms/trash/{item_id}/restore',data={'csrf':csrf_of(page.text)}).status_code==303
    db.expire_all();assert db.get(DmsArea,cid).parent_id==rid
    assert db.get(DmsFile,file_id).record_id==record_id and (folder/'proof.pdf').read_bytes()==b'preserved'
    assert db.scalar(select(DmsAccess.id).where(DmsAccess.area_id==cid)) is not None
    db.delete(db.get(DmsRecord,record_id));db.flush();db.delete(db.get(DmsArea,cid));db.flush();db.delete(db.get(DmsArea,rid));db.commit()


def test_file_owner_not_editor_and_archive_write_guard(db):
    from sqlalchemy import select
    from app.db import DmsAccess
    from app.security import hash_password
    from conftest import csrf_of, login, settings
    settings(module_dms='1')
    suffix=secrets.token_hex(4)
    owner=User(name='Owner',email=f'owner-{suffix}@example.org',password_hash=hash_password('lifecycle-test'),permissions='')
    editor=User(name='Editor',email=f'editor-{suffix}@example.org',password_hash=hash_password('lifecycle-test'),permissions='')
    area=DmsArea(name='Shared '+suffix);db.add_all([owner,editor,area]);db.flush()
    db.add_all([DmsAccess(area_id=area.id,user_id=u.id,level=2) for u in [owner,editor]])
    record=DmsRecord(area_id=area.id,owner_id=owner.id,title='Shared record');db.add(record);db.flush()
    file=DmsFile(name='Owner.txt',file='owner.txt',uploaded_by_id=owner.id);record.files.append(file);db.commit()
    folder=dms.files_dir(record.id);folder.mkdir(parents=True,exist_ok=True);(folder/file.file).write_text('owner')
    c=login(editor.email,'lifecycle-test');page=c.get(f'/dms/r/{record.id}');token=csrf_of(page.text)
    assert c.post(f'/dms/r/{record.id}/files/{file.id}/delete',data={'csrf':token}).status_code==403
    assert c.post(f'/dms/r/{record.id}/delete',data={'csrf':token}).status_code==409
    c=login(owner.email,'lifecycle-test');page=c.get(f'/dms/r/{record.id}');token=csrf_of(page.text)
    assert c.post(f'/dms/r/{record.id}/archive',data={'csrf':token}).status_code==303
    assert c.get(f'/dms/r/{record.id}/files/{file.id}').status_code==200
    archived_page=c.get(f'/dms/r/{record.id}')
    assert f'action="/dms/r/{record.id}/upload"' not in archived_page.text
    assert f'action="/dms/r/{record.id}/edit"' not in archived_page.text
    target=DmsArea(name='Archive move target '+suffix);db.add(target);db.flush()
    db.add(DmsAccess(area_id=target.id,user_id=owner.id,level=2));db.commit()
    assert c.post('/dms/move',data={'csrf':token,'ids':str(record.id),'area_id':str(target.id)}).status_code==303
    db.expire_all();assert db.get(DmsRecord,record.id).area_id==area.id
    db.delete(target);db.commit()
    assert c.post(f'/dms/r/{record.id}/edit',data={'csrf':token,'title':'Bad change'}).status_code==409
    assert c.post(f'/dms/r/{record.id}/files/{file.id}/delete',data={'csrf':token}).status_code==409
    assert c.post(f'/dms/r/{record.id}/activate',data={'csrf':token}).status_code==303
    db.expire_all();db.delete(db.get(DmsRecord,record.id));db.flush();db.delete(area);db.delete(owner);db.delete(editor);db.commit()


def test_active_sickness_link_is_protected_by_source_status(db):
    from app.db import KrankReport
    area=DmsArea(name='Sickness protection '+secrets.token_hex(4));db.add(area);db.flush()
    record=DmsRecord(area_id=area.id,title='Health record',kind='krank',status='abgeschlossen');db.add(record);db.flush()
    report=KrankReport(ref_no='LIFE-'+secrets.token_hex(6),kind='simple',status='proof_missing',dms_record_id=record.id);db.add(report);db.flush()
    assert 'Laufende Krankmeldung' in lifecycle.protection(db,record)
    report.status='done';db.flush()
    assert 'Laufende Krankmeldung' not in lifecycle.protection(db,record)
    db.delete(report);db.delete(record);db.flush();db.delete(area);db.commit()


def test_deleted_source_case_does_not_recreate_dms_and_restore_resumes(db):
    from sqlalchemy import select
    from app.db import Form, FormResponse, TrashItem
    from conftest import settings
    settings(module_dms='1')
    admin=db.scalar(select(User).where(User.is_admin.is_(True)))
    area=DmsArea(name='Source removal '+secrets.token_hex(4));db.add(area);db.flush()
    form=Form(owner_id=admin.id,title='Source case',kind='application')
    db.add(form);db.flush()
    response=FormResponse(form_id=form.id,ref_no='SOURCE-'+secrets.token_hex(4),status='done',closed_at=utcnow())
    db.add(response);db.flush()
    record=DmsRecord(area_id=area.id,title='Case retained',response_id=response.id)
    db.add(record);db.commit()
    record_id,response_id=record.id,response.id
    dms.delete_record(db,record,admin,'Test completed case removal');db.commit()
    db.expire_all();response=db.get(FormResponse,response_id)
    assert response.dms_removed and dms.sync(db,response) is None
    dms.reconcile()
    db.expire_all();assert db.get(DmsRecord,record_id) is None
    item=db.scalar(select(TrashItem).where(TrashItem.kind=='dms',TrashItem.row_id==record_id))
    assert trash.restore(db,item,admin.name) is None
    db.commit();db.expire_all()
    assert not db.get(FormResponse,response_id).dms_removed
    assert db.get(DmsRecord,record_id).response_id==response_id
    db.delete(db.get(DmsRecord,record_id));db.flush();db.delete(response);db.delete(form);db.flush();db.delete(area);db.commit()


def test_file_restore_checks_archive_and_collision_before_changing_data(db):
    import json
    from sqlalchemy import select
    from pathlib import Path
    from app.db import TrashItem
    area=DmsArea(name='Restore guard '+secrets.token_hex(4));db.add(area);db.flush()
    record=DmsRecord(area_id=area.id,title='Guarded parent');db.add(record);db.flush()
    file=DmsFile(name='Proof.txt',file='proof.txt');record.files.append(file);db.commit()
    record_id,file_id=record.id,file.id
    folder=dms.files_dir(record_id);folder.mkdir(parents=True,exist_ok=True)
    original=folder/'proof.txt';original.write_bytes(b'original proof')
    item=trash.delete_obj(db,'dms_file',file,'Test');db.commit()
    saved=Path(json.loads(item.files_json)[0][1])
    record.archived_at=utcnow();db.commit()
    assert 'reaktivieren' in trash.restore(db,item,'Test')
    assert saved.read_bytes()==b'original proof' and not original.exists()
    record.archived_at=None;db.commit();original.write_bytes(b'conflicting file')
    assert 'Konflikt' in trash.restore(db,item,'Test')
    assert db.get(DmsFile,file_id) is None and saved.read_bytes()==b'original proof'
    original.unlink()
    assert trash.restore(db,item,'Test') is None
    db.commit();assert original.read_bytes()==b'original proof'
    db.delete(record);db.flush();db.delete(area);db.commit()


def test_new_rows_do_not_reuse_recoverable_ids_even_in_a_batch(db):
    from sqlalchemy import select
    from app.db import TrashItem
    area=DmsArea(name='Reserved IDs '+secrets.token_hex(4));db.add(area);db.flush()
    old=DmsRecord(area_id=area.id,title='Recoverable');db.add(old);db.flush();old_id=old.id
    item=trash.delete_obj(db,'dms',old,'Test');db.flush()
    first=DmsRecord(area_id=area.id,title='New first')
    second=DmsRecord(area_id=area.id,title='New second')
    db.add_all([first,second]);db.flush()
    assert len({old_id,first.id,second.id})==3
    assert trash.restore(db,item,'Test') is None
    db.flush();assert db.get(DmsRecord,old_id).title=='Recoverable'
    for row in (first,second,db.get(DmsRecord,old_id)):db.delete(row)
    db.flush();db.delete(area);db.commit()


def test_restore_does_not_link_a_reused_source_id(db):
    from app.db import KrankReport
    area=DmsArea(name='Source identity '+secrets.token_hex(4));db.add(area);db.flush()
    record=DmsRecord(area_id=area.id,title='Completed source');db.add(record);db.flush()
    report=KrankReport(kind='simple',ref_no='IDENTITY-'+secrets.token_hex(4),status='done',dms_record_id=record.id)
    db.add(report);db.flush();source_id=report.id;record_id=record.id
    item=trash.delete_obj(db,'dms',record,'Test');db.flush()
    db.delete(report);db.flush()
    newer=KrankReport(kind='simple',id=source_id,ref_no='NEW-'+secrets.token_hex(4),status='done',created_at=utcnow()+timedelta(seconds=1))
    db.add(newer);db.flush()
    assert trash.restore(db,item,'Test') is None
    db.flush();db.refresh(newer)
    assert newer.dms_record_id is None
    db.delete(db.get(DmsRecord,record_id));db.delete(newer);db.flush();db.delete(area);db.commit()
