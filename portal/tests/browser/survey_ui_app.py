"""Isolated survey browser fixture; reuses the mail-free task test account."""
from task_ui_app import app
from app import live as lv
from app.db import Form, LivePoll, LiveQuestion, SessionLocal, User, set_setting
from sqlalchemy import select

with SessionLocal() as db:
    set_setting(db,'module_polls','1')
    set_setting(db,'module_forms','1')
    user=db.scalar(select(User).where(User.email=='browser@example.org'))
    user.permissions='tasks,tasks_manage,votes,polls,forms'
    poll=LivePoll(owner_id=user.id,title='Feedback zur Bürgerversammlung',public_token='browser-survey-sample-token')
    db.add(poll);db.flush()
    question=LiveQuestion(poll_id=poll.id,position=0,title='',kind='single')
    assert not lv.apply_question(question,{'kind':'single','title':'Was ist Ihnen wichtig?','options':'Mobilität\nZusammenleben\nNatur'})
    db.add(question)
    db.add(Form(owner_id=user.id,title='Eigenständiges Formular',schema_json='[]',active=False))
    db.commit()
