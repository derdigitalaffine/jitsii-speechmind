import json
import secrets

import pytest
from sqlalchemy import select

from app import bundle_lifecycle as bl, circulations as cl, trash
from app.db import Circulation, CirculationBundle, TrashItem, User, utcnow
from conftest import csrf_of, login, settings


@pytest.fixture
def bundle_people(db):
    from app.main import hash_password
    settings(module_circulations='1')
    suffix=secrets.token_hex(4)
    people=[]
    for role in ('owner','other','manager'):
        user=User(name=role,email=f'bundle-{role}-{suffix}@example.org',password_hash=hash_password('passwort-test-123'),permissions='circulations_create'+(',circulations_manage' if role=='manager' else ''),active=True)
        db.add(user);people.append(user)
    db.commit()
    yield people
    db.rollback()
    ids=[p.id for p in people]
    for item in db.scalars(select(TrashItem).where(TrashItem.kind=='circulation_bundle')):
        if any(bl.trash_access(p,item) for p in people):trash.purge(db,item,'test')
    db.query(CirculationBundle).filter(CirculationBundle.owner_id.in_(ids)).delete()
    db.query(Circulation).filter(Circulation.owner_id.in_(ids)).delete()
    for person in people:db.delete(person)
    db.commit()


def make(db,owner,shared=False):
    content=cl.default();content['title']='Testmappe'
    bundle=CirculationBundle(owner_id=owner.id,draft_json=cl.dumps(content),shared=shared)
    db.add(bundle);db.commit();return bundle


def test_unused_own_bundle_roundtrip_preserves_files_and_owner_access(db,bundle_people):
    owner,other,manager=bundle_people
    bundle=make(db,owner);bid=bundle.id
    folder=cl.files_dir(bundle);folder.mkdir(parents=True,exist_ok=True);(folder/'test.pdf').write_bytes(b'%PDF-test')
    with login(owner.email,'passwort-test-123') as c:
        csrf=csrf_of(c.get('/sammelmappen').text)
        response=c.post(f'/sammelmappen/{bid}/delete',data={'csrf':csrf},follow_redirects=False)
        assert response.status_code==303
        db.expire_all();assert db.get(CirculationBundle,bid) is None
        item=db.scalar(select(TrashItem).where(TrashItem.kind=='circulation_bundle',TrashItem.row_id==bid))
        assert item and 29 < (item.expires_at-utcnow()).total_seconds()/86400 <= 30
        assert not folder.exists()
        assert bl.trash_access(owner,item) and not bl.trash_access(other,item) and not bl.trash_access(manager,item)
        response=c.post(f'/sammelmappen/papierkorb/{item.id}/restore',data={'csrf':csrf},follow_redirects=False)
        assert response.status_code==303
        db.expire_all();assert db.get(CirculationBundle,bid).owner_id==owner.id
        assert (folder/'test.pdf').read_bytes()==b'%PDF-test'
    import shutil
    shutil.rmtree(folder)


def test_used_or_shared_bundle_archives_without_destroying_historical_source(db,bundle_people):
    owner,other,_=bundle_people
    bundle=make(db,owner)
    content=cl.default();content['title']='Copied';content['items']=[{'kind':'law','key':'key','id':1,'title':'Document','bundle_id':bundle.id,'bundle_title':'Testmappe'}]
    circulation=Circulation(owner_id=owner.id,draft_json=cl.dumps(content));db.add(circulation);db.commit()
    assert bl.used(db,bundle) and not bl.removable(db,bundle)
    with login(owner.email,'passwort-test-123') as c:
        csrf=csrf_of(c.get('/sammelmappen').text)
        assert c.post(f'/sammelmappen/{bundle.id}/delete',data={'csrf':csrf}).status_code==409
        assert c.post(f'/sammelmappen/{bundle.id}/archive',data={'csrf':csrf},follow_redirects=False).status_code==303
        db.expire_all();assert bundle.archived
        from app.routes_circulations import available_bundles
        assert bundle not in available_bundles(db,owner)
        assert bundle in available_bundles(db,owner,include_archived=True)
        assert json.loads(circulation.draft_json)['items'][0]['bundle_id']==bundle.id
        assert c.get(f'/sammelmappen/{bundle.id}/edit',follow_redirects=False).status_code==303
        assert c.post(f'/sammelmappen/{bundle.id}/archive',data={'csrf':csrf},follow_redirects=False).status_code==303
        db.expire_all();assert not bundle.archived
    shared=make(db,owner,True)
    assert not bl.removable(db,shared)
    with pytest.raises(ValueError):trash.delete_obj(db,'circulation_bundle',shared,owner.email)


def test_edit_manager_can_archive_but_cannot_delete_another_owners_bundle(db,bundle_people):
    owner,_,manager=bundle_people;bundle=make(db,owner)
    from app.routes_circulations import bundle_may_edit
    assert bundle_may_edit(db,manager,bundle) and not bl.may_remove(manager,bundle)
    with login(manager.email,'passwort-test-123') as c:
        csrf=csrf_of(c.get('/sammelmappen').text)
        assert c.post(f'/sammelmappen/{bundle.id}/delete',data={'csrf':csrf}).status_code==404
        assert c.post(f'/sammelmappen/{bundle.id}/archive',data={'csrf':csrf},follow_redirects=False).status_code==303


def test_usage_detects_trashed_drafts(db,bundle_people):
    owner,_,_=bundle_people;bundle=make(db,owner)
    content=cl.default();content['items']=[{'bundle_id':bundle.id}]
    row=Circulation(owner_id=owner.id,draft_json=cl.dumps(content));db.add(row);db.commit()
    item=trash.delete_obj(db,'circulation_draft',row,owner.email);db.commit()
    assert bl.used(db,bundle)
    trash.purge(db,item,owner.email);db.commit()
    assert not bl.used(db,bundle)
