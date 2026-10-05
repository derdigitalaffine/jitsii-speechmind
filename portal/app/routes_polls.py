"""Seiten der Terminumfragen: anlegen, auswerten, teilen, festlegen und öffentlich abstimmen."""

import json
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from . import access, planning, polls as pl, shares as sh, shortlinks as sl, worker
from .db import LOCAL_TZ, Group, Meeting, Poll, PollParticipant, User, to_local, utcnow
from .main import (
    app, check_csrf, current_user, home_for, ensure_guest_token, flash, get_db, rate_limit, redirect, render, require,
    session_user, unique_room,
)
from .planning import parse_emails
from .security import new_link_token, room_slug

poll_user = require("polls")
COOKIE = "jsm_poll_"


def _poll(db: Session, poll_id: int, user: User, need: int) -> tuple[Poll, int]:
    """Terminumfrage mit Zugriffsprüfung. need: sh.VIEW, sh.INVITE, sh.EDIT oder sh.OWNER."""
    poll = db.get(Poll, poll_id)
    level = sh.access_level(db, "poll", poll, user)
    if level == 0:
        raise HTTPException(404, "Terminumfrage nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diese Aktion reicht Ihre Freigabe für die Terminumfrage nicht aus.")
    return poll, level


def _parse_local(value: str) -> datetime | None:
    try:
        local = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None) if local else None


def _apply_settings(poll: Poll, data) -> None:
    flag = lambda key: data.get(key) == "1"  # noqa: E731
    poll.title = " ".join(str(data.get("title", "")).split())[:255] or poll.title or "Terminumfrage"
    poll.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:5000]
    poll.location = " ".join(str(data.get("location", "")).split())[:255]
    duration = str(data.get("duration", "60"))
    poll.duration_minutes = int(duration) if duration.isdigit() and 5 <= int(duration) <= 1440 else 60
    poll.expires_at = _parse_local(str(data.get("expires_at", "")))
    poll.allow_maybe = flag("allow_maybe")
    poll.hidden = flag("hidden")
    poll.single_choice = flag("single_choice")
    limit = str(data.get("max_per_option", "")).strip()
    poll.max_per_option = int(limit) if limit.isdigit() and int(limit) > 0 else None
    poll.require_email = flag("require_email")
    poll.notify_votes = flag("notify_votes")


def _form_ctx(poll: Poll | None) -> dict:
    options = [pl.option_input(o) for o in poll.options] if poll else []
    expires = to_local(poll.expires_at).strftime("%Y-%m-%dT%H:%M") if poll and poll.expires_at else ""
    return {"poll": poll, "options_data": options, "expires": expires, "durations": planning.DURATIONS}


# --- Verwaltung ----------------------------------------------------------------------

