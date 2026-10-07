import json
import re
import pytest
from sqlalchemy import select
from app import circulations as cl
from app.db import CirculationBundle, Circulation, CirculationVersion, LawText, Form
from app.routes_circulations import return_path
from conftest import login, csrf_of, client, settings
from test_circulations import actors, make


@pytest.fixture
def bundles(db,actors):
    yield actors
    for bundle in db.scalars(select(CirculationBundle).where(CirculationBundle.owner_id.in_([u.id for u in actors]))):
        import shutil
        shutil.rmtree(cl.files_dir(bundle),ignore_errors=True)
        db.delete(bundle)
    db.commit()


def new_bundle(db,owner,title='Onboardingmappe',shared=False,items=None):
    c=cl.default();c.update(title=title,body='Dokumente für den Einstieg',items=items or [])
    row=CirculationBundle(owner_id=owner.id,draft_json=cl.dumps(c),shared=shared)
    db.add(row);db.commit();return row


def save_data(page,row,**values):
    return {'csrf':csrf_of(page.text),'revision':row.updated_at.isoformat(),'title':'Onboardingmappe',**values}


def test_separate_editor_reusable_choices_and_safe_return(db,bundles):
    owner=login(bundles[0].email,'passwort-test-123')
    page=owner.get('/sammelmappen');assert page.status_code==200
    created=owner.post('/sammelmappen/new',data={'csrf':csrf_of(page.text),'return_to':'https://evil.example'})
    assert created.status_code==303 and 'evil' not in created.headers['location']
    edit=owner.get(created.headers['location']);assert edit.status_code==200
    assert 'Portalobjekte hinzufügen' in edit.text and 'Textdokument direkt erstellen' in edit.text
    assert 'Empfänger festlegen' not in edit.text and 'multiple class="form-select' not in edit.text
    row,ver,rec=make(db,bundles)
    page=owner.get(f'/umlaeufe/{row.id}/edit')
    assert 'Sammelmappen auswählen' in page.text and '/sammelmappen' in page.text
    assert 'Portalobjekte hinzufügen' not in page.text and 'data-markdown-editor' in page.text
    assert return_path('//evil.example')=='' and return_path('/umlaeufe/1/edit')=='/umlaeufe/1/edit'
    bundle=new_bundle(db,bundles[0])
    selection=owner.get(f'/umlaeufe/{row.id}/edit?bundle={bundle.id}')
    assert re.search(r'data-bundle-id="'+str(bundle.id)+r'"\s+checked',selection.text)
    unavailable=owner.get(f'/umlaeufe/{row.id}/edit?bundle=999999')
    assert unavailable.status_code==200 and 'data-bundle-id="999999"' not in unavailable.text


def test_private_shared_and_proxy_permissions(db,bundles):
    own=new_bundle(db,bundles[0])
    stranger=login(bundles[3].email,'passwort-test-123')
    assert stranger.get(f'/sammelmappen/{own.id}').status_code==404
    bundles[3].permissions='circulations_create';db.commit()
    assert stranger.get(f'/sammelmappen/{own.id}').status_code==404
    own.shared=True;db.commit()
    assert stranger.get(f'/sammelmappen/{own.id}').status_code==200
    assert stranger.get(f'/sammelmappen/{own.id}/edit').status_code==404
    assert client().get(f'/sammelmappen/{own.id}').status_code in (303,401,403)
    from app.db import Absence
    db.add(Absence(user_id=bundles[0].id,substitute_id=bundles[2].id,created_by=bundles[0].id,starts_on=cl.absence.today(),ends_on=cl.absence.today(),status='confirmed'));db.commit()
    assert login(bundles[2].email,'passwort-test-123').get(f'/sammelmappen/{own.id}/edit').status_code==200


def test_upload_text_edit_import_independence_and_stale_save(db,bundles):
    owner=login(bundles[0].email,'passwort-test-123');bundle=new_bundle(db,bundles[0])
    page=owner.get(f'/sammelmappen/{bundle.id}/edit');original_revision=bundle.updated_at.isoformat()
    saved=owner.post(f'/sammelmappen/{bundle.id}/save',data=save_data(page,bundle,new_markdown_title='Checkliste',new_markdown_body='## Willkommen\n**Erster Tag**',item_sequence=json.dumps(['markdown:new','upload:0'])),files={'files':('plan.pdf',b'%PDF-1.4\n%%EOF','application/pdf')})
    assert saved.status_code==303;db.refresh(bundle)
    items=cl.content(bundle)['items'];assert [i['kind'] for i in items]==['markdown','file']
    pdf=owner.get(f'/sammelmappen/{bundle.id}/files/{items[1]["key"]}')
    assert pdf.status_code==200 and pdf.headers['x-frame-options']=='SAMEORIGIN'
    assert pdf.headers['cache-control']=='no-store'
    assert owner.post(f'/sammelmappen/{bundle.id}/save',data=save_data(page,bundle,revision=original_revision)).status_code==409
    # Publication copies both bytes and text; editing the source later cannot change the recipient's copy.
    row,ver,rec=make(db,bundles)
    page=owner.get(f'/umlaeufe/{row.id}/edit')
    imported=owner.post(f'/umlaeufe/{row.id}/save',data=save_data(page,row,title='Umlauf',kind='circulation',body='Einleitung',mode='ack',users=bundles[1].id,add_bundle=str(bundle.id),item_sequence=json.dumps([f'bundle:{bundle.id}:{i["key"]}' for i in items])))
    assert imported.status_code==303;db.refresh(row)
    copied=cl.content(row)['items'];assert len(copied)==2 and copied[0]['key']!=items[0]['key']
    assert cl.file_path(row,copied[1]).read_bytes()==cl.file_path(bundle,items[1]).read_bytes()
    published=cl.publish(db,row,bundles[0]);db.commit();frozen=cl.content(published)
    page=owner.get(f'/sammelmappen/{bundle.id}/edit')
    changed=owner.post(f'/sammelmappen/{bundle.id}/save',data=save_data(page,bundle,**{'markdown_body_'+items[0]['key']:'## Neue Fassung'}))
    assert changed.status_code==303;db.refresh(bundle)
    assert cl.content(bundle)['items'][0]['body']=='## Neue Fassung'
    assert cl.content(published)==frozen and cl.content(row)['items'][0]['body']=='## Willkommen\n**Erster Tag**'
    assert client().get(f'/sammelmappen/{bundle.id}/files/{items[1]["key"]}').status_code in (303,401,403)


