"""Versioned circulation folders, personal acknowledgements and portal integration.

A reference never grants source access. Explicitly uploaded copies are distributed
with the folder. Guest capabilities are hashed, expiring and never forwarded.
"""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy import select

from . import absence, dms, forms, notify
from .config import settings
from .db import (Circulation, CirculationBundle, CirculationDistributor, CirculationEvent, CirculationReceipt,
                 CirculationRecipient, CirculationVersion, DmsFile, DmsRecord, Form, Group, GroupMember,
                 LawText, SessionLocal, User, get_settings, utcnow)

CATEGORIES = ['Dienstanweisungen', 'Personalinformationen', 'IT', 'Arbeitsschutz', 'Onboarding', 'Allgemeines']
DECISIONS = {'': 'Offen', 'ack': 'Zur Kenntnis genommen', 'approved': 'Freigegeben', 'rejected': 'Abgelehnt',
             'exempt': 'Ausgenommen', 'offline': 'Extern dokumentiert', 'carried': 'Bestätigung der Vorfassung'}
_md = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def content(obj):
    return json.loads(obj.content_json if isinstance(obj, CirculationVersion) else obj.draft_json)


def markdown(text):
    return Markup(_md.render(text or ''))


def default():
    return dict(title='', body='', category='Allgemeines', kind='notice', mode='info', per_item=False,
                sequential=False, audience={'users': [], 'groups': [], 'all': False, 'guests': []},
                dynamic=False, public=False, pinned=False, items=[], publish_on='', due_on='', expires_on='',
                reminder_days=3, guest_days=30, escalate_id=None, review_requested=False, require_item_sequence=False, allow_proxy_approval=False, share_progress=False, email_summary='')


def may_edit(db, user, row):
    if not user or not row:
        return False
    if user.can('circulations_manage'):
        return True
    if row.owner_id == user.id:
        return True
    if user.can('circulations_publish') and db.scalar(select(CirculationVersion.id).where(
        CirculationVersion.circulation_id == row.id, CirculationVersion.published_by == user.id)):
        return True
    owner = db.get(User, row.owner_id)
    return bool(owner and owner.active and row.owner_id in absence.represented(db, user)
                and (owner.can('circulations_create') or owner.can('circulations_publish')))


def may_publish(db, user, row):
    if user.can('circulations_manage'):
        return True
    return user.can('circulations_publish') and (may_edit(db, user, row) or content(row).get('review_requested'))


def event(db, row, kind, text='', user=None, version=None, recipient=None):
    db.add(CirculationEvent(circulation_id=row.id, version_id=version.id if version else None,
                           recipient_id=recipient.id if recipient else None, actor_id=user.id if user else None,
                           kind=kind, text=text[:10000]))


def version(db, row, number=None):
    return db.scalar(select(CirculationVersion).where(CirculationVersion.circulation_id == row.id,
                  CirculationVersion.number == (number or row.current_version)))


def recipients(db, ver):
    return list(db.scalars(select(CirculationRecipient).where(CirculationRecipient.version_id == ver.id)
                          .order_by(CirculationRecipient.position, CirculationRecipient.id)))


def own_recipient(db, ver, user):
    return db.scalar(select(CirculationRecipient).where(CirculationRecipient.version_id == ver.id,
                       CirculationRecipient.user_id == user.id)) if user else None


def at(value):
    return datetime.fromisoformat(value) if value else None


def active(row, ver):
    c = content(ver)
    return not row.archived and (not c['publish_on'] or at(c['publish_on']) <= utcnow())


def expired(ver):
    return bool(content(ver)['expires_on'] and at(content(ver)['expires_on']) <= utcnow())


def readable(db, row, ver, user=None, guest=None):
    if may_edit(db, user, row) or (user and user.can('circulations_publish') and content(row).get('review_requested')):
        return True
    if ver and content(ver)['publish_on'] and at(content(ver)['publish_on']) > utcnow():
        return False
    if not ver or not active(row, ver):
        # Archived folders remain readable to their actual recipients.
        if not ver or not row.archived:
            return False
    c = content(ver)
    if guest:
        return guest.version_id == ver.id
    return bool(c['public'] or (user and acting_recipients(db, ver, user)))


def ready(db, ver, recipient):
    if not recipient or recipient.decision:
        return False
    if not content(ver)['sequential']:
        return True
    people = recipients(db, ver)
    if any(p.decision == 'rejected' for p in people):
        return False
    return not any(p.position < recipient.position and not p.decision for p in people)


