"""Terminumfragen (wie Doodle).

Die planende Person schlägt Termine vor (ganze Tage oder Uhrzeiten). Teilnehmende antworten je
Termin mit Ja, Wenn nötig (abschaltbar) oder Nein – über den öffentlichen Link mit Namen oder über
ihren persönlichen Link aus einer Einladung. Danach legt die planende Person den Termin fest;
auf Wunsch entsteht daraus direkt eine Besprechung mit Kalendereinladungen.
"""

import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from . import ics, mailtpl, notify
from .config import settings
from .db import LOCAL_TZ, Group, Poll, PollOption, PollParticipant, User, get_settings, to_local, utcnow
from .planning import EMAIL_RE
from .security import new_link_token

ANSWERS = {"yes": ("Ja", "fa-check", "success"), "maybe": ("Wenn nötig", "fa-question", "warning"),
           "no": ("Nein", "fa-xmark", "danger")}
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MAX_OPTIONS = 200


# --- Terminvorschläge ---------------------------------------------------------------

def _utc(local: datetime) -> datetime:
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def parse_options(raw: str) -> list[dict]:
    """Vorschläge aus dem Formular (JSON: [{date, start, end, note}]). Ohne start: ganztägig."""
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    result, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            day = date.fromisoformat(str(item.get("date", "")))
        except ValueError:
            continue
        start, end = str(item.get("start") or "").strip(), str(item.get("end") or "").strip()
        try:
            if start:
                begin = _utc(datetime.fromisoformat(f"{day}T{start}"))
                finish = _utc(datetime.fromisoformat(f"{day}T{end}")) if end else None
                if finish is not None and finish <= begin:
                    finish = None
                opt = {"starts_at": begin, "ends_at": finish, "all_day": False}
            else:
                opt = {"starts_at": datetime.combine(day, datetime.min.time()), "ends_at": None, "all_day": True}
        except ValueError:
            continue
        key = (opt["starts_at"], opt["ends_at"], opt["all_day"])
        if key in seen:
            continue
        seen.add(key)
        opt["note"] = " ".join(str(item.get("note") or "").split())[:120]
        result.append(opt)
    return sorted(result, key=lambda o: o["starts_at"])[:MAX_OPTIONS]


def option_parts(opt: PollOption) -> dict:
    """Anzeige eines Vorschlags: Monat, Tag, Wochentag, Uhrzeit (Ortszeit)."""
    if opt.all_day:
        day = opt.starts_at
        return {"month": MONTHS[day.month - 1], "year": day.year, "day": day.strftime("%d"),
                "weekday": WEEKDAYS[day.weekday()],
                "time": "ganztägig", "date": day.strftime("%d.%m.%Y"),
                "label": f"{WEEKDAYS_LONG[day.weekday()]}, {day:%d.%m.%Y} (ganztägig)"}
    start = to_local(opt.starts_at)
    end = to_local(opt.ends_at) if opt.ends_at else None
    time = f"{start:%H:%M}" + (f"–{end:%H:%M}" if end else "")
    return {"month": MONTHS[start.month - 1], "year": start.year, "day": start.strftime("%d"),
            "weekday": WEEKDAYS[start.weekday()],
            "time": time, "date": start.strftime("%d.%m.%Y"),
            "label": f"{WEEKDAYS_LONG[start.weekday()]}, {start:%d.%m.%Y}, {time} Uhr"}


def option_input(opt: PollOption) -> dict:
    """Vorschlag zurück in Formularwerte (Ortszeit) – für die Bearbeitung."""
    if opt.all_day:
        return {"id": opt.id, "date": opt.starts_at.date().isoformat(), "start": "", "end": "", "note": opt.note}
    start = to_local(opt.starts_at)
    end = to_local(opt.ends_at) if opt.ends_at else None
    return {"id": opt.id, "date": start.date().isoformat(), "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M") if end else "", "note": opt.note}


def set_options(db, poll: Poll, wanted: list[dict]) -> None:
    """Gleicht die Vorschläge ab: bestehende (gleicher Zeitpunkt) bleiben samt Antworten erhalten."""
    key = lambda o: (o["starts_at"], o["ends_at"], o["all_day"]) if isinstance(o, dict) \
        else (o.starts_at, o.ends_at, o.all_day)  # noqa: E731
    wanted_by_key = {key(w): w for w in wanted}
    for opt in list(poll.options):
        if key(opt) in wanted_by_key:
            opt.note = wanted_by_key.pop(key(opt))["note"]
        else:
            poll.options.remove(opt)
            db.delete(opt)
    for item in wanted_by_key.values():
        poll.options.append(PollOption(**item))
    if poll.final_option_id and poll.final_option_id not in {o.id for o in poll.options}:
        poll.final_option_id = None


# --- Auswertung ---------------------------------------------------------------------

def is_open(poll: Poll) -> bool:
    return not poll.closed and not (poll.expires_at and poll.expires_at < utcnow())


