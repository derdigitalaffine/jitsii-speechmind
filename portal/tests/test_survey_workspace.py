"""Unified survey UX: direct live entry, ACL isolation, lifecycle and contextual navigation."""
import json
import re
import pytest
from sqlalchemy import delete, select
from app import live as lv
from app.db import Form, LivePoll, LiveQuestion, Poll, PollShare, SessionLocal, User, Vote, VoteShare, utcnow
from app.security import hash_password
from conftest import csrf_of, login, settings

ADMIN=('admin@example.org','admin-passwort-123')


def main(html):
    return html[html.index('<main '):html.index('</main>')]


@pytest.fixture
def people():
    settings(module_polls='1',module_forms='1')
    with SessionLocal() as db:
        rows=[]
        for email,permissions in [('survey-reader@example.org',''),('survey-other@example.org','votes,polls')]:
            row=User(name=email.split('@')[0],email=email,password_hash=hash_password('survey-password'),permissions=permissions,must_change_password=False)
            db.add(row);rows.append(row)
        db.flush()
        reader,other=rows
        live=LivePoll(owner_id=1,title='Workspace Live',public_token='workspace-live-token-long')
        private=LivePoll(owner_id=other.id,title='Workspace Secret',public_token='workspace-secret-token-long')
        vote=Vote(owner_id=other.id,title='Workspace Shared vote',public_token='workspace-vote-token-long')
        poll=Poll(owner_id=other.id,title='Workspace Shared date',closed=True,published_at=None)
        form=Form(owner_id=1,title='Workspace Standalone form',schema_json='[]')
        db.add_all([live,private,vote,poll,form]);db.flush()
        db.add_all([VoteShare(vote_id=vote.id,user_id=reader.id,level=1),PollShare(poll_id=poll.id,user_id=reader.id,level=2)])
        db.commit()
        ids={'live':live.id,'private':private.id,'vote':vote.id,'poll':poll.id,'reader':reader.id,'other':other.id,'form':form.id}
    yield ids
    with SessionLocal() as db:
        for model,key in [(Form,'form'),(LivePoll,'live'),(LivePoll,'private'),(Vote,'vote'),(Poll,'poll')]:
            row=db.get(model,ids[key])
            if row:db.delete(row)
        for key in ('reader','other'):
            row=db.get(User,ids[key])
            if row:db.delete(row)
        # Fresh direct-entry drafts created by these tests.
        for row in db.scalars(select(LivePoll).where(LivePoll.title.in_(['Live-Umfrage','Workspace Renamed']))):db.delete(row)
        db.commit()


def test_hub_keeps_forms_separate_and_filters_combined(people):
    c=login(*ADMIN)
    page=c.get('/umfragen?q=Workspace&kind=live&scope=own')
    body=main(page.text)
    assert page.status_code==200
    assert 'Workspace Live' in body and 'Workspace Secret' not in body
    assert 'Workspace Standalone form' not in body
    assert 'state=archive' in body and 'kind=live' in body and 'scope=own' in body and 'q=Workspace' in body
    assert body.count('btn-primary')==1
    assert 'Neu erstellen' in body
    assert 'Workspace Secret' in main(c.get('/umfragen?scope=portal').text)
    assert 'Workspace Shared vote' not in main(c.get('/umfragen?scope=portal&q=NotFound').text)
    assert 'Workspace Standalone form' in main(c.get('/forms').text)
    for path in ('/polls','/votes'):
        assert 'Umfragen &amp; Abstimmungen' in main(c.get(path).text)


