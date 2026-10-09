"""Quiz/ranking remain anonymous, hide solutions, and share server-side moderation rules."""
import json
import time
import pytest
from sqlalchemy import delete
from app import live as lv
from app.db import LiveAnswer, LivePoll, LiveQuestion, SessionLocal
from conftest import csrf_of, login, client, settings

@pytest.fixture(autouse=True)
def clean():
    settings(module_polls="1")
    with SessionLocal() as db:
        db.execute(delete(LivePoll)); db.commit()

def setup(pacing="free", seconds=0):
    staff = login("admin@example.org", "admin-passwort-123")
    csrf = csrf_of(staff.get('/votes').text)
    response = staff.post('/votes/live/new', data=dict(csrf=csrf, title='Quiz', pacing=pacing))
    path = response.headers['location']
    csrf = csrf_of(staff.get(path).text)
    for data in [dict(kind='quiz', title='Mehrere Lösungen', options='A\nB\nC', correct='1,3', points='6', partial='1', nickname='1', seconds=str(seconds), show_results='immediate'),
                 dict(kind='rank', title='Prioritäten', options='A\nB\nC', top_n='2')]:
        assert staff.post(path+'/fragen', data=dict(csrf=csrf, **data)).status_code == 303
    pid = int(path.rsplit('/',1)[1])
    with SessionLocal() as db:
        poll = db.get(LivePoll,pid); token = poll.public_token; ids=[q.id for q in poll.questions]
    staff.post(path+'/status',data=dict(csrf=csrf,action='open'))
    a,b=client(),client()
    for c in (a,b): assert c.get('/l/'+token).status_code == 200
    return staff,csrf,path,token,ids,a,b

def answer(c,token,q,value,**extra):
    return c.post('/l/'+token+'/answer',json=dict(question=q,value=value,**extra),headers={'X-Live-Device':c.cookies.get(lv.DEVICE_COOKIE)})

def test_quiz_multi_change_two_devices_solution_release_and_anonymous_export():
    staff,csrf,path,token,ids,a,b=setup()
    qid=ids[0]
    public=a.get('/l/'+token+'/state.json').json()['questions'][0]
    assert 'correct' not in public['settings'] and 'solution' not in public and 'results' not in public
    assert answer(a,token,qid,{'o':['o1']},nickname='Ada').status_code == 200
    assert answer(b,token,qid,{'o':['o1','o3']}).status_code == 200
    assert answer(a,token,qid,{'o':['o1','o2']},nickname='Ada').status_code == 200
    with SessionLocal() as db:
        assert db.query(LiveAnswer).filter_by(question_id=qid).count() == 2
    staff_state=staff.get(path+'/state.json').json()['questions'][0]
    assert 'solution' not in staff_state and staff_state['answer_count']==2
    staff.post(f'{path}/fragen/{qid}/release',data={'csrf':csrf})
    result=a.get('/l/'+token+'/state.json').json()['questions'][0]
    assert result['solution']==['o1','o3'] and result['score']==0 and result['results']['total']==2
    assert result['scoreboard']==[{'name':'Ada','points':0}]
    assert answer(a,token,qid,{'o':['o1','o3']}).status_code == 409
    export=staff.get(f'{path}/fragen/{qid}/export.csv').text
    assert 'Ada' not in export and a.cookies.get(lv.DEVICE_COOKIE) not in export and 'o3' in export

def test_quiz_partial_exact_and_negative():
    q=LiveQuestion(kind='quiz',settings_json=json.dumps(dict(correct=['a','b'],points=6,partial=True)))
    assert lv.quiz_score(q,{'o':['a']})==3
    assert lv.quiz_score(q,{'o':['a','b']})==6
    assert lv.quiz_score(q,{'o':['a','c']})==0
    q.settings_json=json.dumps(dict(correct=['a','b'],points=6,partial=False))
    assert lv.quiz_score(q,{'o':['a']})==0
    assert lv.quiz_score(q,{'o':['a','b']})==6

