import json
import secrets
from sqlalchemy import select
from app import circulations as cl, trash
from app.db import Circulation, CirculationEvent, TrashItem
from conftest import login,csrf_of
from test_circulations import actors,make


def draft(db,user,title='Entwurf'):
    c=cl.default();c.update(title=title)
    row=Circulation(owner_id=user.id,draft_json=cl.dumps(c));db.add(row);db.commit();return row


def test_bulk_delete_files_and_restore_permissions(db,actors):
    rows=[draft(db,actors[0],f'Entwurf {n}') for n in range(2)];ids=[r.id for r in rows]
    folder=cl.files_dir(rows[0]);(folder/'test.pdf').write_bytes(b'pdf')
    owner=login(actors[0].email,'passwort-test-123');page=owner.get('/umlaeufe?tab=drafts')
    assert 'data-draft-all' in page.text and 'data-draft-select' in page.text
    r=owner.post('/umlaeufe/entwuerfe/delete',data={'csrf':csrf_of(page.text),'ids':ids})
    assert r.status_code==303
    db.expire_all();assert not db.get(Circulation,ids[0]) and not folder.exists()
    items=list(db.scalars(select(TrashItem).where(TrashItem.kind=='circulation_draft',TrashItem.row_id.in_(ids))))
    assert len(items)==2
    outsider=login(actors[3].email,'passwort-test-123');p=outsider.get('/umlaeufe/entwuerfe/papierkorb')
    assert items[0].label not in p.text
    assert outsider.post(f'/umlaeufe/entwuerfe/papierkorb/{items[0].id}/restore',data={'csrf':csrf_of(p.text)}).status_code==404
    page=owner.get('/umlaeufe/entwuerfe/papierkorb');assert page.status_code==200
    for item in items:
        assert owner.post(f'/umlaeufe/entwuerfe/papierkorb/{item.id}/restore',data={'csrf':csrf_of(page.text)}).status_code==303
    db.expire_all();assert db.get(Circulation,ids[0]) and (folder/'test.pdf').read_bytes()==b'pdf'


def test_mixed_selection_cannot_delete_published_or_foreign(db,actors):
    row=draft(db,actors[0]);published,ver,rec=make(db,actors)
    owner=login(actors[0].email,'passwort-test-123');page=owner.get('/umlaeufe?tab=drafts');token=csrf_of(page.text)
    assert owner.post('/umlaeufe/entwuerfe/delete',data={'csrf':token,'ids':[row.id,published.id]}).status_code==409
    db.expire_all();assert db.get(Circulation,row.id) and db.get(Circulation,published.id)
    other=draft(db,actors[3])
    assert owner.post('/umlaeufe/entwuerfe/delete',data={'csrf':token,'ids':[row.id,other.id]}).status_code==404
    assert owner.post('/umlaeufe/entwuerfe/delete',data={'ids':[row.id]}).status_code==400


def test_discard_preserves_publication_receipts_and_revision(db,actors):
    row,ver,rec=make(db,actors);cl.acknowledge(db,row,ver,rec,actors[1],'all','ack');db.commit()
    c=cl.content(row);c['body']='Unsaved draft';row.draft_json=cl.dumps(c);db.commit()
    owner=login(actors[0].email,'passwort-test-123');page=owner.get(f'/umlaeufe/{row.id}/edit');token=csrf_of(page.text)
    assert owner.post(f'/umlaeufe/{row.id}/discard',data={'csrf':token,'revision':'stale'}).status_code==409
    r=owner.post(f'/umlaeufe/{row.id}/discard',data={'csrf':token,'revision':row.updated_at.isoformat()});assert r.status_code==303
    db.refresh(row);db.refresh(rec)
    assert cl.content(row)==cl.content(ver) and rec.decision=='ack' and cl.receipts(db,rec)