def receipts(db, recipient):
    return list(db.scalars(select(CirculationReceipt).where(CirculationReceipt.recipient_id == recipient.id)
                          .order_by(CirculationReceipt.id))) if recipient else []


def requirement_keys(c):
    return ['body', *[i['key'] for i in c['items']]] if c['per_item'] else ['all']


def action_label(c):
    return 'Freigabe erforderlich' if c['mode'] == 'approval' else 'Kenntnisnahme erforderlich' if c['mode'] == 'ack' else 'Keine Rückmeldung erforderlich'


def acting_recipients(db, ver, user):
    if not user: return []
    c = content(ver)
    allowed = [user.id]
    if c['mode'] == 'approval' and c.get('allow_proxy_approval'):
        allowed += absence.represented(db, user)
    return [r for r in recipients(db, ver) if r.user_id in allowed]


def acknowledge(db, row, ver, rec, user, key, decision, reason=''):
    if not rec or (rec.user_id is not None and rec.id not in {r.id for r in acting_recipients(db, ver, user)}):
        raise HTTPException(403, 'Nur die adressierte Person darf selbst bestätigen.')
    if row.current_version != ver.number or not active(row, ver) or row.archived or expired(ver):
        raise HTTPException(409, 'Diese Fassung ist nicht mehr zur Bestätigung geöffnet.')
    c = content(ver)
    if c['mode'] == 'info' or not ready(db, ver, rec):
        raise HTTPException(409, 'Diese Station ist noch nicht geöffnet oder bereits abgeschlossen.')
    if decision == 'rejected':
        if c['mode'] != 'approval' or not reason.strip():
            raise HTTPException(422, 'Eine Ablehnung benötigt eine Begründung.')
    elif decision != ('approved' if c['mode'] == 'approval' else 'ack') or key not in requirement_keys(c):
        raise HTTPException(422, 'Ungültige Bestätigung.')
    if decision != 'rejected':
        if c.get('require_item_sequence') and c['per_item']:
            confirmed = {r.item_key for r in receipts(db, rec)}
            next_key = next((k for k in requirement_keys(c) if k not in confirmed), None)
            if key != next_key: raise HTTPException(409, 'Bitte die Dokumente in der vorgegebenen Reihenfolge bearbeiten.')
        if any(r.item_key == key for r in receipts(db, rec)):
            raise HTTPException(409, 'Dieses Dokument wurde bereits bestätigt.')
        db.add(CirculationReceipt(recipient_id=rec.id, item_key=key, recorded_by=user.id if user else None, method='proxy' if user and user.id != rec.user_id else 'self'))
        db.flush()
        if set(requirement_keys(c)) <= {r.item_key for r in receipts(db, rec)}:
            rec.decision, rec.decided_at = decision, utcnow()
    else:
        rec.decision, rec.decided_at, rec.reason = decision, utcnow(), reason.strip()[:4000]
    if user and user.id != rec.user_id: rec.recorded_by = user.id
    event(db, row, decision, key if decision != 'rejected' else reason, user, ver, rec)
    db.flush()
    dispatch(db, row, ver)


def audience_users(db, audience):
    # Preserve explicit order for sequential stations; group members follow by name.
    ids = list(dict.fromkeys(audience['users']))
    group_ids = set(audience['groups'])
    members = select(GroupMember.user_id).where(GroupMember.group_id.in_(group_ids))
    more = db.scalars(select(User).where(User.active.is_(True),
                    True if audience['all'] else User.id.in_(members)).order_by(User.name, User.id))
    ids += [u.id for u in more if u.id not in ids]
    return [u for uid in ids if (u := db.get(User, uid)) and u.active]


def sync_audience(db, row, ver):
    c = content(ver)
    present = {r.user_id for r in recipients(db, ver) if r.user_id}
    next_pos = max([r.position for r in recipients(db, ver)], default=-1) + 1
    for u in audience_users(db, c['audience']):
        if u.id not in present:
            db.add(CirculationRecipient(version_id=ver.id, user_id=u.id, name=u.name, email=u.email,
                                       position=next_pos))
            next_pos += 1
    db.flush()