def test_ranking_validation_borda_changes_lock_and_release():
    staff,csrf,path,token,ids,a,b=setup(); qid=ids[1]
    for raw in [['o1','o1'],['o1','wrong'],['o1'],['o1','o2','o3']]:
        assert answer(a,token,qid,{'r':raw}).status_code == 400
    assert answer(a,token,qid,{'r':['o2','o1']}).status_code==200
    assert answer(a,token,qid,{'r':['o3','o1']}).status_code==200
    assert answer(b,token,qid,{'r':['o1','o2']}).status_code==200
    result=staff.get(path+'/state.json').json()['questions'][1]['results']
    assert result['total']==2 and result['rows'][0]['label']=='A' and result['rows'][0]['count']==5
    staff.post(f'{path}/fragen/{qid}/lock',data={'csrf':csrf})
    assert answer(a,token,qid,{'r':['o2','o3']}).status_code==409
    assert '1: C' in staff.get(f'{path}/fragen/{qid}/export.csv').text

def test_moderated_step_releases_previous_quiz_and_timer_is_server_enforced():
    staff,csrf,path,token,ids,a,b=setup('moderated',10)
    assert answer(a,token,ids[1],{'r':['o1','o2']}).status_code==409
    with SessionLocal() as db:
        q=db.get(LiveQuestion,ids[0]); s=lv.settings(q); s['started']=time.time()-11; q.settings_json=json.dumps(s); db.commit()
    assert answer(a,token,ids[0],{'o':['o1']}).status_code==409
    staff.post(path+'/schritt',data={'csrf':csrf,'dir':'next'})
    payload=a.get('/l/'+token+'/state.json').json()
    assert payload['questions'][0]['kind']=='rank'
    assert payload['questions'][1]['solution']==['o1','o3']
    assert answer(a,token,ids[1],{'r':['o1','o2']}).status_code==200

def test_never_results_quiz_and_used_question_edit_guard():
    staff,csrf,path,token,ids,a,b=setup()
    assert answer(a,token,ids[0],{'o':['o1']}).status_code==200
    response=staff.post(path+'/fragen',data=dict(csrf=csrf,question_id=str(ids[0]),kind='quiz',title='changed',options='X\nY',correct='1'))
    assert response.status_code==303
    with SessionLocal() as db:
        q=db.get(LiveQuestion,ids[0]); assert q.title=='Mehrere Lösungen'; q.show_results='never'; db.commit()
    staff.post(f'{path}/fragen/{ids[0]}/release',data={'csrf':csrf})
    payload=a.get('/l/'+token+'/state.json').json()['questions'][0]
    assert 'solution' not in payload and 'score' not in payload and 'scoreboard' not in payload
    assert staff.get(path+'/state.json').json()['questions'][0]['solution']==['o1','o3']


def test_rejected_unknown_choice_and_bad_correct_definition():
    staff,csrf,path,token,ids,a,b=setup()
    assert answer(a,token,ids[0],{'o':['o1','unknown']}).status_code == 400
    q=LiveQuestion(kind='quiz')
    assert lv.apply_question(q,dict(title='Bad',kind='quiz',options='A\nB',correct='3'))
    assert lv.apply_question(q,dict(title='Bad',kind='quiz',options='A\nB',correct='text'))
    assert lv.apply_question(q,dict(title='Bad',kind='quiz',options='A\nB',correct=''))


