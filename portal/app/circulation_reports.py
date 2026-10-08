"""Read-only reports. Source access never grants access to recipient evidence."""
from collections import Counter, defaultdict
from sqlalchemy import select
from . import circulations as cl
from .db import Circulation, CirculationVersion, CirculationRecipient, CirculationReceipt, CirculationEvent, User, utcnow


def may_report(db, user, row):
    return cl.may_edit(db, user, row)


def snapshot(db, row, ver, people=None, proofs=None, events=None):
    c = cl.content(ver or row)
    people = people if people is not None else (cl.recipients(db, ver) if ver else [])
    keys = cl.requirement_keys(c) if c['mode'] != 'info' else []
    if proofs is None:
        proofs = list(db.scalars(select(CirculationReceipt).where(CirculationReceipt.recipient_id.in_([p.id for p in people]))))
    if events is None:
        events = list(db.scalars(select(CirculationEvent).where(CirculationEvent.version_id == ver.id).order_by(CirculationEvent.created_at, CirculationEvent.id))) if ver else []
    acknowledged = {p.id: {r.item_key for r in proofs if r.recipient_id == p.id} for p in people}
    question_state = {}
    for e in events:
        if e.kind in {'question', 'reply'}: question_state[e.recipient_id] = e.kind
    counts = Counter(p.decision or 'pending' for p in people)
    live = bool(ver and row.current_version == ver.number and cl.active(row, ver) and not cl.expired(ver))
    overdue = bool(live and keys and c['due_on'] and cl.at(c['due_on']) < utcnow())
    stopped = c['sequential'] and counts['rejected'] > 0
    details = []
    for p in people:
        done = len(set(keys) & acknowledged[p.id])
        waiting = bool(not p.decision and c['sequential'] and (stopped or any(other.position < p.position and not other.decision for other in people)))
        status = cl.DECISIONS[p.decision] if p.decision else ('Keine Rückmeldung erforderlich' if not keys else 'Ablauf gestoppt' if stopped else 'Später an der Reihe' if waiting else 'Teilweise bestätigt' if done else cl.action_label(c))
        details.append(dict(rec=p, status=status, done=done, required=len(keys), acknowledged=acknowledged[p.id],
                            overdue=bool(overdue and not p.decision), waiting=waiting, question=question_state.get(p.id) == 'question'))
    completed = sum(bool(p.decision) for p in people) if keys else 0
    phase = 'Entwurf' if not ver else 'Archiviert' if row.archived else 'Abgelaufen' if cl.expired(ver) else 'Geplant' if not cl.active(row, ver) else 'Information' if not keys else 'Gestoppt' if stopped else 'Abgeschlossen' if people and completed == len(people) else 'In Bearbeitung'
    docs = [dict(key=k, title='Einleitung' if k == 'body' else 'Gesamte Fassung' if k == 'all' else next((i['title'] for i in c['items'] if i['key'] == k), k),
                 confirmed=sum(k in acknowledged[p.id] for p in people), pending=sum(not p.decision and k not in acknowledged[p.id] for p in people)) for k in keys]
    return dict(row=row, ver=ver, c=c, people=details, counts=counts, total=len(people), completed=completed,
                pending=counts['pending'] if keys else 0, overdue=sum(p['overdue'] for p in details),
                questions=sum(p['question'] for p in details), phase=phase, documents=docs,
                percent=round(100 * completed / len(people)) if keys and people else None,
                bundle_ids={str(i['bundle_id']) for i in c['items'] if i.get('bundle_id')})


def overview(db, user, scope='mine'):
    rows = [r for r in db.scalars(select(Circulation).order_by(Circulation.updated_at.desc()))
            if (scope != 'mine' or r.owner_id == user.id) and may_report(db, user, r)]
    versions = list(db.scalars(select(CirculationVersion).where(CirculationVersion.circulation_id.in_([r.id for r in rows]))))
    row_numbers={r.id:r.current_version for r in rows}
    current = {v.circulation_id:v for v in versions if row_numbers[v.circulation_id]==v.number}
    people = list(db.scalars(select(CirculationRecipient).where(CirculationRecipient.version_id.in_([v.id for v in current.values()])).order_by(CirculationRecipient.position, CirculationRecipient.id)))
    proofs = list(db.scalars(select(CirculationReceipt).where(CirculationReceipt.recipient_id.in_([p.id for p in people]))))
    events = list(db.scalars(select(CirculationEvent).where(CirculationEvent.version_id.in_([v.id for v in current.values()])).order_by(CirculationEvent.created_at, CirculationEvent.id)))
    by_version,proofs_by_version,events_by_version=defaultdict(list),defaultdict(list),defaultdict(list)
    recipient_versions={p.id:p.version_id for p in people}
    for p in people: by_version[p.version_id].append(p)
    for proof in proofs: proofs_by_version[recipient_versions[proof.recipient_id]].append(proof)
    for event in events: events_by_version[event.version_id].append(event)
    return [snapshot(db,row,current.get(row.id),by_version[current[row.id].id] if row.id in current else [],
        proofs_by_version[current[row.id].id] if row.id in current else [],events_by_version[current[row.id].id] if row.id in current else []) for row in rows]



def filtered(reports, params):
    q = params.get('q','').strip().casefold()[:200]
    return [r for r in reports if (not q or q in (r['c']['title']+' '+r['c']['category']).casefold())
            and (not params.get('mode') or r['c']['mode'] == params['mode'])
            and (not params.get('phase') or r['phase'] == params['phase'])
            and (not params.get('bundle') or params['bundle'] in r['bundle_ids'])
            and (params.get('status') != 'overdue' or r['overdue'])
            and (params.get('status') != 'pending' or r['pending'])
            and (params.get('status') != 'rejected' or r['counts']['rejected'])
            and (params.get('status') != 'questions' or r['questions'])]


def totals(reports):
    return {k:sum(r[k] for r in reports) for k in ('total','completed','pending','overdue','questions')}


def export_data(report):
    return dict(id=report['row'].id, title=report['c']['title'], version=report['ver'].number if report['ver'] else None,
        phase=report['phase'], mode=report['c']['mode'], due_on=report['c']['due_on'], counts=dict(report['counts']),
        **{k:report[k] for k in ('total','completed','pending','overdue','questions','percent','documents')},
        recipients=[dict(name=p['rec'].name, email=p['rec'].email, type='Benutzer' if p['rec'].user_id else 'Gast',
            status=p['status'], decision=p['rec'].decision, reason=p['rec'].reason,
            decided_at=p['rec'].decided_at.isoformat() if p['rec'].decided_at else '', recorded_by=p['rec'].recorded_by,
            notified_at=p['rec'].notified_at.isoformat() if p['rec'].notified_at else '',
            reminded_at=p['rec'].reminded_at.isoformat() if p['rec'].reminded_at else '',
            confirmed_documents=sorted(p['acknowledged']), required=p['required'], done=p['done'], overdue=p['overdue'], question=p['question']) for p in report['people']])
