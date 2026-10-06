"""Terminbuchung (wie Microsoft Bookings oder Calendly).

Die anbietende Person legt im Kalender Zeitbereiche fest (z. B. „Di 9–12 Uhr“). Daraus entstehen
Zeitfenster der eingestellten Dauer, nach jedem Termin optional eine Pause. Gäste buchen ein freies
Zeitfenster selbst, bekommen eine Bestätigung mit Kalendereintrag und einem Link, über den sie den
Termin verschieben oder absagen können. Optional entsteht je Buchung eine eigene Videokonferenz.
"""

import io
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from . import csvsafe, ics, links, mailtpl, notify, planning
from .config import settings
from .db import (
    LOCAL_TZ, Booking, BookingInvite, BookingPage, BookingWindow, Group, Meeting, SessionLocal, User,
    get_settings, to_local, utcnow,
)
from .planning import EMAIL_RE
from .polls import WEEKDAYS, WEEKDAYS_LONG
from .security import new_link_token, room_slug

MAX_WINDOW_HOURS = 24
HORIZON_DAYS = 400


# --- Zeit ---------------------------------------------------------------------------

def to_utc(local: datetime) -> datetime:
    if local.tzinfo is None:
        local = local.replace(tzinfo=LOCAL_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def parse_local(value: str) -> datetime | None:
    """ISO-Zeit aus Formular oder Kalender (mit oder ohne Zeitzone) als UTC (naiv)."""
    try:
        return to_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00"))) if value else None
    except ValueError:
        return None


def label(start: datetime, end: datetime | None = None) -> str:
    s = to_local(start)
    text = f"{WEEKDAYS_LONG[s.weekday()]}, {s:%d.%m.%Y}, {s:%H:%M}"
    if end:
        text += f"–{to_local(end):%H:%M}"
    return text + " Uhr"


# --- Zeitfenster -----------------------------------------------------------------------

def add_window(db, page: BookingPage, start: datetime, end: datetime) -> str:
    """Zeitbereich anlegen. Überlappende Bereiche werden zusammengefasst. Gibt eine Fehlermeldung oder ''."""
    if end <= start:
        return "Das Ende muss nach dem Beginn liegen."
    if end - start > timedelta(hours=MAX_WINDOW_HOURS):
        return "Ein Zeitbereich darf höchstens 24 Stunden lang sein."
    if end - start < timedelta(minutes=page.slot_minutes):
        return f"Der Zeitbereich ist kürzer als ein Termin ({page.slot_minutes} Minuten)."
    for w in list(page.windows):
        if w.starts_at <= end and w.ends_at >= start:  # überlappt oder grenzt an
            start, end = min(start, w.starts_at), max(end, w.ends_at)
            page.windows.remove(w)
            db.delete(w)
    page.windows.append(BookingWindow(starts_at=start, ends_at=end))
    return ""


def slots(page: BookingPage, include_past: bool = False) -> list[dict]:
    """Alle Zeitfenster mit Belegung: {start, end, booked, free}."""
    step = timedelta(minutes=page.slot_minutes + page.pause_minutes)
    length = timedelta(minutes=page.slot_minutes)
    counts: dict[datetime, int] = {}
    for b in page.bookings:
        if b.status == "booked":
            counts[b.starts_at] = counts.get(b.starts_at, 0) + 1
    now = utcnow()
    found: dict[datetime, dict] = {}
    for w in page.windows:
        t = w.starts_at
        while t + length <= w.ends_at:
            if (include_past or t >= now) and t not in found:
                booked = counts.get(t, 0)
                found[t] = {"start": t, "end": t + length, "booked": booked, "free": max(page.capacity - booked, 0)}
            t += step
    return sorted(found.values(), key=lambda s: s["start"])


def bookable(page: BookingPage, keep: Booking | None = None) -> list[dict]:
    """Zeitfenster, die Gäste jetzt buchen können (Vorlauf beachtet). keep: eigene Buchung beim Umbuchen."""
    earliest = utcnow() + timedelta(hours=page.min_notice_hours)
    result = []
    for s in slots(page):
        own = keep is not None and keep.status == "booked" and keep.starts_at == s["start"]
        if s["start"] >= earliest and (s["free"] > 0 or own):
            result.append({**s, "own": own})
    return result


def group_by_day(items: list[dict]) -> list[dict]:
    days: dict[str, dict] = {}
    for s in items:
        local = to_local(s["start"])
        key = local.strftime("%Y-%m-%d")
        if key not in days:
            days[key] = {"key": key, "weekday": WEEKDAYS[local.weekday()], "weekday_long": WEEKDAYS_LONG[local.weekday()],
                         "date": local.strftime("%d.%m."), "full": local.strftime("%d.%m.%Y"), "slots": []}
        days[key]["slots"].append({**s, "time": local.strftime("%H:%M"), "iso": s["start"].isoformat()})
    return list(days.values())


def active_bookings(page: BookingPage) -> list[Booking]:
    return [b for b in page.bookings if b.status == "booked"]


def can_cancel(booking: Booking) -> bool:
    return booking.status == "booked" and \
        booking.starts_at - timedelta(hours=booking.page.cancel_hours) > utcnow()


# --- Links, Kalender, Mails ---------------------------------------------------------------

def public_link(page: BookingPage) -> str:
    return f"{links.base('bookings')}/b/{page.public_token}"


def invite_link(inv: BookingInvite) -> str:
    return f"{links.base('bookings')}/b/{inv.page.public_token}?i={inv.token}"


def manage_link(b: Booking) -> str:
    return f"{links.base('bookings')}/b/m/{b.token}"


def _uid(b: Booking) -> str:
    return f"booking-{b.id}@{urlparse(settings.portal_base_url).hostname or 'portal'}"


def join_link(db, b: Booking) -> str:
    if not b.meeting_id:
        return ""
    meeting = db.get(Meeting, b.meeting_id)
    inv = meeting.invitees[0] if meeting and meeting.invitees else None
    return planning.personal_link(inv) if inv else ""


def calendar(db, b: Booking, method: str = "REQUEST") -> str:
    page = b.page
    cfg = get_settings(db)
    link = join_link(db, b)
    text = (page.description + "\n\n" if page.description else "") + \
        (f"Videokonferenz: {link}\n" if link else "") + f"Termin verschieben oder absagen: {manage_link(b)}"
    return ics.build(method=method, uid=_uid(b), sequence=b.sequence, start=b.starts_at,
                     minutes=int((b.ends_at - b.starts_at).total_seconds() // 60), title=page.title,
                     description=text, location=link or page.location, url=link or manage_link(b),
                     organizer=planning.organizer_identity(cfg, page.owner),
                     attendees=[(b.name, b.email)], cancelled=method == "CANCEL")


def _values(db, b: Booking, extra: dict | None = None) -> dict:
    page = b.page
    link = join_link(db, b)
    values = {"name": b.name, "titel": page.title, "termin": label(b.starts_at, b.ends_at),
              "ort": f"Ort: {page.location}" if page.location and not link else "",
              "videolink": f"Teilnahme per Videokonferenz (im Browser, ohne Installation):\n{link}" if link else "",
              "verwalten": manage_link(b), "absagefrist": f"{page.cancel_hours} Stunden",
              "hinweis": page.confirm_text, "anbieter": page.owner.name if page.owner else ""}
    values.update(extra or {})
    return values


def _send_guest(db, b: Booking, key: str, method: str, extra: dict | None = None) -> bool:
    cfg = get_settings(db)
    subject, body = mailtpl.render(db, key, _values(db, b, extra), cfg)
    att = [{"filename": "absage.ics" if method == "CANCEL" else "termin.ics", "content": calendar(db, b, method),
            "calendar_method": method}]
    return notify.enqueue(db, b.email, subject, body, key, cfg,
                          reply_to=b.page.owner.email if b.page.owner else None, attachments=att)


def _notify_owner(db, b: Booking, event: str) -> None:
    page = b.page
    if not page.notify_owner or page.owner is None or not page.owner.active:
        return
    cfg = get_settings(db)
    subject, body = mailtpl.render(db, "booking_owner", _values(db, b, {
        "ereignis": event, "name": page.owner.name, "gast": f"{b.name} <{b.email}>" + (f", Tel. {b.phone}" if b.phone else ""),
        "nachricht": b.note or "", "frei": str(sum(s["free"] for s in bookable(page))),
        "link": f"{settings.portal_base_url}/bookings/{page.id}"}), cfg)
    notify.enqueue(db, page.owner.email, subject, body, "booking_owner", cfg)


# --- Buchen, Umbuchen, Absagen -----------------------------------------------------------

def _meeting_for(db, b: Booking) -> None:
    """Eigene Videokonferenz für die Buchung (Portal-Raum, persönlicher Link für den Gast)."""
    from .main import ensure_guest_token, unique_room  # vermeidet Importzyklus
    page = b.page
    if not page.online or page.owner is None:
        return
    meeting = Meeting(owner_id=page.owner_id, title=f"{page.title}: {b.name}"[:200],
                      room=unique_room(db, room_slug(page.title)), starts_at=b.starts_at,
                      duration_minutes=page.slot_minutes, description=b.note or None, ics_sequence=0)
    ensure_guest_token(meeting)
    db.add(meeting)
    db.flush()
    planning.ensure_uid(meeting)
    planning.add_invitees(db, meeting, [b.email])
    for inv in meeting.invitees:
        inv.name, inv.invited_at = b.name, utcnow()
    b.meeting_id = meeting.id


def check(page: BookingPage, start: datetime, email: str, keep: Booking | None = None) -> tuple[dict | None, str]:
    slot = next((s for s in bookable(page, keep) if s["start"] == start), None)
    if slot is None:
        return None, "Dieser Termin ist leider nicht mehr frei. Bitte wählen Sie einen anderen."
    if keep is None:
        mine = [b for b in active_bookings(page) if b.email == email and b.starts_at >= utcnow()]
        if len(mine) >= page.max_per_person:
            return None, ("Sie haben bereits einen Termin gebucht. Über den Link in Ihrer Bestätigung können Sie "
                          "ihn verschieben oder absagen.")
    return slot, ""


def book(db, page: BookingPage, start: datetime, name: str, email: str, phone: str = "", note: str = "",
         user: User | None = None, invite: BookingInvite | None = None) -> tuple[Booking | None, str]:
    slot, error = check(page, start, email)
    if error:
        return None, error
    b = Booking(page_id=page.id, starts_at=slot["start"], ends_at=slot["end"], name=name, email=email, phone=phone,
                note=note, user_id=user.id if user else None, invite_id=invite.id if invite else None,
                token=new_link_token())
    page.bookings.append(b)
    db.flush()
    _meeting_for(db, b)
    _send_guest(db, b, "booking_confirm", "REQUEST")
    _notify_owner(db, b, "Neue Buchung")
    return b, ""


def move(db, b: Booking, start: datetime) -> str:
    """Termin verschieben (Gast oder anbietende Person). Gibt eine Fehlermeldung oder ''."""
    if start == b.starts_at:
        return ""
    slot, error = check(b.page, start, b.email, keep=b)
    if error:
        return error
    b.starts_at, b.ends_at, b.sequence, b.reminded_at = slot["start"], slot["end"], b.sequence + 1, None
    if b.meeting_id:
        meeting = db.get(Meeting, b.meeting_id)
        if meeting:
            meeting.starts_at = b.starts_at
            meeting.ics_sequence = (meeting.ics_sequence or 0) + 1
    _send_guest(db, b, "booking_update", "REQUEST")
    _notify_owner(db, b, "Termin verschoben")
    return ""


def cancel(db, b: Booking, by: str, reason: str = "") -> None:
    if b.status != "booked":
        return
    b.status, b.cancelled_at, b.cancelled_by = "cancelled", utcnow(), by
    b.cancel_reason, b.sequence = reason[:1000], b.sequence + 1
    _send_guest(db, b, "booking_cancelled", "CANCEL", {
        "grund": f"Begründung: {reason}" if reason else "",
        "wer": "Sie haben" if by == "guest" else (f"{b.page.owner.name} hat" if b.page.owner else "Der Anbieter hat")})
    if by == "guest":
        _notify_owner(db, b, "Absage")
    if b.meeting_id:
        meeting = db.get(Meeting, b.meeting_id)
        if meeting:
            for rec in meeting.recordings:
                rec.meeting_id = None
            db.delete(meeting)
        b.meeting_id = None


# --- Einladungen ------------------------------------------------------------------------

def invite(db, page: BookingPage, actor: User, user_ids: list[int], group_ids: list[int],
           guests: list[tuple[str, str]]) -> tuple[int, int]:
    """Personen persönlich einladen (z. B. Bewerber:innen). guests: [(E-Mail, Name)]."""
    cfg = get_settings(db)
    existing = {i.email for i in page.invites}
    targets = list(guests)
    if user_ids:
        targets += [(u.email, u.name) for u in db.scalars(select(User).where(User.id.in_(user_ids), User.active.is_(True)))]
    for g in db.scalars(select(Group).where(Group.id.in_(group_ids))) if group_ids else []:
        targets += [(u.email, u.name) for u in g.members if u.active]
    added = skipped = 0
    for email, name in targets:
        if email in existing:
            skipped += 1
            continue
        existing.add(email)
        inv = BookingInvite(email=email, name=name or planning.name_from_email(email), token=new_link_token())
        page.invites.append(inv)
        db.flush()
        if _send_invite(db, inv, actor, "booking_invite", cfg):
            inv.invited_at = utcnow()
        added += 1
    return added, skipped


def _send_invite(db, inv: BookingInvite, actor: User, key: str, cfg) -> bool:
    page = inv.page
    days = group_by_day(bookable(page))
    span = f"{days[0]['full']} bis {days[-1]['full']}" if days else ""
    subject, body = mailtpl.render(db, key, {
        "name": inv.name, "titel": page.title, "beschreibung": page.description, "link": invite_link(inv),
        "absender": actor.name, "zeitraum": span, "dauer": f"{page.slot_minutes} Minuten",
        "ort": f"Ort: {page.location}" if page.location and not page.online else
        ("Das Gespräch findet als Videokonferenz statt; den Link erhalten Sie mit der Bestätigung." if page.online else "")},
        cfg)
    return notify.enqueue(db, inv.email, subject, body, key, cfg, reply_to=actor.email)


def booked_emails(page: BookingPage) -> set[str]:
    return {b.email for b in active_bookings(page)}


def remind_invites(db, page: BookingPage, actor: User) -> int:
    cfg = get_settings(db)
    done = booked_emails(page)
    count = 0
    for inv in page.invites:
        if inv.email not in done and _send_invite(db, inv, actor, "booking_invite_reminder", cfg):
            inv.reminded_at = utcnow()
            count += 1
    return count


def parse_guests(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Gäste aus Freitext: je Zeile „Name <mail>“, „mail, Name“, „mail;Name“ oder nur die Adresse."""
    import re
    guests, bad, seen = [], [], set()
    for raw in re.split(r"[\n]+", text or ""):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(.*?)<([^>]+)>\s*$", line)
        if m:
            name, email = m.group(1).strip(" ,;\""), m.group(2).strip()
        else:
            parts = [p.strip() for p in re.split(r"[;,\t]", line) if p.strip()]
            email = next((p for p in parts if "@" in p), "")
            name = " ".join(p for p in parts if p != email)
            if not email:  # mehrere Adressen in einer Zeile ohne Namen
                bad.append(line)
                continue
            extra = [p for p in parts if "@" in p and p != email]
            for e in extra:
                if EMAIL_RE.match(e.lower()) and e.lower() not in seen:
                    seen.add(e.lower())
                    guests.append((e.lower(), ""))
        email = email.lower()
        if not EMAIL_RE.match(email):
            bad.append(line)
        elif email not in seen:
            seen.add(email)
            guests.append((email, name[:120]))
    return guests, bad


# --- Erinnerungen (Worker) und Export ------------------------------------------------------

def send_reminders() -> int:
    now = utcnow()
    count = 0
    with SessionLocal() as db:
        due = db.scalars(select(Booking).where(Booking.status == "booked", Booking.reminded_at.is_(None),
                                               Booking.starts_at > now,
                                               Booking.starts_at <= now + timedelta(hours=72))).all()
        for b in due:
            hours = b.page.reminder_hours
            if not hours or b.starts_at - now > timedelta(hours=hours):
                continue
            # Kurzfristig gebuchte Termine nicht sofort wieder erinnern
            if b.created_at > b.starts_at - timedelta(hours=hours):
                b.reminded_at = now
                continue
            cfg = get_settings(db)
            subject, body = mailtpl.render(db, "booking_reminder", _values(db, b), cfg)
            notify.enqueue(db, b.email, subject, body, "booking_reminder", cfg)
            b.reminded_at = now
            count += 1
        db.commit()
    return count


# --- Terminliste: Filter und Export -------------------------------------------------------

STATUS_FILTERS = {"upcoming": "Anstehend", "past": "Vergangen", "cancelled": "Abgesagt", "all": "Alle"}
SORTS = {"start": "Termin (früheste zuerst)", "-start": "Termin (späteste zuerst)", "name": "Name",
         "-created": "Zuletzt gebucht"}


def filter_bookings(page: BookingPage, status: str = "upcoming", date_from: str = "", date_to: str = "",
                    q: str = "", sort: str = "start") -> list[Booking]:
    now = utcnow()
    items = list(page.bookings)
    if status == "upcoming":
        items = [b for b in items if b.status == "booked" and b.ends_at >= now]
    elif status == "past":
        items = [b for b in items if b.status == "booked" and b.ends_at < now]
    elif status == "cancelled":
        items = [b for b in items if b.status == "cancelled"]
    start = parse_local(f"{date_from}T00:00") if date_from else None
    end = parse_local(f"{date_to}T23:59:59") if date_to else None
    if start:
        items = [b for b in items if b.starts_at >= start]
    if end:
        items = [b for b in items if b.starts_at <= end]
    needle = (q or "").strip().lower()
    if needle:
        items = [b for b in items if needle in f"{b.name} {b.email} {b.phone} {b.note}".lower()]
    keys = {"start": lambda b: b.starts_at, "-start": lambda b: b.starts_at, "name": lambda b: b.name.lower(),
            "-created": lambda b: b.created_at}
    items.sort(key=keys.get(sort, keys["start"]), reverse=sort in ("-start", "-created"))
    return items


def _row(b: Booking) -> dict:
    return {"id": b.id, "beginn": to_local(b.starts_at).isoformat(timespec="minutes"),
            "ende": to_local(b.ends_at).isoformat(timespec="minutes"), "name": b.name, "email": b.email,
            "telefon": b.phone or None, "nachricht": b.note or None,
            "status": "gebucht" if b.status == "booked" else "abgesagt",
            "gebucht_am": to_local(b.created_at).isoformat(timespec="seconds"),
            "abgesagt_von": {"guest": "Gast", "owner": "Anbieter"}.get(b.cancelled_by) if b.status != "booked" else None,
            "absagegrund": b.cancel_reason or None}


def to_csv(page: BookingPage, items: list[Booking] | None = None) -> str:
    items = page.bookings if items is None else items
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    w.writerow(["Datum", "Beginn", "Ende", "Name", "E-Mail", "Telefon", "Nachricht", "Status", "Gebucht am",
                "Abgesagt von", "Grund"])
    for b in items:
        r = _row(b)
        w.writerow([to_local(b.starts_at).strftime("%d.%m.%Y"), to_local(b.starts_at).strftime("%H:%M"),
                    to_local(b.ends_at).strftime("%H:%M"), b.name, b.email, b.phone, b.note, r["status"],
                    to_local(b.created_at).strftime("%d.%m.%Y %H:%M"), r["abgesagt_von"] or "", b.cancel_reason])
    return "\ufeff" + buf.getvalue()


def to_json(page: BookingPage, items: list[Booking]) -> str:
    import json
    return json.dumps({"buchungsseite": {"id": page.id, "titel": page.title, "ort": page.location or None,
                                         "dauer_minuten": page.slot_minutes, "online": page.online,
                                         "exportiert": to_local(utcnow()).isoformat(timespec="seconds")},
                       "termine": [_row(b) for b in items]}, ensure_ascii=False, indent=2)


def to_markdown(page: BookingPage, items: list[Booking]) -> str:
    def cell(text) -> str:
        return str(text or "").replace("|", "\\|").replace("\n", " ").strip()
    lines = [f"# {cell(page.title)}", "", f"Stand: {to_local(utcnow()):%d.%m.%Y, %H:%M} Uhr · {len(items)} Termin(e)", "",
             "| Datum | Zeit | Name | E-Mail | Telefon | Nachricht | Status |", "|---|---|---|---|---|---|---|"]
    for b in items:
        s, e = to_local(b.starts_at), to_local(b.ends_at)
        lines.append(f"| {WEEKDAYS[s.weekday()]}, {s:%d.%m.%Y} | {s:%H:%M}–{e:%H:%M} | {cell(b.name)} | {cell(b.email)} | "
                     f"{cell(b.phone)} | {cell(b.note)} | {'gebucht' if b.status == 'booked' else 'abgesagt'} |")
    return "\n".join(lines) + "\n"


def to_ics(page: BookingPage, items: list[Booking], name: str = "") -> str:
    """Mehrere Termine als Kalenderdatei (zum Importieren oder Abonnieren)."""
    events = []
    for b in items:
        text = ics.build(method="PUBLISH", uid=_uid(b), sequence=b.sequence, start=b.starts_at,
                         minutes=int((b.ends_at - b.starts_at).total_seconds() // 60),
                         title=f"{page.title}: {b.name}" + (" (abgesagt)" if b.status != "booked" else ""),
                         description="\n".join(x for x in (f"{b.name} <{b.email}>", f"Tel. {b.phone}" if b.phone else "",
                                                           b.note) if x),
                         location=page.location, url=f"{settings.portal_base_url}/bookings/{page.id}", organizer=None,
                         attendees=[], cancelled=b.status != "booked", alarm_minutes=15)
        lines = text.split("\r\n")
        start, end = lines.index("BEGIN:VEVENT"), lines.index("END:VEVENT")
        events += lines[start:end + 1]
    head = ["BEGIN:VCALENDAR", f"PRODID:{ics.PRODID}", "VERSION:2.0", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
            f"X-WR-CALNAME:{name or page.title}", "X-PUBLISHED-TTL:PT15M", "REFRESH-INTERVAL;VALUE=DURATION:PT15M"]
    return "\r\n".join(head + events + ["END:VCALENDAR"]) + "\r\n"


def feed_link(page: BookingPage) -> str:
    return f"{links.base('bookings')}/b/feed/{page.feed_token}.ics" if page.feed_token else ""


def calendar_events(page: BookingPage) -> list[dict]:
    """Daten für den Kalender der anbietenden Person (FullCalendar)."""
    events = [{"id": f"w{w.id}", "start": to_local(w.starts_at).isoformat(), "end": to_local(w.ends_at).isoformat(),
               "display": "background", "classNames": ["bk-window"], "extendedProps": {"kind": "window", "wid": w.id}}
              for w in page.windows]
    for b in active_bookings(page):
        events.append({"id": f"b{b.id}", "title": b.name, "start": to_local(b.starts_at).isoformat(),
                       "end": to_local(b.ends_at).isoformat(), "classNames": ["bk-booking"],
                       "extendedProps": {"kind": "booking", "bid": b.id}})
    return events


def horizon_ok(start: datetime) -> bool:
    return utcnow() - timedelta(days=1) <= start <= utcnow() + timedelta(days=HORIZON_DAYS)