def source(db, user, item, *, allow_archived=False):
    """Validate on save and publication; no snapshots of protected portal references."""
    kind, ident = item['kind'], item.get('id')
    modules = get_settings(db)
    module = {'law': 'laws', 'form': 'forms', 'dms': 'dms'}.get(kind)
    if module and modules.get('module_' + module) != '1':
        raise HTTPException(422, 'Das verknüpfte Modul ist deaktiviert.')
    if kind == 'law':
        obj = db.get(LawText, ident)
        if not obj or not obj.published:
            raise HTTPException(422, 'Bitte einen veröffentlichten Rechtstext auswählen.')
        return obj.title, '/recht/' + obj.slug
    if kind == 'form':
        obj = db.get(Form, ident)
        if not obj or not obj.active or not obj.public_token or (obj.internal and not user.can('internal_forms')):
            raise HTTPException(422, 'Das Formular hat keinen nutzbaren Ausfülllink.')
        return obj.title, '/f/' + obj.public_token
    if kind == 'dms':
        obj = db.get(DmsFile, ident)
        if not obj or dms.record_level(db, user, obj.record) < dms.READ:
            raise HTTPException(403, 'Keine Leseberechtigung für dieses DMS-Dokument.')
        if obj.record.archived_at and not allow_archived:
            raise HTTPException(409, 'Archivierte DMS-Dokumente können nicht neu hinzugefügt werden.')
        return obj.name, f'/dms/r/{obj.record_id}/files/{obj.id}'
    return item['title'], ''


def item_access(db, user, item):
    if item['kind'] == 'dms':
        obj = db.get(DmsFile, item['id'])
        return bool(user and obj and get_settings(db).get('module_dms') == '1'
                    and dms.record_level(db, user, obj.record) >= dms.READ)
    if item['kind'] == 'law':
        obj = db.get(LawText, item['id'])
        return bool(obj and obj.published and (not obj.internal or user) and get_settings(db).get('module_laws') == '1')
    if item['kind'] == 'form':
        obj = db.get(Form, item['id'])
        return bool(obj and obj.active and obj.public_token and get_settings(db).get('module_forms') == '1'
                    and (not obj.internal or (user and user.can('internal_forms'))))
    return True


def publish(db, row, user, reack=True):
    if not may_publish(db, user, row):
        raise HTTPException(403, 'Das Recht zum Veröffentlichen fehlt.')
    c = content(row)
    if not c['title'].strip() or (not c['body'].strip() and not c['items']):
        raise HTTPException(422, 'Titel und mindestens ein Inhalt sind erforderlich.')
    if c['dynamic'] and c['sequential']:
        raise HTTPException(422, 'Eine feste Stationsfolge kann keine dynamischen Empfänger haben.')
    if c['public'] and (c['audience']['guests'] or c['mode'] != 'info'):
        raise HTTPException(422, 'Öffentliche Aushänge dienen der Information ohne personenbezogene Bestätigung.')
    audience = audience_users(db, c['audience'])
    if not audience and not c['audience']['guests'] and not c['public']:
        raise HTTPException(422, 'Bitte mindestens einen Empfänger auswählen.')
    for item in c['items']:
        if item['kind'] in {'law', 'form', 'dms'}:
            item['title'], item['url'] = source(db, user, item, allow_archived=True)
        if item['kind'] == 'law':
            if db.get(LawText, item['id']).internal and (c['public'] or c['audience']['guests']):
                raise HTTPException(422, 'Interne Dienstanweisungen sind nur für angemeldete Benutzer verfügbar.')
            # Public law text is frozen for meaningful document acknowledgement.
            item['body'] = db.get(LawText, item['id']).body_md
        if item['kind'] == 'dms':
            if c['public'] or c['audience']['guests']:
                raise HTTPException(422, 'DMS-Verweise sind intern. Für Gäste eine ausdrücklich freigegebene Kopie hochladen.')
            if any(not item_access(db, u, item) for u in audience):
                raise HTTPException(422, 'Nicht alle Empfänger dürfen das verknüpfte DMS-Dokument lesen. Rechte prüfen oder eine freigegebene Kopie hochladen.')
        if item['kind'] == 'form' and db.get(Form, item['id']).internal and (c['public'] or c['audience']['guests']):
            raise HTTPException(422, 'Interne Formulare können nicht an Gäste oder öffentlich verteilt werden.')
    # Date validation is server-side and independent of the editor.
    start = at(c['publish_on']) or utcnow()
    if any(c[k] and at(c[k]) <= start for k in ['due_on', 'expires_on']):
        raise HTTPException(422, 'Frist und Ablauf müssen nach der Veröffentlichung liegen.')
    if c['due_on'] and c['expires_on'] and at(c['due_on']) > at(c['expires_on']):
        raise HTTPException(422, 'Die Bestätigungsfrist darf nicht nach dem Ablauf liegen.')
    old = version(db, row)
    c['review_requested'] = False
    row.current_version += 1
    row.archived = False
    row.updated_at = utcnow()
    row.draft_json = dumps(c)
    ver = CirculationVersion(circulation_id=row.id, number=row.current_version, content_json=dumps(c),
                             digest=hashlib.sha256(dumps(c).encode()).hexdigest(), published_by=user.id)
    db.add(ver); db.flush()
    sync_audience(db, row, ver)
    for g in c['audience']['guests']:
        if g['email'].lower() in {r.email.lower() for r in recipients(db, ver)}: continue
        db.add(CirculationRecipient(version_id=ver.id, name=g['name'], email=g['email'],
                                   position=len(recipients(db, ver))))
        db.flush()
    if old and not reack:
        # Reusing prior evidence is explicit, never falsely reported as a new acknowledgement.
        prev = {r.user_id or r.email.lower(): r for r in recipients(db, old)}
        for r in recipients(db, ver):
            pr = prev.get(r.user_id or r.email.lower())
            if pr and pr.decision in {'ack', 'approved', 'offline', 'carried'}:
                r.decision, r.decided_at = 'carried', pr.decided_at
                r.reason = f'Bestätigung übernommen aus Fassung {old.number}; keine neue Bestätigung.'
                r.recorded_by = user.id
                for receipt in receipts(db, pr):
                    db.add(CirculationReceipt(recipient_id=r.id, item_key=receipt.item_key,
                        acknowledged_at=receipt.acknowledged_at, method='carried', recorded_by=user.id,
                        evidence=f'Fassung {old.number}, Nachweis {receipt.id}'))
    event(db, row, 'publish', f'Fassung {ver.number}; erneute Bestätigung: {reack}', user, ver)
    dispatch(db, row, ver)
    return ver