def test_order_validation_rollback_and_no_duplicate_aliases(db,bundles):
    items=[{'key':'a','title':'A'},{'key':'b','title':'B'}]
    assert cl.ordered_items(items,{'item:a':items[0],'item:b':items[1]},'["item:b","item:a"]')==items[::-1]
    for raw in ('{}','["item:a"]','["item:a","item:a"]','["forged","item:b"]'):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):cl.ordered_items(items,{'item:a':items[0],'item:b':items[1]},raw)
    owner=login(bundles[0].email,'passwort-test-123');bundle=new_bundle(db,bundles[0]);page=owner.get(f'/sammelmappen/{bundle.id}/edit')
    response=owner.post(f'/sammelmappen/{bundle.id}/save',data=save_data(page,bundle,item_sequence='["forged"]'),files={'files':('bad.pdf',b'%PDF-1.4\n%%EOF','application/pdf')})
    assert response.status_code==422;db.refresh(bundle)
    assert cl.content(bundle)['items']==[] and list(cl.files_dir(bundle).iterdir())==[]


def test_portal_reference_deduplication_and_access_recheck(db,bundles):
    settings(module_forms='1')
    form=Form(title='Interne Checkliste',owner_id=bundles[0].id,public_token='bundle-test-private',internal=True,active=True)
    db.add(form);db.commit()
    bundle=new_bundle(db,bundles[0],shared=True,items=[dict(key='form',kind='form',id=form.id,title=form.title,url='/f/bundle-test-private')])
    owner=login(bundles[0].email,'passwort-test-123');row,ver,rec=make(db,bundles)
    page=owner.get(f'/umlaeufe/{row.id}/edit')
    failed=owner.post(f'/umlaeufe/{row.id}/save',data=save_data(page,row,add_bundle=bundle.id))
    assert failed.status_code==422  # creator has no internal_forms permission
    bundles[0].permissions+=',internal_forms';db.commit()
    page=owner.get(f'/umlaeufe/{row.id}/edit')
    saved=owner.post(f'/umlaeufe/{row.id}/save',data=save_data(page,row,add_bundle=bundle.id,add_form=form.id))
    assert saved.status_code==303;db.refresh(row)
    assert len(cl.content(row)['items'])==1
    db.delete(form);db.commit()


def test_blackboard_blog_excerpt_and_markdown_safety(db,bundles):
    row,ver,rec=make(db,bundles,mode='info',public=True,body='## Willkommen\n**Ein Beitrag**\n<script>alert(1)</script>')
    page=client().get('/umlaeufe?tab=board')
    assert page.status_code==200 and 'cl-blog-post' in page.text and 'Beitrag lesen' in page.text
    assert '<script>alert(1)</script>' not in page.text and '<h2>Willkommen</h2>' not in page.text
    owner=login(bundles[0].email,'passwort-test-123');edit=owner.get(f'/umlaeufe/{row.id}/edit')
    preview=owner.post('/umlaeufe/preview',data={'csrf':csrf_of(edit.text),'body':'[Bad](javascript:alert(1))\n<script>alert(1)</script>\n**Fett**'})
    assert preview.status_code==200 and '<strong>Fett</strong>' in preview.text
    assert '<script>' not in preview.text and 'href="javascript:' not in preview.text
    settings(module_circulations='0')
    assert owner.get('/sammelmappen').status_code==404
    settings(module_circulations='1')


def test_existing_draft_can_be_saved_as_independent_bundle(db,bundles):
    row,ver,rec=make(db,bundles,items=[dict(key='doc',kind='markdown',title='Checkliste',file='c'*32+'.md',mime='text/markdown',size=4,body='Test')])
    cl.file_path(row,cl.content(row)['items'][0]).write_bytes(b'Test')
    owner=login(bundles[0].email,'passwort-test-123');page=owner.get(f'/umlaeufe/{row.id}/edit')
    result=owner.post(f'/umlaeufe/{row.id}/bundle',data={'csrf':csrf_of(page.text)})
    assert result.status_code==303 and result.headers['location'].startswith('/sammelmappen/')
    bid=int(result.headers['location'].split('/')[2]);bundle=db.get(CirculationBundle,bid)
    copied=cl.content(bundle)['items'][0]
    assert copied['key']!='doc' and cl.file_path(bundle,copied).read_bytes()==b'Test'
    assert cl.content(ver)['items'][0]['key']=='doc'
