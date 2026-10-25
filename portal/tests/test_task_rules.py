import json
import pytest
from sqlalchemy import select, func
from app import tasks as ts, task_rules
from app.task_models import Task, TaskRule, TaskRuleRun, TaskActivity
from test_native_tasks import task_people, make, client_for  # noqa: F401


def rule(db,people,**changes):
    people[0].permissions='tasks,tasks_manage';db.commit()
    clean=task_rules.rule_values({'name':'Versand vorbereiten','trigger':'completed','rule_action':'followup',
          'action_title':'Folgeaufgabe','action_user':str(people[1].id),'action_days':'1','active':'1',**changes})
    row=TaskRule(creator_id=people[0].id,**clean);db.add(row);db.commit();return row


def test_completed_event_retries_do_not_duplicate_and_paused_rules_do_nothing(db,task_people):
    automation=rule(db,task_people)
    task=make(db,task_people)
    ts.transition(db,task_people[1],task,'done');db.commit()
    assert db.scalar(select(func.count(Task.id)).where(Task.title=='Folgeaufgabe'))==1
    run=db.scalar(select(TaskRuleRun).where(TaskRuleRun.rule_id==automation.id))
    assert run.version==automation.version
    ts.transition(db,task_people[1],task,'done');db.commit()
    assert db.scalar(select(func.count(Task.id)).where(Task.title=='Folgeaufgabe'))==1
    automation.active=False;db.commit()
    second=make(db,task_people)
    ts.transition(db,task_people[1],second,'done');db.commit()
    assert db.scalar(select(func.count(Task.id)).where(Task.title=='Folgeaufgabe'))==1


def test_recursion_is_hard_bounded_and_automatic_actions_are_audited(db,task_people):
    rule(db,task_people,trigger='created')
    make(db,task_people)
    assert db.scalar(select(func.count(Task.id)).where(Task.creator_id==task_people[0].id))==2
    assert db.scalar(select(TaskActivity).where(TaskActivity.kind=='automation'))


def test_live_permissions_and_inactive_assignee_prevent_automatic_work(db,task_people):
    rule(db,task_people)
    task=make(db,task_people)
    task_people[0].permissions='tasks';db.commit()
    ts.transition(db,task_people[1],task,'done');db.commit()
    assert not db.scalar(select(Task).where(Task.title=='Folgeaufgabe'))


def test_preview_is_side_effect_free_and_nonmanagers_cannot_access_rules(db,task_people):
    task=make(db,task_people)
    c,token=client_for(task_people[1])
    assert c.get('/aufgaben/regeln').status_code==403
    task_people[0].permissions='tasks,tasks_manage';db.commit()
    c,token=client_for(task_people[0])
    data={'csrf':token,'name':'Testregel','trigger':'completed','rule_action':'followup','action_title':'Nicht anlegen',
          'action_user':str(task_people[1].id),'action_days':'1','example_id':task.id,'action':'preview'}
    assert c.post('/aufgaben/regeln',data=data).status_code==200
    assert not db.scalar(select(TaskRule)) and not db.scalar(select(Task).where(Task.title=='Nicht anlegen'))
    for bad in ['__import__("os")','shell','{{ user }}']:
        with pytest.raises(ts.Invalid):task_rules.rule_values({**data,'rule_action':bad})
