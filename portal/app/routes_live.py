"""Live-Umfragen: anlegen, Fragen pflegen, moderieren, Präsentationsmodus (Beamer) und Teilnahme per QR-Code ohne
Anmeldung (/l/<token>). Logik in live.py."""

import json

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from . import links, live as lv, shortlinks as sl
from .config import settings
from .db import LivePoll, LiveQuestion, User
from .main import app, check_csrf, flash, get_db, rate_limit, redirect, render, require, session_user
from .routes_votes import _module_on
from .security import new_link_token

vote_user = require("votes")


def _poll(db: Session, poll_id: int, user: User) -> LivePoll:
    _module_on()
    poll = db.get(LivePoll, poll_id)
    if poll is None or not (user.is_admin or poll.owner_id == user.id):
        raise HTTPException(404, "Live-Umfrage nicht gefunden.")
    return poll


def join_url(poll: LivePoll) -> str:
    return f"{links.base('polls')}/l/{poll.public_token}"


# --- Verwaltung -------------------------------------------------------------------------------------

@app.post("/votes/live/new", dependencies=[Depends(check_csrf)])
async def live_create(request: Request, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    poll = LivePoll(owner_id=user.id, title=" ".join(str(data.get("title", "")).split())[:255] or "Live-Umfrage",
                    public_token=new_link_token(),
                    pacing=data.get("pacing") if data.get("pacing") in lv.PACING else "moderated")
    db.add(poll)
    db.commit()
    flash(request, "Live-Umfrage angelegt – jetzt Fragen hinzufügen.")
    return redirect(f"/votes/live/{poll.id}")


@app.get("/votes/live/{poll_id:int}")
def live_edit(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    return render(request, "live_edit.html", user, poll=poll, kinds=lv.KINDS, charts=lv.CHARTS, pacing=lv.PACING,
                  show_results=lv.SHOW_RESULTS, statuses=lv.STATUSES, opts=lv.opts, settings_of=lv.settings,
                  join=join_url(poll), counts={q.id: lv.tally(db, q)["total"] for q in poll.questions},
                  words={q.id: lv.raw_words(db, q) for q in poll.questions if q.kind == "words"},
                  entries={q.id: lv.entry_payload(db, q, None, True)["entries"] for q in poll.questions
                           if q.kind in lv.ENTRY_KINDS})


@app.post("/votes/live/{poll_id:int}/settings", dependencies=[Depends(check_csrf)])
async def live_settings(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    data = await request.form()
    poll.title = " ".join(str(data.get("title", "")).split())[:255] or poll.title
    poll.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:2000]
    poll.pacing = data.get("pacing") if data.get("pacing") in lv.PACING else poll.pacing
    db.commit()
    flash(request, "Gespeichert.")
    return redirect(f"/votes/live/{poll.id}")


@app.post("/votes/live/{poll_id:int}/fragen", dependencies=[Depends(check_csrf)])
async def live_question_save(request: Request, poll_id: int, user: User = Depends(vote_user),
                             db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    data = await request.form()
    qid = str(data.get("question_id", ""))
    q = next((x for x in poll.questions if str(x.id) == qid), None) if qid else None
    if qid and q is None:
        raise HTTPException(404)
    if q is None:
        if len(poll.questions) >= lv.MAX_QUESTIONS:
            flash(request, f"Höchstens {lv.MAX_QUESTIONS} Fragen je Umfrage.", "error")
            return redirect(f"/votes/live/{poll.id}")
        q = LiveQuestion(poll_id=poll.id, position=len(poll.questions), title="", kind=str(data.get("kind", "single")))
    error = lv.apply_question(q, data)
    if error:
        db.rollback()
        flash(request, error, "error")
        return redirect(f"/votes/live/{poll.id}#neu")
    if q.id is None:
        poll.questions.append(q)
    db.commit()
    if poll.current_id is None:
        poll.current_id = q.id
        db.commit()
    flash(request, "Frage gespeichert.")
    return redirect(f"/votes/live/{poll.id}#frage-{q.id}")


def _question(poll: LivePoll, qid: int) -> LiveQuestion:
    q = next((x for x in poll.questions if x.id == qid), None)
    if q is None:
        raise HTTPException(404)
    return q


@app.post("/votes/live/{poll_id:int}/fragen/{qid:int}/woerter", dependencies=[Depends(check_csrf)])
async def live_words(request: Request, poll_id: int, qid: int, user: User = Depends(vote_user),
                     db: Session = Depends(get_db)):
    """Wortwolke moderieren: Begriff ausblenden, wieder zeigen, zusammenfassen."""
    poll = _poll(db, poll_id, user)
    q = _question(poll, qid)
    if q.kind != "words":
        raise HTTPException(400)
    data = await request.form()
    error = lv.moderate(q, str(data.get("action", "")), str(data.get("key", "")), str(data.get("into", "")))
    if error:
        flash(request, error, "error")
    else:
        db.commit()
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"ok": not error, "error": error, "words": lv.raw_words(db, q)})
    return redirect(f"/votes/live/{poll.id}#frage-{q.id}")


@app.post("/votes/live/{poll_id:int}/fragen/{qid:int}/{action}", dependencies=[Depends(check_csrf)])
async def live_question_action(request: Request, poll_id: int, qid: int, action: str, user: User = Depends(vote_user),
                               db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    q = _question(poll, qid)
    data = await request.form()
    if action in ("up", "down"):
        qs = list(poll.questions)
        i = qs.index(q)
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(qs):
            qs[i], qs[j] = qs[j], qs[i]
            for n, x in enumerate(qs):
                x.position = n
    elif action == "delete":
        if poll.current_id == q.id:
            poll.current_id = None
        db.delete(q)
    elif action == "release":
        q.released = not q.released
    elif action == "lock":
        q.locked = not q.locked
    elif action == "chart" and data.get("chart") in lv.KINDS[q.kind][2]:
        q.chart = data.get("chart")
    elif action == "show":
        poll.current_id = q.id
    elif action == "reset":
        from sqlalchemy import delete
        from .db import LiveAnswer
        db.execute(delete(LiveAnswer).where(LiveAnswer.question_id == q.id))
    else:
        raise HTTPException(400)
    db.commit()
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(lv.state(db, poll, staff=True))
    return redirect(f"/votes/live/{poll.id}#frage-{q.id}" if action != "delete" else f"/votes/live/{poll.id}")


@app.get("/votes/live/{poll_id:int}/fragen/{qid:int}/export.csv")
def live_export_csv(poll_id: int, qid: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    q = _question(poll, qid)
    return Response(lv.to_csv(db, q), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="live-frage-{q.id}.csv"'})


@app.get("/votes/live/{poll_id:int}/fragen/{qid:int}/wolke.png")
def live_cloud_png(poll_id: int, qid: int, dunkel: str = "", user: User = Depends(vote_user),
                   db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    q = _question(poll, qid)
    if q.kind != "words":
        raise HTTPException(400)
    return Response(lv.cloud_png(db, q, dark=dunkel == "1"), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="wortwolke-{q.id}.png"'})


@app.post("/votes/live/{poll_id:int}/status", dependencies=[Depends(check_csrf)])
async def live_status(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    action = (await request.form()).get("action")
    if action == "open":
        if not poll.questions:
            flash(request, "Bitte zuerst mindestens eine Frage anlegen.", "error")
            return redirect(f"/votes/live/{poll.id}")
        poll.status = "open"
        if poll.current_id is None:
            poll.current_id = poll.questions[0].id
    elif action == "close":
        poll.status = "closed"
    db.commit()
    flash(request, {"open": "Die Umfrage läuft – Teilnehmende können jetzt per QR-Code antworten.",
                    "close": "Die Umfrage ist beendet."}.get(action, "Gespeichert."))
    return redirect(f"/votes/live/{poll.id}")


@app.post("/votes/live/{poll_id:int}/schritt", dependencies=[Depends(check_csrf)])
async def live_step(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    """Präsentation: nächste/vorige Frage (moderierter Ablauf)."""
    poll = _poll(db, poll_id, user)
    data = await request.form()
    lv.step(poll, 1 if data.get("dir") == "next" else -1)
    db.commit()
    return JSONResponse(lv.state(db, poll, staff=True))


@app.get("/votes/live/{poll_id:int}/state.json")
def live_staff_state(poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    return JSONResponse(lv.state(db, poll, staff=True), headers={"Cache-Control": "no-store"})


@app.get("/votes/live/{poll_id:int}/praesentation")
def live_present(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    return render(request, "live_present.html", user, poll=poll, join=join_url(poll),
                  short=join_url(poll).split("://", 1)[-1], charts=lv.CHARTS, kinds=lv.KINDS)


@app.get("/votes/live/{poll_id:int}/qr.svg")
def live_qr(poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    data, media = sl.qr_image(join_url(poll), sl.qr_options("svg", 10, border=1))
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=300"})


@app.post("/votes/live/{poll_id:int}/loeschen", dependencies=[Depends(check_csrf)])
def live_delete(request: Request, poll_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    poll = _poll(db, poll_id, user)
    db.delete(poll)
    db.commit()
    flash(request, f"Live-Umfrage „{poll.title}“ gelöscht.")
    return redirect("/votes")


# --- Teilnahme (ohne Anmeldung) -------------------------------------------------------------------

def _public_poll(db: Session, token: str) -> LivePoll:
    _module_on()
    poll = db.query(LivePoll).filter(LivePoll.public_token == token).first() if len(token) > 10 else None
    if poll is None:
        raise HTTPException(404, "Diese Umfrage gibt es nicht (mehr).")
    return poll


def _device(request: Request) -> str:
    raw = request.cookies.get(lv.DEVICE_COOKIE, "")
    return raw if len(raw) == 32 and all(c in "0123456789abcdef" for c in raw) else ""


@app.get("/l/{token}")
def live_join(request: Request, token: str, db: Session = Depends(get_db)):
    poll = _public_poll(db, token)
    raw = _device(request) or lv.new_device()
    user = session_user(request, db)
    response = render(request, "live_join.html", user, poll=poll, device=raw, token=token)
    response.set_cookie(lv.DEVICE_COOKIE, raw, max_age=365 * 86400, httponly=True, samesite="lax",
                        secure=settings.secure_cookies, path="/l")
    if user is None and "jsm_session" not in request.cookies:
        request.session.clear()
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/l/{token}/state.json")
def live_join_state(request: Request, token: str, db: Session = Depends(get_db)):
    poll = _public_poll(db, token)
    raw = _device(request)
    return JSONResponse(lv.state(db, poll, lv.device_hash(raw) if raw else None), headers={"Cache-Control": "no-store"})


@app.post("/l/{token}/answer")
async def live_answer(request: Request, token: str, db: Session = Depends(get_db)):
    """Antwort speichern. Schutz gegen fremde Seiten: der Kopf X-Live-Device muss zur Gerätekennung im Cookie
    passen (die nur die eigene Seite kennt)."""
    rate_limit(request, "live-answer", limit=120, window=60)
    poll = _public_poll(db, token)
    raw = _device(request)
    if not raw or request.headers.get("x-live-device") != raw:
        raise HTTPException(403, "Bitte die Seite neu laden.")
    if poll.status != "open":
        return JSONResponse({"ok": False, "error": "Die Umfrage ist gerade nicht geöffnet."}, status_code=409)
    try:
        body = json.loads((await request.body())[:20000] or b"{}")
    except ValueError:
        body = {}
    q = next((x for x in poll.questions if str(x.id) == str(body.get("question"))), None)
    if q is None or (poll.pacing == "moderated" and q.id != poll.current_id):
        return JSONResponse({"ok": False, "error": "Diese Frage ist gerade nicht aktiv."}, status_code=409)
    if q.locked:
        return JSONResponse({"ok": False, "error": "Für diese Frage sind keine Antworten mehr möglich."}, status_code=409)
    value, error = lv.read_answer(q, body.get("value"))
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    if q.kind in lv.ENTRY_KINDS:
        _entry, error = lv.add_entry(db, poll, q, lv.device_hash(raw), value)
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=400)
    else:
        lv.save_answer(db, poll, q, lv.device_hash(raw), value)
    db.commit()
    return JSONResponse({"ok": True, **lv.state(db, poll, lv.device_hash(raw))})


@app.post("/l/{token}/upvote")
async def live_upvote(request: Request, token: str, db: Session = Depends(get_db)):
    """Q&A: Frage hochstimmen bzw. Stimme zurücknehmen (je Gerät einmal)."""
    rate_limit(request, "live-answer", limit=120, window=60)
    poll = _public_poll(db, token)
    raw = _device(request)
    if not raw or request.headers.get("x-live-device") != raw:
        raise HTTPException(403, "Bitte die Seite neu laden.")
    try:
        body = json.loads((await request.body())[:2000] or b"{}")
    except ValueError:
        body = {}
    q = next((x for x in poll.questions if str(x.id) == str(body.get("question"))), None)
    if q is None or poll.status != "open" or (poll.pacing == "moderated" and q.id != poll.current_id):
        return JSONResponse({"ok": False, "error": "Diese Frage ist gerade nicht aktiv."}, status_code=409)
    error = lv.upvote(db, q, int(body.get("answer") or 0), lv.device_hash(raw))
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    db.commit()
    return JSONResponse({"ok": True, **lv.state(db, poll, lv.device_hash(raw))})


@app.post("/votes/live/{poll_id:int}/beitraege/{aid:int}/{action}", dependencies=[Depends(check_csrf)])
def live_entry_action(request: Request, poll_id: int, aid: int, action: str, user: User = Depends(vote_user),
                      db: Session = Depends(get_db)):
    """Moderation von Pinnwand- und Q&A-Beiträgen: freigeben, ausblenden, beantwortet markieren."""
    from .db import LiveAnswer
    poll = _poll(db, poll_id, user)
    a = db.get(LiveAnswer, aid)
    if a is None or a.poll_id != poll.id:
        raise HTTPException(404)
    error = lv.moderate_entry(a, action)
    if error:
        raise HTTPException(400, error)
    db.commit()
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(lv.state(db, poll, staff=True))
    return redirect(f"/votes/live/{poll.id}#frage-{a.question_id}")