def test_shared_reader_cannot_reveal_private_surveys_or_actions(people):
    c=login('survey-reader@example.org','survey-password')
    body=main(c.get('/umfragen?scope=portal').text)
    assert 'Workspace Shared vote' in body and 'Workspace Shared date' in body
    assert 'Workspace Secret' not in body and 'Workspace Live' not in body
    assert 'Neu erstellen' not in body
    assert 'ds-survey-card' not in main(c.get('/umfragen?q=Workspace Secret').text)
    assert c.get('/umfragen/neu').status_code==403
    assert c.get(f'/votes/live/{people["private"]}').status_code==403
    body=main(c.get(f'/votes/{people["vote"]}?tab=share').text)
    assert 'Wählerverzeichnis' not in body and 'Umfragebereiche' in body
    assert 'name="users"' not in body
    assert 'Workspace Shared vote' not in main(c.get('/umfragen?scope=own').text)


def test_direct_live_creation_without_title_is_unpublished_and_moderated(people):
    c=login(*ADMIN)
    page=c.get('/umfragen/neu')
    assert 'name="title"' not in main(page.text)
    assert 'Live-Umfrage vorbereiten' in page.text
    response=c.post('/votes/live/new',data={'csrf':csrf_of(page.text),'workspace':'1'})
    assert response.status_code==303 and '?tab=build#neu' in response.headers['location']
    pid=int(re.search(r'/live/(\d+)',response.headers['location'])[1])
    with SessionLocal() as db:
        row=db.get(LivePoll,pid)
        assert row.status=='draft' and row.pacing=='moderated' and row.opened_at is None
    page=c.get(response.headers['location'])
    body=main(page.text)
    for label in ('Fragen','Teilnahme','Durchführung','Ergebnisse','Einstellungen'):
        assert label in body
    assert 'Frageart' in body and 'name="title"' in body
    assert 'live-moderation"' not in body
    assert 'Wortwolke' in body and 'Quiz' in body


def test_live_validation_preserves_all_question_values(people):
    c=login(*ADMIN);pid=people['live'];page=c.get(f'/votes/live/{pid}?tab=build&kind=quiz')
    response=c.post(f'/votes/live/{pid}/fragen',data={'csrf':csrf_of(page.text),'kind':'quiz','title':'Workspace Quiz',
        'options':'Alpha\nBeta','correct':'9','points':'5','seconds':'45','nickname':'1','partial':'1','chart':'table','show_results':'never'})
    assert response.status_code==422
    body=main(response.text)
    for value in ('Workspace Quiz','Alpha\nBeta','value="9"','value="45"','value="5"'):
        assert value in body
    assert re.search(r'name="nickname"[^>]*checked',body)
    assert re.search(r'value="table"[^>]*selected',body)
    assert re.search(r'value="never"[^>]*selected',body)
    with SessionLocal() as db:assert not db.get(LivePoll,pid).questions


def test_live_actions_return_to_correct_area_and_cannot_redirect_outside(people):
    c=login(*ADMIN);pid=people['live'];base=f'/votes/live/{pid}'
    token=csrf_of(c.get(base).text)
    response=c.post(base+'/fragen',data={'csrf':token,'kind':'yesno','title':'Workspace First','return_tab':'build'})
    assert '?tab=build#frage-' in response.headers['location']
    c.post(base+'/fragen',data={'csrf':token,'kind':'words','title':'Workspace Second'})
    with SessionLocal() as db:ids=[q.id for q in db.get(LivePoll,pid).questions]
    response=c.post(base+'/status',data={'csrf':token,'action':'open','return_tab':'moderate'})
    assert response.headers['location']==base+'?tab=moderate'
    response=c.post(base+'/schritt',data={'csrf':token,'dir':'next','return_tab':'moderate'})
    assert response.status_code==303 and response.headers['location']==base+'?tab=moderate'
    page=main(c.get(base+'?tab=moderate').text)
    assert 'lm-title">Workspace Second' in page
    assert '/reset' not in page and 'Fragenübersicht' in page
    assert 'Beiträge aktualisieren' in page
    response=c.post(base+f'/fragen/{ids[1]}/lock',data={'csrf':token,'return_tab':'https://example.org'})
    assert response.headers['location'].startswith(base+'?tab=moderate')
    response=c.post(base+'/settings',data={'csrf':token,'title':'Workspace Renamed','pacing':'free'})
    assert response.headers['location']==base+'?tab=settings'
    assert 'Workspace Renamed' in main(c.get(base+'?tab=settings').text)