def tally(poll: Poll, exclude: PollParticipant | None = None) -> dict[int, dict]:
    """Je Vorschlag: Anzahl Ja / Wenn nötig / Nein und Punkte (Ja = 2, Wenn nötig = 1)."""
    result = {o.id: {"yes": 0, "maybe": 0, "no": 0, "score": 0} for o in poll.options}
    for p in poll.participants:
        if exclude is not None and p.id == exclude.id:
            continue
        for oid, answer in p.answers.items():
            row = result.get(int(oid)) if str(oid).isdigit() else None
            if row is not None and answer in ANSWERS:
                row[answer] += 1
                row["score"] += 2 if answer == "yes" else 1 if answer == "maybe" else 0
    return result


def best(poll: Poll, counts: dict[int, dict]) -> set[int]:
    """Vorschläge mit den meisten Zusagen (bei Gleichstand zählen die „Wenn nötig“)."""
    if not counts:
        return set()
    top = max((c["yes"], c["maybe"]) for c in counts.values())
    if top == (0, 0):
        return set()
    return {oid for oid, c in counts.items() if (c["yes"], c["maybe"]) == top}


def full_options(poll: Poll, participant: PollParticipant | None = None) -> set[int]:
    """Vorschläge, deren Plätze (Ja-Stimmen) schon vergeben sind – ohne die eigene Stimme."""
    if not poll.max_per_option:
        return set()
    counts = tally(poll, exclude=participant)
    return {oid for oid, c in counts.items() if c["yes"] >= poll.max_per_option}


def read_answers(poll: Poll, data, participant: PollParticipant | None) -> tuple[dict, str]:
    """Antworten aus dem Formular prüfen. Gibt (Antworten, Fehlermeldung) zurück."""
    allowed = set(ANSWERS) if poll.allow_maybe else {"yes", "no"}
    answers = {}
    for opt in poll.options:
        value = str(data.get(f"o_{opt.id}", "no"))
        answers[str(opt.id)] = value if value in allowed else "no"
    if poll.single_choice:
        choice = str(data.get("choice", ""))
        answers = {str(o.id): ("yes" if str(o.id) == choice else "no") for o in poll.options}
    yes = [oid for oid, a in answers.items() if a == "yes"]
    if poll.single_choice and not yes:
        return answers, "Bitte einen Termin auswählen."
    taken = full_options(poll, participant) & {int(o) for o in yes}
    if taken:
        labels = ", ".join(option_parts(o)["label"] for o in poll.options if o.id in taken)
        return answers, f"Für diesen Termin sind keine Plätze mehr frei: {labels}"
    return answers, ""


def to_csv(poll: Poll) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Name", "E-Mail", "Geantwortet", *[option_parts(o)["label"] for o in poll.options], "Kommentar"])
    for p in poll.participants:
        if not p.answered_at:
            continue
        a = p.answers
        writer.writerow([p.name, p.email, to_local(p.answered_at).strftime("%d.%m.%Y %H:%M"),
                         *[ANSWERS.get(a.get(str(o.id), ""), ("–",))[0] for o in poll.options], p.comment])
    counts = tally(poll)
    writer.writerow(["Summe Ja", "", "", *[counts[o.id]["yes"] for o in poll.options], ""])
    if poll.allow_maybe:
        writer.writerow(["Summe Wenn nötig", "", "", *[counts[o.id]["maybe"] for o in poll.options], ""])
    return "﻿" + buf.getvalue()


# --- Links, Einladungen, Mails ---------------------------------------------------------

def public_link(poll: Poll) -> str:
    return f"{settings.portal_base_url}/t/{poll.public_token}"


def personal_link(p: PollParticipant) -> str:
    return f"{settings.portal_base_url}/t/p/{p.edit_token}"


def deadline_text(poll: Poll) -> str:
    return ("Bitte bis " + to_local(poll.expires_at).strftime("%d.%m.%Y, %H:%M Uhr") + " abstimmen.") \
        if poll.expires_at else ""


def _mail(db, poll: Poll, p: PollParticipant, key: str, actor: User | None, cfg, extra=None) -> bool:
    values = {"name": p.name or p.email, "titel": poll.title, "beschreibung": poll.description,
              "ort": poll.location, "link": personal_link(p), "absender": actor.name if actor else "",
              "frist": deadline_text(poll), "vorschlaege": str(len(poll.options))}
    extra = dict(extra or {})
    attachments = extra.pop("_attachments", None)
    values.update(extra)
    subject, body = mailtpl.render(db, key, values, cfg)
    return notify.enqueue(db, p.email, subject, body, key, cfg, reply_to=actor.email if actor else None,
                          attachments=attachments)


