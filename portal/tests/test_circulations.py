import hashlib
import json
import secrets
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import circulations as cl
from app.db import (Absence, Circulation, CirculationDistributor, CirculationEvent, CirculationReceipt,
                    CirculationRecipient, CirculationVersion, Group, User, SessionLocal, utcnow)
from conftest import client, csrf_of, login, settings


@pytest.fixture
def actors(db):
    settings(module_circulations='1')
    suffix=secrets.token_hex(4)
    people=[]
    for name in ['owner','recipient','proxy','stranger']:
        from app.main import hash_password
        u=User(name=name,email=f'cl-{name}-{suffix}@example.org',password_hash=hash_password('passwort-test-123'),
               permissions='circulations_create,circulations_publish' if name=='owner' else '',active=True)
        db.add(u);people.append(u)
    db.commit()
    yield people
    for row in db.scalars(select(Circulation).where(Circulation.owner_id.in_([u.id for u in people]))):
        versions=list(db.scalars(select(CirculationVersion).where(CirculationVersion.circulation_id==row.id)))
        for v in versions:
            for r in cl.recipients(db,v):
                for receipt in cl.receipts(db,r):db.delete(receipt)
                db.query(CirculationEvent).filter(CirculationEvent.recipient_id==r.id).delete()
                db.delete(r)
            db.query(CirculationEvent).filter(CirculationEvent.version_id==v.id).delete()
            db.flush();db.delete(v)
        db.query(CirculationEvent).filter(CirculationEvent.circulation_id==row.id).delete()
        db.flush();db.delete(row)
    db.query(Absence).filter(Absence.user_id.in_([u.id for u in people])).delete()
    db.query(CirculationDistributor).filter(CirculationDistributor.owner_id.in_([u.id for u in people])).delete()
    db.flush()
    for u in people:db.delete(u)
    db.commit()


def make(db, people, **opts):
    c=cl.default();c.update(title='Onboarding',body='**Willkommen**',mode='ack');c.update(opts)
    
    if 'audience' not in opts:c['audience']['users']=[people[1].id]
    row=Circulation(owner_id=people[0].id,draft_json=cl.dumps(c));db.add(row);db.flush()
    ver=cl.publish(db,row,people[0]);db.commit()
    return row,ver,cl.own_recipient(db,ver,people[1])


def test_versions_receipts_and_carry_are_distinct(db,actors):
    row,ver,rec=make(db,actors)
    cl.acknowledge(db,row,ver,rec,actors[1],'all','ack');db.commit()
    original=cl.content(ver)
    c=cl.content(row);c['body']='Neue Fassung';row.draft_json=cl.dumps(c)
    second=cl.publish(db,row,actors[0],reack=True);db.commit()
    assert cl.content(ver)==original and not cl.own_recipient(db,second,actors[1]).decision
    with pytest.raises(HTTPException):cl.acknowledge(db,row,ver,rec,actors[1],'all','ack')
    third=cl.publish(db,row,actors[0],reack=False);db.commit()
    # The immediate prior version was unconfirmed, so nothing can be carried forward.
    assert not cl.own_recipient(db,third,actors[1]).decision
    cl.acknowledge(db,row,third,cl.own_recipient(db,third,actors[1]),actors[1],'all','ack');db.commit()
    fourth=cl.publish(db,row,actors[0],reack=False);db.commit()
    assert cl.own_recipient(db,fourth,actors[1]).decision=='carried'


def test_proxy_can_edit_but_not_ack_for_owner_or_recipient(db,actors):
    row,ver,rec=make(db,actors)
    db.add(Absence(user_id=actors[0].id,substitute_id=actors[2].id,created_by=actors[0].id,
                   starts_on=cl.absence.today(),ends_on=cl.absence.today(),status='confirmed'));db.commit()
    assert cl.may_edit(db,actors[2],row)
    with pytest.raises(HTTPException) as err:cl.acknowledge(db,row,ver,rec,actors[2],'all','ack')
    assert err.value.status_code==403 and not rec.decision


def test_guest_token_is_hashed_revocable_and_has_no_get_confirmation(db,actors):
    row,ver,rec=make(db,actors,audience={'users':[actors[1].id],'groups':[],'all':False,'guests':[{'name':'Gast','email':'guest@example.org'}]})
    guest=next(r for r in cl.recipients(db,ver) if not r.user_id)
    url=cl.guest_url(db,row,ver,guest);db.commit();token=url.rsplit('/',1)[-1]
    assert guest.token_hash!=token
    c=client();page=c.get('/umlaeufe/g/'+token)
    assert page.status_code==200 and not guest.decision and page.headers['referrer-policy']=='no-referrer'
    assert c.get(f'/umlaeufe/{row.id}').status_code==404
    response=c.post('/umlaeufe/g/'+token+'/ack',data={'csrf':csrf_of(page.text),'confirm':'1','decision':'ack','key':'all'})
    assert response.status_code==303
    db.refresh(guest);assert guest.decision=='ack'
    guest.token_hash=None;db.commit();assert c.get('/umlaeufe/g/'+token).status_code==404


