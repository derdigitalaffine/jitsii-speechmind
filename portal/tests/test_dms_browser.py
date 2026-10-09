import secrets
import pytest
from sqlalchemy import select
from app import dms
from app.db import DmsAccess,DmsArea,DmsFile,DmsRecord,DmsLog,User
from app.security import hash_password
from conftest import login, settings, client


@pytest.fixture
def folders(db):
    settings(module_dms='1')
    suffix=secrets.token_hex(4)
    reader=User(name='Ordnerleser',email='dms-'+suffix+'@example.org',password_hash=hash_password('dms-browser-test'),permissions='')
    root=DmsArea(name='Lesbarer Hauptordner',code='01')
    child=DmsArea(name='Lesbarer Unterordner',code='01.1')
    hidden=DmsArea(name='Geheimer Ordner')
    db.add_all([reader,root,child,hidden]);db.flush();child.parent_id=root.id
    db.add(DmsAccess(area_id=root.id,user_id=reader.id,level=1))
    records=[]
    for area,name in [(root,'Vorgang oben'),(child,'Vorgang unten'),(hidden,'Vertraulicher Vorgang')]:
        record=DmsRecord(area_id=area.id,title=name,ref_no=name,kind='manuell',text=name.lower());db.add(record);records.append(record)
    db.flush();pdf=DmsFile(record_id=records[1].id,name='Nachweis.pdf',file='abcd.pdf',mime='application/pdf',size=18)
    unsafe=DmsFile(record_id=records[1].id,name='Bild.svg',file='abcd.svg',mime='image/svg+xml',size=5)
    db.add_all([pdf,unsafe]);db.commit()
    dms.files_dir(records[1].id).mkdir(parents=True,exist_ok=True)
    (dms.files_dir(records[1].id)/pdf.file).write_bytes(b'%PDF-1.4\n%%EOF')
    (dms.files_dir(records[1].id)/unsafe.file).write_text('<svg/>')
    yield reader,root,child,hidden,records,pdf,unsafe
    for record in records:db.delete(record)
    db.flush();db.query(DmsAccess).filter(DmsAccess.user_id==reader.id).delete()
    for area in [child,root,hidden]:db.delete(area);db.flush()
    db.delete(reader);db.commit()


def test_folder_browser_direct_children_search_and_paths(db,folders):
    reader,root,child,hidden,records,pdf,unsafe=folders
    c=login(reader.email,'dms-browser-test')
    page=c.get('/dms');assert page.status_code==200
    assert root.name in page.text and hidden.name not in page.text
    assert records[1].title not in page.text
    nested=c.get('/dms',params={'area':root.id})
    assert nested.status_code==200 and child.name in nested.text
    assert records[0].title in nested.text and records[1].title not in nested.text
    nested=c.get('/dms',params={'area':child.id})
    assert records[1].title in nested.text and 'Übergeordneter Ordner' in nested.text
    assert c.get('/dms',params={'area':hidden.id}).status_code==404
    search=c.get('/dms',params={'q':'Vorgang'})
    assert records[1].title in search.text and records[2].title not in search.text
    exported=c.get('/dms/export.csv',params={'area':root.id,'scope':'folder'})
    assert records[0].title in exported.text and records[1].title not in exported.text


def test_inline_preview_keeps_source_auth_and_attachment_default(db,folders):
    reader,root,child,hidden,records,pdf,unsafe=folders
    c=login(reader.email,'dms-browser-test');base=f'/dms/r/{records[1].id}'
    page=c.get(base);assert page.status_code==200 and 'data-dms-preview' in page.text
    assert f'/dms?area={child.id}' in page.text
    url=base+f'/files/{pdf.id}'
    assert c.get(url).headers['content-disposition'].startswith('attachment')
    preview=c.get(url,params={'preview':'1'})
    assert preview.status_code==200 and preview.headers['content-disposition'].startswith('inline')
    assert preview.headers['x-frame-options']=='SAMEORIGIN'
    assert preview.headers['cache-control']=='private, no-store'
    assert client().get(url,params={'preview':'1'}).status_code!=200
    assert c.get(f'/dms/r/{records[0].id}/files/{pdf.id}',params={'preview':'1'}).status_code==404
    blocked=c.get(base+f'/files/{unsafe.id}',params={'preview':'1'})
    assert blocked.headers['content-disposition'].startswith('attachment')
    assert blocked.headers['content-type']=='application/octet-stream'


def test_plan_management_is_nested_and_existing_access_forms_remain(db,folders):
    reader,root,child,hidden,records,pdf,unsafe=folders
    admin=login('admin@example.org','admin-passwort-123')
    page=admin.get('/dms/areas')
    assert page.status_code==200 and 'dms-plan-children' in page.text
    assert f'/dms/areas/{child.id}/access' in page.text
    assert f'id="bereich-{root.id}"' in page.text
    assert login(reader.email,'dms-browser-test').get('/dms/areas').status_code==403


def test_design_system_filter_reset_preserves_folder_archive(db,folders):
    reader,root,child,hidden,records,pdf,unsafe=folders
    c=login(reader.email,'dms-browser-test')
    page=c.get('/dms',params={'area':child.id,'state':'archive','q':'nothing'})
    assert page.status_code==200
    assert f'href="/dms?area={child.id}&amp;state=archive"' in page.text
    assert 'name="state" value="archive"' in page.text
    assert 'ds-filter-chip' in page.text and 'ds-empty' in page.text
    assert 'ds-page-header' in page.text