def guest_url(db, row, ver, recipient):
    token = secrets.token_urlsafe(32)
    recipient.token_hash = hashlib.sha256(token.encode()).hexdigest()
    recipient.token_expires_at = min(utcnow() + timedelta(days=content(ver)['guest_days']),
                                    at(content(ver)['expires_on']) or datetime.max)
    return settings.portal_base_url.rstrip('/') + '/umlaeufe/g/' + token


def dispatch(db, row, ver, reminders=False):
    if not active(row, ver) or expired(ver) or row.archived:
        return 0
    c = content(ver)
    cfg = get_settings(db)
    if not notify.mail_configured(cfg):
        return 0
    sent = 0
    for r in recipients(db, ver):
        if r.user_id is None and r.token_expires_at and r.token_hash is None:
            continue  # An explicit revocation survives reminder ticks until manually reissued.
        if c['mode'] != 'info' and not ready(db, ver, r):
            continue
        initial = r.notified_at is None
        reminder = (reminders and c['mode'] != 'info' and not r.decision and c['reminder_days'] > 0
                    and (r.reminded_at or r.notified_at or utcnow()) <= utcnow() - timedelta(days=c['reminder_days']))
        if not initial and not reminder:
            continue
        url = guest_url(db, row, ver, r) if r.user_id is None else settings.portal_base_url.rstrip('/') + f'/umlaeufe/{row.id}'
        from .db import to_local
        subject = ('Erinnerung – ' if reminder else '') + action_label(c) + ': ' + c['title']
        due = to_local(at(c['due_on'])).strftime('%d.%m.%Y %H:%M') if c['due_on'] else 'Ohne feste Frist'
        owner = db.get(User, ver.published_by)
        body = f'Guten Tag {r.name},\n\n{action_label(c)}\n{c["title"]} · Fassung {ver.number}\nHerausgeber: {owner.name if owner else "Portal"}\nFrist: {due}\n'
        if ver.number > 1 and c['mode'] != 'info': body += 'Geänderte Fassung – erneute Rückmeldung erforderlich.\n'
        if c.get('email_summary'): body += '\n' + c['email_summary'] + '\n'
        body += f'\nDie Mappe enthält {len(c["items"])} Dokumente.\n'
        if c['mode'] != 'info' and c['per_item']:
            confirmed = {x.item_key for x in receipts(db, r)}
            labels = {'body':'Einleitung', **{i['key']:i['title'] for i in c['items']}}
            body += 'Noch offen: ' + ', '.join(labels[k] for k in requirement_keys(c) if k not in confirmed) + '\n'
        if c['mode'] == 'approval': body += 'Bitte freigeben oder mit Begründung ablehnen.\n'
        elif c['mode'] == 'ack': body += 'Bitte den Inhalt ausdrücklich persönlich zur Kenntnis nehmen.\n'
        button = 'Umlauf öffnen und entscheiden' if c['mode'] == 'approval' else 'Umlauf öffnen und Kenntnisnahme bestätigen' if c['mode'] == 'ack' else 'Information öffnen'
        body += '\n' + button + ':\n' + url + '\nDas Öffnen allein bestätigt nichts.\n'
        if r.user_id is None: body += '\nPersönlicher Gastlink: bitte nicht weitergeben. Gültig bis ' + to_local(r.token_expires_at).strftime('%d.%m.%Y %H:%M') + '.\n'
        if notify.enqueue(db, r.email, subject, body, 'circulation_personal', cfg):
            if initial: r.notified_at = utcnow()
            else: r.reminded_at = utcnow()
            sent += 1
            if r.user_id and c['mode']=='approval' and c.get('allow_proxy_approval'):
                active_proxy=absence.current(db,r.user_id)
                substitute=active_proxy.substitute if active_proxy else None
                if substitute and substitute.active and r.user_id in absence.represented(db,substitute):
                    proxy_url=settings.portal_base_url.rstrip('/')+f'/umlaeufe/{row.id}?recipient={r.id}'
                    proxy_body=(f'Guten Tag {substitute.name},\n\nFreigabe in Vertretung für {r.name} erforderlich.\n{c["title"]} · Fassung {ver.number}\nFrist: {due}\n\nDie Freigabe in Vertretung ist für diesen Umlauf ausdrücklich erlaubt. Ihre Handlung wird unter Ihrem Namen protokolliert.\n\nUmlauf öffnen und entscheiden:\n'+proxy_url+'\nDas Öffnen allein bestätigt nichts.')
                    notify.enqueue(db,substitute.email,'Vertretung – '+subject,proxy_body,'circulation_proxy',cfg)
    return sent