@app.get("/polls")
def polls_list(request: Request, all: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    show_all = user.is_admin and all == "1"
    shared = [] if show_all else sh.shared_with(db, "poll", user)
    if not user.can("polls") and not shared:
        raise HTTPException(403, "Für den Bereich „Terminumfragen“ fehlt die Berechtigung. "
                                 "Bitte wenden Sie sich an die Verwaltung des Portals.")
    q = select(Poll).options(joinedload(Poll.owner)).order_by(Poll.updated_at.desc())
    if not show_all:
        q = q.where(Poll.owner_id == user.id)
    items = db.scalars(q).unique().all() if user.can("polls") else []
    counts = dict(db.execute(select(PollParticipant.poll_id, func.count(PollParticipant.id))
                             .where(PollParticipant.answered_at.is_not(None))
                             .group_by(PollParticipant.poll_id)).all())
    return render(request, "polls.html", user, polls=items, counts=counts, show_all=show_all, is_open=pl.is_open,
                  parts=pl.option_parts, shared=shared, levels=sh.LEVELS["poll"])


@app.get("/polls/new")
def poll_new(request: Request, user: User = Depends(poll_user)):
    return render(request, "poll_edit.html", user, **_form_ctx(None))


@app.post("/polls/new", dependencies=[Depends(check_csrf)])
async def poll_create(request: Request, user: User = Depends(poll_user), db: Session = Depends(get_db)):
    data = await request.form()
    options = pl.parse_options(str(data.get("options_json", "")))
    if not options:
        flash(request, "Bitte mindestens einen Terminvorschlag angeben.", "error")
        return redirect("/polls/new")
    poll = Poll(owner_id=user.id, title="", public_token=new_link_token())
    _apply_settings(poll, data)
    db.add(poll)
    pl.set_options(db, poll, options)
    db.commit()
    flash(request, f"Terminumfrage mit {len(options)} Vorschlägen angelegt. Teilen Sie jetzt den Link oder laden "
                   "Sie Teilnehmende ein.")
    return redirect(f"/polls/{poll.id}#teilen")


@app.get("/polls/{poll_id}")
def poll_detail(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.VIEW)
    counts = pl.tally(poll)
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
    groups = db.scalars(select(Group).order_by(Group.name)).all()
    public = pl.public_link(poll) if poll.public_token else ""
    answered_n = sum(1 for p in poll.participants if p.answered_at) or 1
    ranking = []
    for o in sorted(poll.options, key=lambda o: (-counts[o.id]["yes"], -counts[o.id]["maybe"], o.starts_at))[:3]:
        c = counts[o.id]
        ranking.append({"option": o, **c, "missing": max(answered_n - c["yes"] - c["maybe"] - c["no"], 0),
                        "yes_pct": round(100 * c["yes"] / answered_n), "maybe_pct": round(100 * c["maybe"] / answered_n)})
    return render(request, "poll.html", user, poll=poll, counts=counts, best=pl.best(poll, counts), ranking=ranking,
                  parts=pl.option_parts, answers=pl.ANSWERS, is_open=pl.is_open(poll), public_url=public,
                  personal_link=pl.personal_link, users=users, groups=groups, errors=sl.QR_ERRORS,
                  answered=[p for p in poll.participants if p.answered_at],
                  waiting=[p for p in poll.participants if not p.answered_at],
                  shortlink_url=("/shortlinks?new=" + quote(public) + "&title=" + quote(poll.title)
                                 + "&next=" + quote(f"/polls/{poll.id}") + "#neu") if public else "",
                  level=level, share_levels=sh.LEVELS["poll"])


@app.get("/polls/{poll_id}/edit")
def poll_edit(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return render(request, "poll_edit.html", user, **_form_ctx(_poll(db, poll_id, user, sh.EDIT)[0]))


@app.post("/polls/{poll_id}/edit", dependencies=[Depends(check_csrf)])
async def poll_update(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.EDIT)
    data = await request.form()
    options = pl.parse_options(str(data.get("options_json", "")))
    if not options:
        flash(request, "Bitte mindestens einen Terminvorschlag angeben.", "error")
        return redirect(f"/polls/{poll.id}/edit")
    _apply_settings(poll, data)
    pl.set_options(db, poll, options)
    db.commit()
    flash(request, "Terminumfrage gespeichert. Antworten zu unveränderten Vorschlägen bleiben erhalten.")
    return redirect(f"/polls/{poll.id}")


@app.post("/polls/{poll_id}/state", dependencies=[Depends(check_csrf)])
def poll_state(request: Request, poll_id: int, action: str = Form(...), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.EDIT if action in ("close", "reopen") else sh.INVITE)
    if action == "close":
        poll.closed = True
        flash(request, "Abstimmung beendet. Die Ergebnisse bleiben sichtbar.")
    elif action == "reopen":
        poll.closed = False
        flash(request, "Abstimmung wieder geöffnet.")
    elif action == "renew":
        poll.public_token = new_link_token()
        flash(request, "Neuer Link erzeugt. Der bisherige funktioniert nicht mehr.")
    elif action == "disable_link":
        poll.public_token = None
        flash(request, "Öffentlicher Link abgeschaltet. Persönliche Links gelten weiter.")
    elif action == "enable_link":
        poll.public_token = new_link_token()
        flash(request, "Öffentlicher Link erzeugt.")
    db.commit()
    return redirect(f"/polls/{poll.id}")


@app.post("/polls/{poll_id}/final", dependencies=[Depends(check_csrf)])
def poll_final(request: Request, poll_id: int, option_id: int = Form(...), notify: str = Form(""),
               create_meeting: str = Form(""), only_yes: str = Form(""), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Termin festlegen: Abstimmung schließen, auf Wunsch alle informieren oder eine Besprechung anlegen."""
    poll, level = _poll(db, poll_id, user, sh.EDIT)
    opt = next((o for o in poll.options if o.id == option_id), None)
    if opt is None:
        raise HTTPException(404)
    poll.final_option_id, poll.closed = opt.id, True
    label = pl.option_parts(opt)["label"]
    if create_meeting == "1" and user.can("video"):
        starts_at, minutes = pl.option_start_local(opt, poll)
        description = "\n\n".join(x for x in (poll.description, f"Ort: {poll.location}" if poll.location else "") if x)
        meeting = Meeting(owner_id=user.id, title=poll.title[:200], room=unique_room(db, room_slug(poll.title)),
                          starts_at=starts_at, duration_minutes=minutes, description=description or None,
                          ics_sequence=0)
        ensure_guest_token(meeting)
        db.add(meeting)
        db.flush()
        planning.ensure_uid(meeting)
        added = planning.add_invitees(db, meeting, pl.participant_emails(poll, only_yes == "1"))
        count, mail_ready = planning.send(db, meeting, added, "invite", user, copy_to_organizer=True)
        poll.meeting_id = meeting.id
        db.commit()
        access.sync(db)
        worker.wake()
        flash(request, f"Termin festgelegt: {label}. Besprechung angelegt"
              + (f", {count} Einladung(en) mit Kalendereintrag werden verschickt." if mail_ready else
                 " – Mailversand ist nicht eingerichtet, es gingen keine Einladungen raus."))
        return redirect(f"/meetings/{meeting.id}")
    sent = pl.announce_final(db, poll, user) if notify == "1" else 0
    db.commit()
    worker.wake()
    flash(request, f"Termin festgelegt: {label}." + (f" {sent} Teilnehmende werden per Mail informiert." if sent else ""))
    return redirect(f"/polls/{poll.id}")


@app.post("/polls/{poll_id}/invite", dependencies=[Depends(check_csrf)])
async def poll_invite(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.INVITE)
    data = await request.form()
    emails, bad = parse_emails(str(data.get("emails", "")))
    if bad:
        flash(request, "Ungültige E-Mail-Adresse: " + ", ".join(bad), "error")
        return redirect(f"/polls/{poll.id}#teilen")
    added, skipped = pl.invite(db, poll, user, [int(v) for v in data.getlist("users") if str(v).isdigit()],
                               [int(v) for v in data.getlist("groups") if str(v).isdigit()], emails)
    db.commit()
    worker.wake()
    if added or skipped:
        flash(request, f"{added} Person(en) eingeladen" + (f", {skipped} waren schon dabei" if skipped else "") + ".")
    else:
        flash(request, "Bitte Personen, Gruppen oder E-Mail-Adressen auswählen.", "error")
    return redirect(f"/polls/{poll.id}#teilnehmende")


@app.post("/polls/{poll_id}/remind", dependencies=[Depends(check_csrf)])
def poll_remind(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.INVITE)
    count = pl.remind(db, poll, user)
    db.commit()
    worker.wake()
    flash(request, f"Erinnerung an {count} Person(en) wird verschickt." if count else
          "Niemand mehr offen (oder Mailversand nicht eingerichtet).")
    return redirect(f"/polls/{poll.id}#teilnehmende")


@app.post("/polls/{poll_id}/participants/{pid}/delete", dependencies=[Depends(check_csrf)])
def poll_participant_delete(request: Request, poll_id: int, pid: int, user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.EDIT)
    p = db.get(PollParticipant, pid)
    if p is None or p.poll_id != poll.id:
        raise HTTPException(404)
    db.delete(p)
    db.commit()
    flash(request, f"{p.name or p.email} entfernt. Der persönliche Link funktioniert nicht mehr.")
    return redirect(f"/polls/{poll.id}#teilnehmende")


@app.get("/polls/{poll_id}/export.csv")
def poll_export(poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.VIEW)
    name = room_slug(poll.title) or "terminumfrage"
    return Response(pl.to_csv(poll), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@app.get("/polls/{poll_id}/qr.{fmt}")
def poll_qr(poll_id: int, fmt: str, size: int = 10, dark: str = "#000000", light: str = "#ffffff",
            error: str = "m", border: int = 2, download: str = "", user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.INVITE)
    if not poll.public_token:
        raise HTTPException(404)
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    data, media = sl.qr_image(pl.public_link(poll), opts)
    headers = {"Cache-Control": "private, max-age=60"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="qr-terminumfrage-{poll.id}.{opts["fmt"]}"'
    return Response(data, media_type=media, headers=headers)


@app.post("/polls/{poll_id}/copy", dependencies=[Depends(check_csrf)])
def poll_copy(request: Request, poll_id: int, user: User = Depends(poll_user), db: Session = Depends(get_db)):
    poll, _ = _poll(db, poll_id, user, sh.VIEW)
    clone = Poll(owner_id=user.id, title=(poll.title + " (Kopie)")[:255], description=poll.description,
                 location=poll.location, duration_minutes=poll.duration_minutes, allow_maybe=poll.allow_maybe,
                 hidden=poll.hidden, single_choice=poll.single_choice, max_per_option=poll.max_per_option,
                 require_email=poll.require_email, notify_votes=poll.notify_votes, public_token=new_link_token())
    db.add(clone)
    pl.set_options(db, clone, [{"starts_at": o.starts_at, "ends_at": o.ends_at, "all_day": o.all_day,
                                "note": o.note} for o in poll.options])
    db.commit()
    flash(request, "Kopie angelegt (ohne Teilnehmende). Passen Sie die Termine an.")
    return redirect(f"/polls/{clone.id}/edit")


@app.post("/polls/{poll_id}/delete", dependencies=[Depends(check_csrf)])
def poll_delete(request: Request, poll_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, level = _poll(db, poll_id, user, sh.EDIT)
    db.delete(poll)
    db.commit()
    flash(request, f"Terminumfrage „{poll.title}“ gelöscht.")
    return redirect("/polls" if user.can("polls") else home_for(user))


@app.post("/polls/{poll_id}/shares", dependencies=[Depends(check_csrf)])
async def poll_share_add(request: Request, poll_id: int, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Im Portal für Personen oder Gruppen freigeben (nur Besitzer:in bzw. Admin)."""
    poll, _ = _poll(db, poll_id, user, sh.OWNER)
    added, level = sh.add(db, "poll", poll, await request.form())
    db.commit()
    flash(request, f"Freigabe für {added} Eintrag/Einträge gespeichert: {sh.LEVELS['poll'][level][0]}." if added else
          "Bitte Personen oder Gruppen auswählen.", "ok" if added else "error")
    return redirect(f"/polls/{poll.id}#freigaben")


@app.post("/polls/{poll_id}/shares/{share_id}", dependencies=[Depends(check_csrf)])
def poll_share_update(request: Request, poll_id: int, share_id: int, action: str = Form("save"), level: int = Form(1),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    poll, _ = _poll(db, poll_id, user, sh.OWNER)
    message = sh.update(db, "poll", poll, share_id, action, level)
    if message is None:
        raise HTTPException(404)
    db.commit()
    flash(request, message)
    return redirect(f"/polls/{poll.id}#freigaben")


# --- Abstimmen (öffentlich) ----------------------------------------------------------------

def _vote_page(request: Request, db: Session, poll: Poll, participant: PollParticipant | None, action: str,
               error: str = "", status: int = 200):
    counts = pl.tally(poll)
    others = [p for p in poll.participants if p.answered_at and (participant is None or p.id != participant.id)]
    member = session_user(request, db)
    page = render(request, "poll_vote.html", None, poll=poll, participant=participant, action=action,
                  others=[] if poll.hidden else others, counts=counts, best=pl.best(poll, counts),
                  parts=pl.option_parts, answers=pl.ANSWERS, is_open=pl.is_open(poll),
                  full=pl.full_options(poll, participant), error=error, member=member,
                  answered_count=sum(1 for p in poll.participants if p.answered_at))
    page.status_code = status
    return page


def _closed_page(request: Request, poll: Poll | None):
    page = render(request, "poll_vote.html", None, poll=poll, missing=True)
    page.status_code = 404
    return page


def _poll_by_token(db: Session, token: str) -> Poll | None:
    return db.scalar(select(Poll).where(Poll.public_token == token)) if len(token) > 10 else None


def _participant_by_token(db: Session, token: str) -> PollParticipant | None:
    return db.scalar(select(PollParticipant).where(PollParticipant.edit_token == token)) if len(token) > 10 else None


@app.get("/t/p/{token}")
def poll_personal(request: Request, token: str, db: Session = Depends(get_db)):
    p = _participant_by_token(db, token)
    if p is None:
        return _closed_page(request, None)
    return _vote_page(request, db, p.poll, p, f"/t/p/{token}")


@app.get("/t/{token}")
def poll_public(request: Request, token: str, db: Session = Depends(get_db)):
    poll = _poll_by_token(db, token)
    if poll is None:
        return _closed_page(request, None)
    # Wer schon abgestimmt hat, bekommt seine Antwort wieder (Cookie mit dem persönlichen Schlüssel)
    own = _participant_by_token(db, request.cookies.get(COOKIE + str(poll.id), ""))
    if own is not None and own.poll_id == poll.id:
        return _vote_page(request, db, poll, own, f"/t/p/{own.edit_token}")
    return _vote_page(request, db, poll, None, f"/t/{token}")


async def _save_vote(request: Request, db: Session, poll: Poll, p: PollParticipant | None, action: str):
    rate_limit(request, "poll-vote", limit=40)
    if not pl.is_open(poll):
        return _vote_page(request, db, poll, p, action, "Die Abstimmung ist beendet.", 409)
    data = await request.form()
    if data.get("website"):  # Honigtopf gegen Spam-Bots
        return redirect(action)
    name = pl.clean_name(str(data.get("name", "")))
    email = str(data.get("email", "")).strip().lower()[:255]
    if not name:
        return _vote_page(request, db, poll, p, action, "Bitte geben Sie Ihren Namen an.", 422)
    if email and not planning.EMAIL_RE.match(email):
        return _vote_page(request, db, poll, p, action, "Die E-Mail-Adresse ist ungültig.", 422)
    if poll.require_email and not email and not (p and p.email):
        return _vote_page(request, db, poll, p, action, "Bitte geben Sie Ihre E-Mail-Adresse an.", 422)
    answers, error = pl.read_answers(poll, data, p)
    if error:
        return _vote_page(request, db, poll, p, action, error, 422)
    changed = p is not None and p.answered_at is not None
    if p is None:
        member = session_user(request, db)
        p = PollParticipant(edit_token=new_link_token(), user_id=member.id if member else None)
        poll.participants.append(p)
    p.name = name
    if email or not p.email:
        p.email = email
    p.answers_json = json.dumps(answers)
    p.comment = str(data.get("comment", "")).replace("\r\n", "\n").strip()[:1000]
    p.answered_at = utcnow()
    db.flush()
    pl.notify_vote(db, poll, p, changed)
    db.commit()
    worker.wake()
    flash(request, "Danke! Ihre Antwort ist gespeichert. Über diesen Link können Sie sie jederzeit ändern: "
                   + pl.personal_link(p))
    response = redirect(f"/t/p/{p.edit_token}")
    response.set_cookie(COOKIE + str(poll.id), p.edit_token, max_age=180 * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return response


@app.post("/t/p/{token}", dependencies=[Depends(check_csrf)])
async def poll_personal_save(request: Request, token: str, db: Session = Depends(get_db)):
    p = _participant_by_token(db, token)
    if p is None:
        return _closed_page(request, None)
    return await _save_vote(request, db, p.poll, p, f"/t/p/{token}")


@app.post("/t/{token}", dependencies=[Depends(check_csrf)])
async def poll_public_save(request: Request, token: str, db: Session = Depends(get_db)):
    poll = _poll_by_token(db, token)
    if poll is None:
        return _closed_page(request, None)
    return await _save_vote(request, db, poll, None, f"/t/{token}")