def invite(db, poll: Poll, actor: User, user_ids: list[int], group_ids: list[int],
           emails: list[str]) -> tuple[int, int]:
    """Lädt Benutzer, Gruppenmitglieder und Gäste mit persönlichem Link ein. Gibt (neu, schon dabei)."""
    cfg = get_settings(db)
    existing = {p.email for p in poll.participants if p.email}
    targets: list[tuple[str, str, int | None]] = []
    if user_ids:
        targets += [(u.email, u.name, u.id) for u in db.scalars(select(User).where(User.id.in_(user_ids),
                                                                                  User.active.is_(True)))]
    for g in db.scalars(select(Group).where(Group.id.in_(group_ids))) if group_ids else []:
        targets += [(u.email, u.name, u.id) for u in g.members if u.active]
    for email in emails:
        user = db.scalar(select(User).where(User.email == email))
        targets.append((email, user.name if user else "", user.id if user else None))
    added = skipped = 0
    for email, name, uid in targets:
        if email in existing:
            skipped += 1
            continue
        existing.add(email)
        p = PollParticipant(email=email, name=name or email.split("@")[0], user_id=uid, edit_token=new_link_token())
        poll.participants.append(p)
        db.flush()
        if _mail(db, poll, p, "poll_invite", actor, cfg):
            p.invited_at = utcnow()
        added += 1
    return added, skipped


def remind(db, poll: Poll, actor: User) -> int:
    cfg = get_settings(db)
    count = 0
    for p in poll.participants:
        if p.email and not p.answered_at and _mail(db, poll, p, "poll_reminder", actor, cfg):
            p.reminded_at = utcnow()
            count += 1
    return count


def notify_vote(db, poll: Poll, p: PollParticipant, changed: bool) -> None:
    if not poll.notify_votes or poll.owner is None or not poll.owner.active:
        return
    cfg = get_settings(db)
    a = p.answers
    lines = [f"{option_parts(o)['label']}: {ANSWERS.get(a.get(str(o.id), 'no'), ('–',))[0]}" for o in poll.options]
    counts = tally(poll)
    top = best(poll, counts)
    stand = "; ".join(f"{option_parts(o)['label']} ({counts[o.id]['yes']} Ja)" for o in poll.options if o.id in top)
    subject, body = mailtpl.render(db, "poll_vote", {
        "name": poll.owner.name, "titel": poll.title, "teilnehmer": p.name + (f" <{p.email}>" if p.email else ""),
        "aktion": "hat die Antwort geändert" if changed else "hat abgestimmt", "antworten": "\n".join(lines),
        "kommentar": p.comment, "stand": stand or "noch keine Zusagen",
        "anzahl": str(sum(1 for x in poll.participants if x.answered_at)),
        "link": f"{settings.portal_base_url}/polls/{poll.id}"}, cfg)
    notify.enqueue(db, poll.owner.email, subject, body, "poll_vote", cfg)


def final_calendar(poll: Poll, opt: PollOption) -> str:
    start = opt.starts_at
    minutes = int((opt.ends_at - opt.starts_at).total_seconds() // 60) if opt.ends_at else poll.duration_minutes or 60
    if opt.all_day:
        start, minutes = _utc(opt.starts_at.replace(hour=9)), poll.duration_minutes or 60
    return ics.build(method="PUBLISH", uid=f"poll-{poll.id}-{opt.id}@{settings.portal_base_url.split('//')[-1]}",
                     sequence=0, start=start, minutes=minutes, title=poll.title, description=poll.description,
                     location=poll.location, url=f"{settings.portal_base_url}", organizer=None, attendees=[])


def announce_final(db, poll: Poll, actor: User) -> int:
    """Teilt allen Teilnehmenden mit E-Mail den festgelegten Termin mit (mit Kalenderdatei)."""
    opt = poll.final_option
    if opt is None:
        return 0
    cfg = get_settings(db)
    cal = final_calendar(poll, opt)
    count = 0
    for p in poll.participants:
        if p.email and _mail(db, poll, p, "poll_final", actor, cfg, {
                "termin": option_parts(opt)["label"],
                "_attachments": [{"filename": "termin.ics", "content": cal, "mime": "text/calendar"}]}):
            count += 1
    return count


def option_start_local(opt: PollOption, poll: Poll) -> tuple[datetime, int]:
    """Beginn (UTC) und Dauer für eine Besprechung aus dem festgelegten Vorschlag."""
    if opt.all_day:
        return _utc(opt.starts_at.replace(hour=9)), poll.duration_minutes or 60
    minutes = int((opt.ends_at - opt.starts_at).total_seconds() // 60) if opt.ends_at else poll.duration_minutes
    return opt.starts_at, max(15, minutes or 60)


def participant_emails(poll: Poll, only_yes: bool) -> list[str]:
    emails = []
    for p in poll.participants:
        if not p.email or not EMAIL_RE.match(p.email):
            continue
        if only_yes and p.answers.get(str(poll.final_option_id)) not in ("yes", "maybe"):
            continue
        emails.append(p.email)
    return list(dict.fromkeys(emails))


def clean_name(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:120]


def default_deadline() -> datetime:
    return utcnow() + timedelta(days=7)