def tick():
    """Called by the existing worker, no additional scheduler or delivery subsystem."""
    sent = 0
    with SessionLocal() as db:
        if get_settings(db).get('module_circulations') != '1':
            return 0
        for row in db.scalars(select(Circulation).where(Circulation.current_version > 0, Circulation.archived.is_(False))):
            ver = version(db, row)
            if not active(row, ver) or expired(ver): continue
            c = content(ver)
            if c['dynamic']:
                sync_audience(db, row, ver)
            sent += dispatch(db, row, ver, reminders=True)
            if c['due_on'] and at(c['due_on']) < utcnow() and c['mode'] != 'info' and c['escalate_id']:
                target = db.get(User, c['escalate_id'])
                overdue = [r for r in recipients(db, ver) if not r.decision and not r.escalated_at]
                if target and target.active and overdue and notify.enqueue(db, target.email,
                    'Überfälliger Umlauf: ' + c['title'],
                    f'{len(overdue)} Bestätigung(en) fehlen. Bitte wenden Sie sich an den Herausgeber.\n' +
                    settings.portal_base_url.rstrip('/') + f'/umlaeufe/{row.id}', 'circulation_escalation'):
                    for r in overdue: r.escalated_at = utcnow()
                    sent += 1
        db.commit()
    return sent


def pending_tasks(db, user):
    """All open acknowledgements/approvals, including later sequential stations."""
    items = []
    for row in db.scalars(select(Circulation).where(Circulation.current_version > 0, Circulation.archived.is_(False))):
        ver = version(db, row)
        for rec in acting_recipients(db, ver, user):
            if rec and not rec.decision and active(row, ver) and not expired(ver) and content(ver)['mode'] != 'info':
                c = content(ver)
                done = len({r.item_key for r in receipts(db, rec)} & set(requirement_keys(c)))
                items.append(dict(row=row, title=c['title'], due=at(c['due_on']), ready=ready(db, ver, rec), action=action_label(c), done=done, required=len(requirement_keys(c)), proxy=rec.user_id != user.id, recipient_id=rec.id, recipient_name=rec.name, stopped=any(p.decision == 'rejected' for p in recipients(db, ver))))
    items.sort(key=lambda x: (x['due'] or datetime.max, x['row'].id))
    return items