def test_sequential_approval_rejection_stops_following_station(db,actors):
    row,ver,_=make(db,actors,sequential=True,mode='approval',audience={'users':[actors[1].id,actors[2].id],'groups':[],'all':False,'guests':[]})
    one,two=cl.recipients(db,ver)
    assert cl.ready(db,ver,one) and not cl.ready(db,ver,two)
    cl.acknowledge(db,row,ver,one,actors[1],'all','rejected','Bitte korrigieren');db.commit()
    assert not cl.ready(db,ver,two)


def test_per_document_requires_each_and_does_not_complete_on_open(db,actors):
    row,ver,rec=make(db,actors,per_item=True,items=[dict(key='document',kind='file',title='Anlage',file='a'*32+'.pdf',mime='application/pdf',size=5,sha256='x')])
    cl.acknowledge(db,row,ver,rec,actors[1],'body','ack');db.commit();assert not rec.decision
    cl.acknowledge(db,row,ver,rec,actors[1],'document','ack');db.commit();assert rec.decision=='ack'
    assert len(cl.receipts(db,rec))==2


def test_scheduled_and_expired_cannot_be_acknowledged(db,actors):
    row,ver,rec=make(db,actors,publish_on=(utcnow()+timedelta(days=2)).isoformat())
    assert not cl.active(row,ver)
    with pytest.raises(HTTPException):cl.acknowledge(db,row,ver,rec,actors[1],'all','ack')


def test_private_routes_exports_and_markdown_sanitization(db,actors):
    row,ver,rec=make(db,actors)
    stranger=login(actors[3].email,'passwort-test-123')
    assert stranger.get(f'/umlaeufe/{row.id}').status_code==404
    assert stranger.get(f'/umlaeufe/{row.id}/export/json').status_code==404
    owner=login(actors[0].email,'passwort-test-123')
    assert owner.get(f'/umlaeufe/{row.id}/edit').status_code==200
    assert owner.get(f'/umlaeufe/{row.id}').status_code==200
    for fmt in ['json','csv','pdf','signatures']:assert owner.get(f'/umlaeufe/{row.id}/export/{fmt}').status_code==200
    assert '<script>' not in cl.markdown('<script>alert(1)</script> [test](javascript:alert(1))')
    assert '<a href="javascript:' not in cl.markdown('[test](javascript:alert(1))')


def test_module_disable_blocks_guest_and_signed_in(db,actors):
    row,ver,rec=make(db,actors)
    settings(module_circulations='0')
    assert client().get('/umlaeufe').status_code==404
    settings(module_circulations='1')


def test_editor_save_and_publish_integration(db,actors):
    owner=login(actors[0].email,'passwort-test-123');page=owner.get('/umlaeufe')
    new=owner.post('/umlaeufe/new',data={'csrf':csrf_of(page.text)})
    edit=owner.get(new.headers['location']);assert edit.status_code==200
    import re
    rev=re.search(r'name="revision" value="([^"]+)"',edit.text).group(1)
    cid=int(new.headers['location'].split('/')[-2])
    result=owner.post(f'/umlaeufe/{cid}/save',data={'csrf':csrf_of(edit.text),'revision':rev,'title':'Dienstanweisung','body':'Test','mode':'ack','users':str(actors[1].id)})
    assert result.status_code==303
    edit=owner.get(new.headers['location']);rev=re.search(r'name="revision" value="([^"]+)"',edit.text).group(1)
    result=owner.post(f'/umlaeufe/{cid}/publish',data={'csrf':csrf_of(edit.text),'revision':rev})
    assert result.status_code==303
    recipient=login(actors[1].email,'passwort-test-123');detail=recipient.get(f'/umlaeufe/{cid}')
    assert detail.status_code==200 and 'Entwurf bearbeiten' not in detail.text
    assert 'Umläufe &amp; Kenntnisnahmen' in recipient.get('/').text