def test_archive_and_trash_are_separate_and_restore_stays_closed(people):
    c=login(*ADMIN);base=f'/votes/live/{people["live"]}'
    token=csrf_of(c.get(base).text)
    c.post(base+'/fragen',data={'csrf':token,'kind':'yesno','title':'Used question'})
    c.post(base+'/status',data={'csrf':token,'action':'open'})
    c.post(base+'/loeschen',data={'csrf':token})
    assert 'Workspace Live' not in main(c.get('/umfragen?kind=live').text)
    assert 'Workspace Live' in main(c.get('/umfragen?kind=live&state=archive').text)
    archived=main(c.get(base+'?tab=build').text)
    assert 'CSV herunterladen' in archived and '/fragen"' not in archived
    assert 'Archiviert' in archived
    c.post(base+'/unarchive',data={'csrf':token})
    with SessionLocal() as db:
        row=db.get(LivePoll,people['live']);assert row.status=='closed' and row.archived_at is None


def test_module_gates_and_creation_permissions(people):
    c=login(*ADMIN);token=csrf_of(c.get('/umfragen').text)
    settings(module_polls='0',module_forms='1')
    assert c.get('/umfragen').status_code==404 and c.get('/umfragen/neu').status_code==404
    assert c.post('/votes/live/new',data={'csrf':token,'workspace':'1'}).status_code==404
    assert c.get('/forms').status_code==200
    assert c.post('/umfragen/papierkorb/999/restore',data={'csrf':token}).status_code==404
    settings(module_polls='1')
    c=login('survey-reader@example.org','survey-password')
    token=csrf_of(c.get('/umfragen').text)
    assert c.post('/votes/live/new',data={'csrf':token,'workspace':'1'}).status_code==403


def test_quick_vote_defaults_keep_formal_rules_accessible(people):
    c=login(*ADMIN)
    body=main(c.get('/votes/new?simple=1').text)
    assert re.search(r'value="anonymous"[^>]*checked',body)
    assert re.search(r'value="public"[^>]*checked',body)
    assert re.search(r'value="live"[^>]*selected',body)
    assert 'bestätigter E-Mail-Adresse' in body
    assert 'Teilnahme & Wahlregeln' in body and 'Zugangscodes' in body and 'Geheim' in body
    assert 'id="vote-rules" >' in body
    legacy=main(c.get('/votes/new').text)
    assert re.search(r'value="secret"[^>]*checked',legacy)
    assert re.search(r'value="invite"[^>]*checked',legacy)


def test_shared_workflow_and_archive_controls_all_engines(people):
    c=login(*ADMIN)
    for base in (f'/votes/{people["vote"]}',f'/polls/{people["poll"]}'):
        for tab in ('share','conduct','results','settings'):
            body=main(c.get(base+'?tab='+tab).text)
            assert 'aria-label="Umfragebereiche"' in body
            assert body.count('aria-current="page"')==1
            assert ('data-confirm="Die Umfrage wird' in body) == (tab=='settings')
            if tab=='results':assert 'name="emails"' not in body
            if tab=='share':assert 'name="emails"' in body


def test_poll_draft_participation_and_archived_owner_controls(people):
    c=login(*ADMIN)
    page=c.get(f'/polls/{people["poll"]}?tab=share')
    body=main(page.text)
    assert 'Zur Durchführung' in body and 'value="enable_link"' not in body
    for model,key,base in [(Poll,'poll','/polls/'),(Vote,'vote','/votes/')]:
        with SessionLocal() as db:
            obj=db.get(model,people[key]);obj.archived_at=utcnow();db.commit()
        body=main(c.get(base+str(people[key])+'?tab=settings').text)
        assert 'Aus Archiv zurückholen' in body
        assert '/unarchive' in body
        assert '/edit"' not in body