def overview(db, user):
    items = pending_tasks(db, user)
    return dict(items=items[:6], count=len(items), overdue=sum(bool(i['due'] and i['due'] < utcnow()) for i in items))


def parse_date(value):
    if not value: return ''
    try:
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    except ValueError:
        raise HTTPException(422, 'Ungültiges Datum.')


def form_data(data, previous):
    def ids(key):
        return list(dict.fromkeys(int(x) for x in data.getlist(key) if str(x).isdigit()))
    c = default()
    for k, n in [('title', 255), ('body', 100000), ('category', 80), ('email_summary', 1000)]: c[k] = str(data.get(k, '')).strip()[:n]
    c['kind'] = 'circulation' if data.get('kind') == 'circulation' else 'notice'
    c['mode'] = str(data.get('mode', 'info'))
    if c['mode'] not in {'info', 'ack', 'approval'}: raise HTTPException(422, 'Ungültiger Modus.')
    for k in ['per_item', 'sequential', 'dynamic', 'public', 'pinned', 'review_requested', 'require_item_sequence', 'allow_proxy_approval', 'share_progress']: c[k] = data.get(k) == '1'
    for k in ['publish_on', 'due_on', 'expires_on']: c[k] = parse_date(str(data.get(k, '')))
    for k, lo, hi, val in [('reminder_days', 0, 90, 3), ('guest_days', 1, 365, 30)]:
        try: c[k] = max(lo, min(hi, int(data.get(k, val))))
        except (TypeError, ValueError): raise HTTPException(422, 'Ungültiges Erinnerungsintervall oder Linkdauer.')
    c['escalate_id'] = int(data['escalate_id']) if str(data.get('escalate_id', '')).isdigit() else None
    guests = []
    for line in str(data.get('guests', '')).splitlines():
        if not line.strip(): continue
        parts = line.strip().split(';', 1)
        email = parts[-1].strip().lower()
        if not re.fullmatch(r'[^\s@;<>]+@[^\s@;<>]+\.[^\s@;<>]+', email) or len(email) > 255:
            raise HTTPException(422, 'Gäste bitte als Name;E-Mail oder E-Mail je Zeile eintragen.')
        if email not in {g['email'] for g in guests}: guests.append(dict(name=parts[0].strip()[:255] if len(parts) == 2 else email, email=email))
    if len(guests) > 500: raise HTTPException(422, 'Maximal 500 Gäste pro Umlauf.')
    c['audience'] = dict(users=ids('users'), groups=ids('groups'), all=data.get('all') == '1', guests=guests)
    c['items'] = [i for i in previous.get('items', []) if i['key'] not in data.getlist('remove_item')]
    try: c['items'].sort(key=lambda i: int(data.get('order_'+i['key'], 100)))
    except (ValueError, TypeError): raise HTTPException(422, 'Ungültige Dokumentreihenfolge.')
    return c



def ordered_items(items, references, raw):
    """Order existing documents, new portal objects and uploads without accepting new data."""
    try:
        sequence = json.loads(raw)
    except ValueError:
        raise HTTPException(422, 'Ungültige Dokumentreihenfolge.') from None
    if not isinstance(sequence, list) or len(sequence) > 100 or any(not isinstance(ref, str) for ref in sequence):
        raise HTTPException(422, 'Ungültige Dokumentreihenfolge.')
    result, seen = [], set()
    for ref in sequence:
        item = references.get(ref)
        if item is None or item['key'] in seen:
            raise HTTPException(422, 'Die Dokumentauswahl hat sich geändert. Bitte die Mappe neu laden.')
        result.append(item)
        seen.add(item['key'])
    if seen != {item['key'] for item in items}:
        raise HTTPException(422, 'Die Dokumentauswahl ist unvollständig. Bitte die Mappe neu laden.')
    return result

def files_dir(row):
    path = settings.data_dir / ('circulation-bundles' if isinstance(row, CirculationBundle) else 'circulations') / str(row.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_path(row, item):
    name = item.get('file', '')
    if not re.fullmatch(r'[a-f0-9]{32}\.[a-z0-9]{1,8}', name):
        raise HTTPException(404)
    return files_dir(row) / name


def public_available(db):
    rows = db.execute(select(Circulation, CirculationVersion).join(CirculationVersion,
        (CirculationVersion.circulation_id == Circulation.id) &
        (CirculationVersion.number == Circulation.current_version)).where(Circulation.archived.is_(False)))
    return any(content(ver)['public'] and active(row, ver) and not expired(ver) for row, ver in rows)