def test_archived_quiz_and_ranking_are_read_only_and_keep_exports():
    staff,csrf,path,token,ids,a,b=setup()
    assert answer(a,token,ids[0],{'o':['o1']}).status_code==200
    assert answer(a,token,ids[1],{'r':['o1','o2']}).status_code==200
    assert staff.post(path+'/loeschen',data={'csrf':csrf}).status_code==303
    for endpoint, data in [('settings',{}),('fragen',dict(kind='quiz',title='X',options='A\nB',correct='1')),('status',{'action':'open'}),('schritt',{'dir':'next'})]:
        assert staff.post(path+'/'+endpoint,data=dict(csrf=csrf,**data)).status_code==409
    for action in ('release','timer','lock','show','reset','delete'):
        assert staff.post(f'{path}/fragen/{ids[0]}/{action}',data={'csrf':csrf}).status_code==409
    assert answer(a,token,ids[0],{'o':['o1','o3']}).status_code==409
    page=staff.get(path)
    assert page.status_code==200 and 'Richtige Lösung' in page.text and 'Borda-Punkte' in page.text
    public=a.get('/l/'+token+'/state.json').json()['questions'][0]
    assert 'solution' not in public and 'correct' not in public['settings']
    assert staff.get(f'{path}/fragen/{ids[0]}/export.csv').status_code==200
    with SessionLocal() as db:
        poll=db.get(LivePoll,int(path.rsplit('/',1)[1])); assert poll.archived_at and poll.used_at
        q=db.get(LiveQuestion,ids[0]); assert not q.released
        assert db.query(LiveAnswer).filter_by(poll_id=poll.id).count()==2


def test_timer_survives_edit_and_new_free_question_starts_immediately():
    staff,csrf,path,token,ids,a,b=setup(seconds=10)
    with SessionLocal() as db:
        q=db.get(LiveQuestion,ids[0]); original=lv.settings(q)['started']
    staff.post(path+'/fragen',data=dict(csrf=csrf,question_id=ids[0],kind='quiz',title='Edited',options='A\nB\nC',correct='1,3',seconds='10'))
    with SessionLocal() as db:
        assert lv.settings(db.get(LiveQuestion,ids[0]))['started']==original
    staff.post(path+'/fragen',data=dict(csrf=csrf,kind='quiz',title='New timer',options='A\nB',correct='1',seconds='30'))
    with SessionLocal() as db:
        q=db.query(LiveQuestion).filter_by(title='New timer').one()
        assert lv.settings(q).get('started') and lv.remaining(q) is not None


def test_release_is_permanent_until_explicit_reset_and_own_nickname_survives():
    staff,csrf,path,token,ids,a,b=setup(); qid=ids[0]
    assert answer(a,token,qid,{'o':['o1']},nickname='Ada').status_code==200
    assert a.get('/l/'+token+'/state.json').json()['questions'][0]['mine']['nickname']=='Ada'
    assert b.get('/l/'+token+'/state.json').json()['questions'][0]['mine'] is None
    assert answer(a,token,qid,{'o':['o1','o3']}).status_code==200
    assert a.get('/l/'+token+'/state.json').json()['questions'][0]['mine']['nickname']=='Ada'
    for _ in range(2):
        assert staff.post(f'{path}/fragen/{qid}/release',data={'csrf':csrf}).status_code==303
    assert staff.post(f'{path}/fragen/{qid}/lock',data={'csrf':csrf}).status_code==409
    assert staff.post(f'{path}/fragen/{qid}/timer',data={'csrf':csrf}).status_code==409
    assert staff.post(path+'/fragen',data=dict(csrf=csrf,question_id=qid,kind='quiz',title='X',options='A\nB',correct='1')).status_code==409
    assert answer(a,token,qid,{'o':['o1']}).status_code==409
    staff.post(f'{path}/fragen/{qid}/reset',data={'csrf':csrf})
    assert answer(a,token,qid,{'o':['o1']}).status_code==200
    with SessionLocal() as db:
        poll=db.get(LivePoll,int(path.rsplit('/',1)[1])); assert poll.used_at
        assert not db.get(LiveQuestion,qid).released


def test_new_current_quiz_after_deleting_current_starts_timer():
    staff,csrf,path,token,ids,a,b=setup('moderated',10)
    assert staff.post(f'{path}/fragen/{ids[0]}/delete',data={'csrf':csrf}).status_code==303
    staff.post(path+'/fragen',data=dict(csrf=csrf,kind='quiz',title='Replacement',options='A\nB',correct='1',seconds='30'))
    with SessionLocal() as db:
        poll=db.get(LivePoll,int(path.rsplit('/',1)[1]))
        q=db.get(LiveQuestion,poll.current_id)
        assert q.title=='Replacement' and lv.settings(q).get('started')
        assert lv.remaining(q) is not None
