"""Finite trigger/condition/action rules; live authority, no expressions, bounded recursion."""
import hashlib
import json
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import tasks as ts
from .db import User, utcnow
from .task_models import Task, TaskParticipant, TaskRule, TaskRuleRun

TRIGGERS = {'created':'Aufgabe angelegt', 'assigned':'Verantwortlichkeit geändert', 'status_changed':'Status geändert',
            'completed':'Aufgabe erledigt', 'review_approved':'Freigabe erteilt', 'review_returned':'Zur Bearbeitung zurückgegeben',
            'due':'Fälligkeit erreicht', 'predecessor_done':'Bestimmte Aufgabe erledigt'}
ACTIONS = {'followup':'Folgeaufgabe erstellen', 'assign':'Verantwortliche Person setzen', 'tag_priority':'Tag / Priorität setzen',
           'due_days':'Fälligkeit relativ setzen', 'participant':'Mitwirkende Person hinzufügen', 'notify':'Beteiligte Person benachrichtigen'}
FIELDS = {'tag','priority','creator_id','assignee_id','group_id','source_type','status','task_id'}


def rule_values(data):
    name = str(data.get('name','')).strip()
    trigger = str(data.get('trigger',''))
    action = str(data.get('rule_action',''))
    if not name or len(name)>200 or trigger not in TRIGGERS or action not in ACTIONS:
        raise ts.Invalid('Geben Sie einen Regelnamen an und wählen Sie ein Ereignis und eine Aktion.')
    conditions = {key:str(data.get('condition_'+key,'')).strip() for key in FIELDS if data.get('condition_'+key)}
    if conditions.get('priority') and conditions['priority'] not in ts.PRIORITIES:
        raise ts.Invalid('Ungültige Bedingung für die Priorität.')
    if conditions.get('status') and conditions['status'] not in ts.STATUSES:
        raise ts.Invalid('Ungültige Bedingung für den Status.')
    for key in ('creator_id','assignee_id','group_id','task_id'):
        if conditions.get(key) and not conditions[key].isdigit():
            raise ts.Invalid('Personen, Gruppen und Aufgaben müssen aus der Auswahl stammen.')
    payload = {'kind':action}
    if action in {'assign','participant','notify','followup'}:
        uid=str(data.get('action_user',''))
        if not uid.isdigit():raise ts.Invalid('Wählen Sie eine Person für die Aktion.')
        payload['user_id']=int(uid)
    if action=='followup':
        title=str(data.get('action_title','')).strip()
        if not title or len(title)>300:raise ts.Invalid('Geben Sie einen Titel für die Folgeaufgabe an.')
        payload['title']=title
    if action in {'due_days','followup'}:
        try:days=int(str(data.get('action_days','1')))
        except ValueError:raise ts.Invalid('Geben Sie eine Anzahl von Tagen ein.') from None
        if not 0<=days<=3650:raise ts.Invalid('Der Abstand muss zwischen 0 und 3650 Tagen liegen.')
        payload['days']=days
    if action=='tag_priority':
        payload['tag']=ts.tags(data.get('action_tag',''))
        payload['priority']=str(data.get('action_priority','normal'))
        if payload['priority'] not in ts.PRIORITIES:raise ts.Invalid('Bitte eine gültige Priorität auswählen.')
    return dict(name=name,trigger=trigger,conditions_json=json.dumps(conditions),action_json=json.dumps(payload),active=data.get('active')=='1')


def matches(row, conditions):
    for key,value in conditions.items():
        actual = row.id if key=='task_id' else row.tags.split(',') if key=='tag' else getattr(row,key)
        if key=='tag':
            if value.casefold() not in [t.casefold() for t in actual]:return False
        elif str(actual or '')!=str(value):return False
    return True


def allowed(db, owner, row):
    if not owner or not owner.active or not ts.manager(owner):return False
    if row.archived_at or not db.scalar(ts.visible_query(owner).where(Task.id==row.id)):return False
    if row.source_type:
        from . import task_sources
        if not task_sources.source_info(db,owner,row.source_type,row.source_id)['row']:return False
    return True


def execute(db, rule, row, owner, key):
    payload=json.loads(rule.action_json)
    kind=payload['kind']
    if kind in {'assign','participant','notify','followup'}:
        person=db.get(User,payload['user_id'])
        if not person or not person.active:raise ts.Invalid('Zielperson ist nicht aktiv.')
    if kind=='followup':
        from .db import to_local
        due=to_local(utcnow()+timedelta(days=payload['days'])).date().isoformat()
        task=ts.create(db,owner,{'title':payload['title'],'assignee_id':person.id,'due_date':due},source_key=f'rule:{rule.id}:{key}')
        ts.audit(db,task,None,'automation',f'Automatische Folgeaufgabe aus Regel „{rule.name}“, Version {rule.version}.')
    elif kind=='assign':
        data=ts.form_values(row);data.update(assignee_id=str(person.id),external='')
        ts.update(db,owner,row,data)
    elif kind=='tag_priority':
        data=ts.form_values(row);data.update(tags=','.join(filter(None,[row.tags,payload['tag']])),priority=payload['priority'])
        ts.update(db,owner,row,data)
    elif kind=='due_days':
        from .db import to_local
        data=ts.form_values(row);data['due_date']=to_local(utcnow()+timedelta(days=payload['days'])).date().isoformat()
        ts.update(db,owner,row,data)
    elif kind=='participant':
        if not db.get(TaskParticipant,(row.id,person.id)):
            db.add(TaskParticipant(task_id=row.id,user_id=person.id))
    elif kind=='notify':
        if not db.scalar(ts.visible_query(person).where(Task.id==row.id)):
            raise ts.Invalid('Die Zielperson hat keinen Zugriff auf die Aufgabe.')
        ts.ping(db,row,[person.id],'Hinweis aus einer Aufgabenregel')
    ts.audit(db,row,None,'automation',f'Automatische Aktion: {ACTIONS[kind]} · Regel „{rule.name}“, Version {rule.version}.')


def emit(db, row, trigger, event_key):
    stack=db.info.setdefault('task_rule_stack',[])
    if len(stack)>=3:return
    key=hashlib.sha256(str(event_key).encode()).hexdigest()
    for rule in list(db.scalars(select(TaskRule).where(TaskRule.active.is_(True),TaskRule.trigger==trigger).order_by(TaskRule.id))):
        if rule.id in stack or not matches(row,json.loads(rule.conditions_json)):continue
        owner=db.get(User,rule.creator_id)
        if not allowed(db,owner,row) or db.get(TaskRuleRun,(rule.id,key)):continue
        stack.append(rule.id)
        try:
            try:
                with db.begin_nested():
                    run=TaskRuleRun(rule_id=rule.id,event_key=key,task_id=row.id,version=rule.version)
                    db.add(run);db.flush()
                    execute(db,rule,row,owner,key)
            except IntegrityError:
                # Another invocation already committed this event.
                continue
            except (ts.Invalid,HTTPException) as exc:
                db.add(TaskRuleRun(rule_id=rule.id,event_key=key,task_id=row.id,version=rule.version,result='Nicht ausgeführt: '+str(exc)[:450]))
                ts.audit(db,row,None,'automation',f'Regel „{rule.name}“ konnte nicht ausgeführt werden. Konfiguration und Berechtigungen prüfen.')
        finally:
            stack.pop()
