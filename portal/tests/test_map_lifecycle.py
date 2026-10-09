"""Saved-map trash recovers data but never quietly reopens historic access."""
import json
from datetime import timedelta
from sqlalchemy import select
from app.db import UserMap, TrashItem, Group, utcnow
from app import map_lifecycle, trash
from conftest import client, login, csrf_of, settings
from test_circulations import actors


def test_map_trash_restore_private_and_explicit_shares(db, actors):
    settings(module_maps='1')
    owner, guest = actors[1], actors[3]
    group = Group(name='Map recovery group')
    db.add(group); db.flush()
    saved = UserMap(owner_id=owner.id, title='Recovery map', state_json='{"center":[7,49]}',
                    share_json=json.dumps({'users':[guest.id], 'groups':[group.id]}), public_token='historic-map-link-123456')
    copy = UserMap(owner_id=guest.id, title='Independent copy', state_json=saved.state_json)
    db.add_all([saved, copy]); db.commit()
    mid, cid = saved.id, copy.id
    owner_client = login(owner.email, 'passwort-test-123')
    guest_client = login(guest.email, 'passwort-test-123')
    csrf = csrf_of(owner_client.get('/maps').text)
    guest_csrf = csrf_of(guest_client.get('/maps').text)
    assert guest_client.post(f'/maps/{mid}/delete', data={'csrf':guest_csrf}).status_code == 404
    assert owner_client.post(f'/maps/{mid}/delete', data={'csrf':csrf}).status_code == 303
    db.expire_all()
    item = db.scalar(select(TrashItem).where(TrashItem.kind=='user_map', TrashItem.row_id==mid))
    tid = item.id
    assert client().get('/karte/m/historic-map-link-123456').status_code == 404
    assert guest_client.get(f'/maps/{mid}').status_code == 404
    assert db.get(UserMap, cid).state_json == '{"center":[7,49]}'
    assert guest_client.post(f'/maps/{tid}/restore', data={'csrf':guest_csrf}).status_code == 404
    assert owner_client.get('/maps?state=trash').status_code == 200
    assert owner_client.post(f'/maps/{tid}/restore', data={'csrf':csrf}).status_code == 303
    db.expire_all(); recovered = db.get(UserMap, mid)
    assert recovered.state_json == '{"center":[7,49]}' and recovered.public_token is None
    assert json.loads(recovered.share_json) == {}
    assert guest_client.get(f'/maps/{mid}').status_code == 404
    assert 'Frühere Freigaben aktivieren' in owner_client.get('/maps').text
    assert owner_client.post(f'/maps/{mid}/restore-shares', data={'csrf':csrf}).status_code == 303
    assert guest_client.get(f'/maps/{mid}').status_code == 200
    assert client().get('/karte/m/historic-map-link-123456').status_code == 404
    db.expire_all(); db.delete(db.get(UserMap, mid)); db.delete(db.get(UserMap, cid)); db.delete(group); db.commit()


def test_map_shared_admin_restore_sanitizes_stale_identities(db, actors):
    actors[0].is_admin = True
    db.commit()
    saved = UserMap(owner_id=actors[1].id, title='Admin recovery', public_token='old-admin-map-token-123',
                    share_json=json.dumps({'users':[actors[3].id, 999999], 'groups':[999999]}))
    db.add(saved); db.commit(); mid=saved.id
    item=map_lifecycle.remove(db,saved,actors[0]);db.commit()
    assert trash.restore(db,item,actors[0].name) is None
    db.commit();db.expire_all(); restored=db.get(UserMap,mid)
    assert restored.public_token is None and json.loads(restored.share_json)=={}
    assert json.loads(restored.restore_share_json)=={'users':[actors[3].id], 'groups':[]}
    item=map_lifecycle.remove(db,restored,actors[1]);db.commit()
    item.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert not map_lifecycle.trash_access(actors[1],item)
    assert trash.restore(db,item,actors[0].name) is not None
    db.delete(item);db.commit()