def test_dispatch_worker_dynamic_membership_and_no_proxy_copy(db,actors,monkeypatch):
    row,ver,rec=make(db,actors,dynamic=True,audience={'users':[actors[1].id],'groups':[],'all':False,'guests':[]})
    sent=[]
    monkeypatch.setattr(cl.notify,'mail_configured',lambda cfg:True)
    monkeypatch.setattr(cl.notify,'enqueue',lambda db,email,*a,**kw: sent.append(email) or True)
    assert cl.dispatch(db,row,ver)==1
    assert cl.dispatch(db,row,ver)==0
    rec.notified_at=utcnow()-timedelta(days=4);db.commit()
    assert cl.dispatch(db,row,ver,reminders=True)==1
    assert sent==[actors[1].email,actors[1].email]
    assert 'circulation_personal' not in cl.absence.FORWARD_KINDS
    group=Group(name='CL dynamic');group.members.append(actors[1]);db.add(group);db.flush()
    c=cl.content(row);c['audience']['groups']=[group.id];row.draft_json=cl.dumps(c)
    new=cl.publish(db,row,actors[0]);db.commit()
    group.members.append(actors[2]);db.commit()
    cl.sync_audience(db,row,new);db.commit()
    assert cl.own_recipient(db,new,actors[2])
    group.members.clear();db.delete(group);db.commit()


def test_upload_preview_keeps_auth_and_stale_save_is_rejected(db,actors):
    row,ver,rec=make(db,actors)
    owner=login(actors[0].email,'passwort-test-123')
    edit=owner.get(f'/umlaeufe/{row.id}/edit')
    rev=row.updated_at.isoformat()
    saved=owner.post(f'/umlaeufe/{row.id}/save',data={'csrf':csrf_of(edit.text),'revision':rev,'title':'PDF','body':'Text','mode':'ack','users':actors[1].id},files={'files':('test.pdf',b'%PDF-1.4\n%%EOF','application/pdf')})
    assert saved.status_code==303
    db.refresh(row);new=cl.publish(db,row,actors[0]);db.commit()
    item=cl.content(new)['items'][0];url=f'/umlaeufe/{row.id}/files/{item["key"]}'
    assert client().get(url).status_code==404
    recipient=login(actors[1].email,'passwort-test-123');pdf=recipient.get(url)
    assert pdf.status_code==200 and pdf.headers['content-disposition'].startswith('inline')
    assert pdf.headers['x-frame-options']=='SAMEORIGIN'
    assert owner.post(f'/umlaeufe/{row.id}/save',data={'csrf':csrf_of(edit.text),'revision':rev}).status_code==409
    assert owner.post(f'/umlaeufe/{row.id}/publish',data={'revision':row.updated_at.isoformat()}).status_code==400


def test_revoked_guests_are_not_reactivated_by_reminders(db,actors,monkeypatch):
    row,ver,rec=make(db,actors,audience={'users':[],'groups':[],'all':False,'guests':[{'name':'Gast','email':'revoked@example.org'}]})
    guest=cl.recipients(db,ver)[0]
    cl.guest_url(db,row,ver,guest)
    guest.token_hash=None;guest.notified_at=utcnow()-timedelta(days=4)
    monkeypatch.setattr(cl.notify,'mail_configured',lambda cfg:True)
    monkeypatch.setattr(cl.notify,'enqueue',lambda *a,**k:pytest.fail('Revoked guest must not get a fresh capability'))
    assert cl.dispatch(db,row,ver,reminders=True)==0
    assert not guest.token_hash


def test_public_board_is_listed_only_when_available(db,actors):
    from app import public_nav
    public_nav.invalidate()
    assert not cl.public_available(db)
    row,ver,rec=make(db,actors,mode='info',public=True)
    assert cl.public_available(db)
    entries=public_nav.entries(db,cl.get_settings(db),{'circulations'})
    assert next(e for e in entries if e['key']=='aushang')['available']
    row.archived=True;db.commit();assert not cl.public_available(db)
    public_nav.invalidate()


def test_markdown_documents_render_safely_and_are_frozen(db,actors):
    row,ver,rec=make(db,actors,items=[dict(key='md',kind='markdown',title='Checkliste',file='b'*32+'.md',mime='text/markdown',size=10,body='## Checkliste\n<script>alert(1)</script>')])
    c=login(actors[1].email,'passwort-test-123');page=c.get(f'/umlaeufe/{row.id}')
    assert page.status_code==200 and '<h2>Checkliste</h2>' in page.text
    assert '<script>alert(1)</script>' not in page.text


def test_confirmation_opens_next_station_and_custom_category_is_filterable(db,actors):
    row,ver,rec=make(db,actors,category='Eigene Kategorie',sequential=True,audience={'users':[actors[1].id,actors[2].id],'groups':[],'all':False,'guests':[]})
    next_rec=cl.own_recipient(db,ver,actors[2]);assert not cl.ready(db,ver,next_rec)
    cl.acknowledge(db,row,ver,rec,actors[1],'all','ack');db.commit()
    assert cl.ready(db,ver,next_rec)
    c=login(actors[2].email,'passwort-test-123')
    page=c.get('/umlaeufe',params={'category':'Eigene Kategorie'})
    assert page.status_code==200 and '<option selected>Eigene Kategorie</option>' in page.text
    assert row.id in {item['row'].id for item in cl.overview(db,actors[2])['items']}
