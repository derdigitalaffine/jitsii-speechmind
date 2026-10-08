import json
import pytest
from fastapi import HTTPException
from app import circulations as cl, circulation_reports as reports, notify
from app.db import Absence
from conftest import login, csrf_of
from test_circulations import actors, make


def test_reports_only_creator_not_recipients_and_safe_export(db,actors):
    row,ver,rec=make(db,actors,per_item=True,items=[{'key':'document','kind':'markdown','title':'Dokument','body':'Text'}])
    cl.acknowledge(db,row,ver,rec,actors[1],'body','ack');db.commit()
    report=reports.snapshot(db,row,ver)
    assert report['pending']==1 and report['people'][0]['done']==1 and report['completed']==0
    assert report['documents'][0]['confirmed']==1
    owner=login(actors[0].email,'passwort-test-123');recipient=login(actors[1].email,'passwort-test-123')
    page=owner.get(f'/umlaeufe/{row.id}/auswertung');assert page.status_code==200
    assert recipient.get(f'/umlaeufe/{row.id}/auswertung').status_code==404
    assert recipient.get('/umlaeufe/auswertung/export/json').json()==[]
    data=owner.get('/umlaeufe/auswertung/export/json').json()
    own=next(d for d in data if d['id']==row.id)
    assert own['recipients'][0]['confirmed_documents']==['body'] and 'token_hash' not in json.dumps(own)
    assert owner.get('/umlaeufe/auswertung/export/csv').status_code==200
    assert not reports.may_report(db,actors[1],row)


def test_document_order_enforced_on_post_and_explicit_rejection(db,actors):
    row,ver,rec=make(db,actors,mode='approval',per_item=True,require_item_sequence=True,items=[{'key':'document','kind':'markdown','title':'Dokument','body':'Text'}])
    with pytest.raises(HTTPException):cl.acknowledge(db,row,ver,rec,actors[1],'document','approved')
    cl.acknowledge(db,row,ver,rec,actors[1],'body','approved');db.commit()
    user=login(actors[1].email,'passwort-test-123');page=user.get(f'/umlaeufe/{row.id}')
    r=user.post(f'/umlaeufe/{row.id}/ack',data={'csrf':csrf_of(page.text),'version':str(ver.number),'key':'document','decision':'rejected','reason':'Bitte ändern'})
    assert r.status_code==303;db.refresh(rec);assert rec.decision=='rejected' and rec.reason=='Bitte ändern'


def test_delegated_approval_actor_and_personal_ack_separate(db,actors):
    db.add(Absence(user_id=actors[1].id,substitute_id=actors[2].id,created_by=actors[1].id,starts_on=cl.absence.today(),ends_on=cl.absence.today(),status='confirmed'));db.commit()
    row,ver,rec=make(db,actors,mode='approval',allow_proxy_approval=True)
    assert rec in cl.acting_recipients(db,ver,actors[2])
    cl.acknowledge(db,row,ver,rec,actors[2],'all','approved');db.commit()
    assert rec.recorded_by==actors[2].id and cl.receipts(db,rec)[0].method=='proxy'
    row2,ver2,rec2=make(db,actors,mode='ack',allow_proxy_approval=True)
    assert not cl.acting_recipients(db,ver2,actors[2])
    with pytest.raises(HTTPException):cl.acknowledge(db,row2,ver2,rec2,actors[2],'all','ack')


def test_aggregate_recipient_view_does_not_reveal_other_statuses(db,actors):
    row,ver,rec=make(db,actors,share_progress=True,audience={'users':[actors[1].id,actors[3].id],'groups':[],'all':False,'guests':[]})
    page=login(actors[1].email,'passwort-test-123').get(f'/umlaeufe/{row.id}')
    assert page.status_code==200 and actors[3].email not in page.text
    assert f'/umlaeufe/{row.id}/auswertung' not in page.text


def test_notification_html_call_to_action_and_escaping():
    text='Freigabe erforderlich\n\nUmlauf öffnen und entscheiden:\nhttps://portal.example.org/umlaeufe/15\nDas Öffnen allein bestätigt nichts.\n\n<script>private</script>'
    html=notify.text_to_html(text)
    assert 'padding:12px 18px' in html and 'href="https://portal.example.org/umlaeufe/15"' in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'padding:12px 18px' not in notify.text_to_html(text.replace('https://portal.example.org/umlaeufe/15','javascript:alert(1)'))
