"""Evidence-preserving deletion and archive boundaries across all poll types."""
import json
import pytest
from fastapi import HTTPException
from app import poll_lifecycle as lifecycle
from app.db import SessionLocal, Poll, Vote, LivePoll, VoteVoter, SeminarActivity, TrashItem, User, utcnow
from app.security import new_link_token


def make(db,kind,**kwargs):
    model=lifecycle.MODELS[kind]
    data=dict(title='Lifecycle regression',owner_id=db.query(User).filter(User.is_admin.is_(True)).first().id)
    if kind=='poll':data.update(published_at=None,closed=True)
    else:data.update(public_token=new_link_token())
    data.update(kwargs)
    obj=model(**data);db.add(obj);db.flush();return obj


@pytest.mark.parametrize('kind',['poll','vote','live_poll'])
def test_unused_draft_is_recoverable_and_used_object_archives(kind):
    with SessionLocal() as db:
        obj=make(db,kind)
        admin=db.get(User,obj.owner_id)
        oid=obj.id
        assert lifecycle.removable(db,kind,obj)
        assert lifecycle.remove(db,kind,obj,admin)=='deleted'
        item=db.query(TrashItem).filter_by(kind=kind,row_id=oid).first()
        assert item is not None and item.expires_at>utcnow()
        saved=lifecycle.prepare_restore(db,kind,json.loads(item.data_json))
        top=next(r['data'] for r in saved['rows'] if r['table']==obj.__tablename__)
        assert top['archived_at'] is None
        if kind=='poll':assert top['published_at'] is None and top['closed']
        else:assert top['status']=='draft'
        db.rollback()
    with SessionLocal() as db:
        obj=make(db,kind)
        if kind=='poll':obj.published_at=utcnow()
        else:obj.opened_at=utcnow()
        db.flush()
        assert not lifecycle.removable(db,kind,obj)
        assert lifecycle.remove(db,kind,obj,db.get(User,obj.owner_id))=='archived'
        assert obj.archived_at
        with pytest.raises(HTTPException) as exc:lifecycle.mutable(obj)
        assert exc.value.status_code==409
        db.rollback()


def test_voter_registration_and_trash_references_protect_drafts():
    with SessionLocal() as db:
        vote=make(db,'vote')
        vote.voters.append(VoteVoter(source='invite',name='Guest',email='guest@example.org',token=new_link_token()))
        db.flush()
        assert not lifecycle.removable(db,'vote',vote)
        live=make(db,'live_poll')
        db.add(TrashItem(kind='seminar',label='Protected parent',table_name='seminars',row_id=99999,
            deleted_by='admin',expires_at=utcnow(),data_json=json.dumps({'rows':[{'table':'seminar_activities','data':{'kind':'live','object_id':live.id}}]})))
        db.flush()
        assert not lifecycle.removable(db,'live_poll',live)
        db.rollback()


def test_shared_editor_cannot_destructively_remove():
    with SessionLocal() as db:
        obj=make(db,'poll')
        outsider=User(id=999999,name='Editor',email='editor@example.org',is_admin=False)
        with pytest.raises(HTTPException) as exc:lifecycle.remove(db,'poll',obj,outsider)
        assert exc.value.status_code==403
        db.rollback()


def test_poll_explicit_publication_and_archive_blocks_all_mutations():
    from conftest import login,csrf_of,settings,client
    settings(module_polls='1')
    c=login('admin@example.org','admin-passwort-123')
    page=c.get('/polls/new')
    options=json.dumps([{'date':'2030-05-10','start':'10:00','end':'11:00','note':''}])
    response=c.post('/polls/new',data={'csrf':csrf_of(page.text),'title':'Lifecycle UI','options_json':options})
    assert response.status_code==303
    pid=int(response.headers['location'].split('/')[2].split('#')[0])
    page=c.get(f'/polls/{pid}')
    assert 'Veröffentlichen und öffnen' in page.text
    token=csrf_of(page.text)
    with SessionLocal() as db:
        poll=db.get(Poll,pid)
        assert poll.closed and poll.published_at is None and poll.public_token is None
    assert c.post(f'/polls/{pid}/state',data={'csrf':token,'action':'publish'}).status_code==303
    with SessionLocal() as db:
        public=db.get(Poll,pid).public_token
    assert client().get('/t/'+public).status_code==200
    assert c.post(f'/polls/{pid}/delete',data={'csrf':token}).status_code==303
    with SessionLocal() as db:
        assert db.get(Poll,pid).archived_at is not None
    assert c.post(f'/polls/{pid}/state',data={'csrf':token,'action':'reopen'}).status_code==409
    assert c.get(f'/polls/{pid}/edit').status_code==409
    assert c.get(f'/polls/{pid}/export.csv').status_code==200
    page=c.get('/t/'+public)
    assert page.status_code==200
    assert c.post('/t/'+public,data={'csrf':csrf_of(page.text),'name':'New response'}).status_code==409
    assert c.post(f'/polls/{pid}/unarchive',data={'csrf':token}).status_code==303
    with SessionLocal() as db:
        poll=db.get(Poll,pid)
        assert poll.archived_at is None and poll.closed
        db.delete(poll);db.commit()



def test_removed_invitation_does_not_make_used_draft_deletable():
    with SessionLocal() as db:
        obj=make(db,'vote')
        voter=VoteVoter(source='invite',name='Guest',email='guest@example.org',token=new_link_token())
        obj.voters.append(voter)
        lifecycle.mark_used(obj)
        db.flush()
        obj.voters.remove(voter)
        db.flush()
        assert not obj.voters and obj.status=='draft' and obj.opened_at is None
        assert not lifecycle.removable(db,'vote',obj)
        assert lifecycle.remove(db,'vote',obj,db.get(User,obj.owner_id))=='archived'
        assert obj.status=='closed' and obj.archived_at
        db.rollback()


def test_removed_share_preserves_usage_marker():
    from app.db import PollShare
    with SessionLocal() as db:
        obj=make(db,'poll')
        share=PollShare(user_id=obj.owner_id,level=1)
        obj.shares.append(share)
        lifecycle.mark_used(obj)
        db.flush()
        obj.shares.remove(share)
        db.flush()
        assert not obj.shares and obj.published_at is None
        assert not lifecycle.removable(db,'poll',obj)
        assert lifecycle.remove(db,'poll',obj,db.get(User,obj.owner_id))=='archived'
        db.rollback()
