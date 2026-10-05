"""Seiten der Abstimmungen: anlegen, Wählerverzeichnis, Codes, Live-Modus, Auswertung und öffentliches Abstimmen."""

import json

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import shares as sh, shortlinks as sl, votes as vt
from .db import Group, User, Vote, VoteBallot, VoteVoter, to_local, utcnow
from .main import (
    app, check_csrf, current_user, enabled_modules, flash, get_db, rate_limit, redirect, render, require, session_user,
)
from .planning import parse_emails
from .security import new_link_token

vote_user = require("votes")
SESSION_KEY = "voted_tokens"


def _module_on() -> None:
    if "polls" not in enabled_modules():
        raise HTTPException(404, "Umfragen und Abstimmungen sind auf diesem Server nicht eingeschaltet.")


def _vote(db: Session, vote_id: int, user: User, need: int) -> tuple[Vote, int]:
    _module_on()
    vote = db.get(Vote, vote_id)
    level = sh.access_level(db, "vote", vote, user)
    if level == 0:
        raise HTTPException(404, "Abstimmung nicht gefunden.")
    if level < need:
        raise HTTPException(403, "Für diese Aktion reicht Ihre Freigabe für die Abstimmung nicht aus.")
    return vote, level


def _apply(vote: Vote, data) -> None:
    vote.title = " ".join(str(data.get("title", "")).split())[:255] or vote.title or "Abstimmung"
    vote.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:5000]
    if vote.status == "draft" or not vote.voters:
        vote.secrecy = data.get("secrecy") if data.get("secrecy") in vt.SECRECY else "secret"
    modes = [a for a in data.getlist("access") if a in vt.ACCESS] or ["invite"]
    vote.access = ",".join(sorted(set(modes)))
    vote.results = data.get("results") if data.get("results") in vt.RESULTS else "after_end"
    vote.allow_change = data.get("allow_change") == "1" and vote.secrecy == "open"
    vote.ends_at = vt.parse_local(str(data.get("ends_at", "")))


def _editor_ctx(vote: Vote | None) -> dict:
    return {"vote": vote, "questions_data": vt.editor_data(vote), "kinds": vt.KINDS, "secrecy": vt.SECRECY,
            "access": vt.ACCESS, "results_modes": vt.RESULTS,
            "ends": to_local(vote.ends_at).strftime("%Y-%m-%dT%H:%M") if vote and vote.ends_at else ""}


# --- Verwaltung ------------------------------------------------------------------------------

@app.get("/votes")
def votes_list(request: Request, all: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    show_all = user.is_admin and all == "1"
    shared = [] if show_all else sh.shared_with(db, "vote", user)
    if not user.can("votes") and not shared:
        raise HTTPException(403, "Für „Abstimmungen“ fehlt die Berechtigung. Bitte wenden Sie sich an die Verwaltung des Portals.")
    q = select(Vote).order_by(Vote.updated_at.desc())
    if not show_all:
        q = q.where(Vote.owner_id == user.id)
    items = db.scalars(q).all() if user.can("votes") or show_all else []
    counts = dict(db.execute(select(VoteBallot.vote_id, func.count(VoteBallot.id)).group_by(VoteBallot.vote_id)).all())
    return render(request, "votes.html", user, votes=items, shared=shared, counts=counts, show_all=show_all,
                  statuses=vt.STATUSES, secrecy=vt.SECRECY, levels=sh.LEVELS["vote"], is_open=vt.is_open)


@app.get("/votes/new")
def vote_new(request: Request, user: User = Depends(vote_user)):
    _module_on()
    return render(request, "vote_edit.html", user, **_editor_ctx(None))


@app.post("/votes/new", dependencies=[Depends(check_csrf)])
async def vote_create(request: Request, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    _module_on()
    data = await request.form()
    vote = Vote(owner_id=user.id, title="", public_token=new_link_token())
    _apply(vote, data)
    db.add(vote)
    try:
        raw = json.loads(str(data.get("questions_json", "[]")))
    except ValueError:
        raw = []
    err = vt.set_questions(db, vote, raw)
    if err:
        db.rollback()
        flash(request, err, "error")
        return render(request, "vote_edit.html", user, **_editor_ctx(None), draft=data, draft_questions=raw)
    db.commit()
    flash(request, "Abstimmung angelegt. Jetzt Wahlberechtigte festlegen und starten.")
    return redirect(f"/votes/{vote.id}")


@app.get("/votes/{vote_id:int}")
def vote_detail(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, level = _vote(db, vote_id, user, sh.VIEW)
    ballots = vt.ballots(db, vote)
    voters = {v.id: v for v in vote.voters}
    named = []
    if vote.secrecy == "open":
        for b in ballots:
            v, a = voters.get(b.voter_id), json.loads(b.answers_json or "{}")
            named.append((v.name if v else "?", [vt.display(q, a.get(str(q.id))) for q in vote.questions]))
    dms_areas = []
    if "dms" in enabled_modules():
        from . import dms
        lv = dms.levels(db, user)
        dms_areas = [(a, d) for a, d in dms.tree(db) if lv.get(a.id, 0) >= dms.WRITE]
    return render(request, "vote.html", user, vote=vote, level=level, results=vt.frozen(vote) or vt.tally(db, vote),
                  turnout=vt.turnout(vote, len(ballots)), statuses=vt.STATUSES, secrecy=vt.SECRECY, access=vt.ACCESS,
                  results_modes=vt.RESULTS, kinds=vt.KINDS, modes=vt.access_modes(vote), public_link=vt.public_link(vote),
                  personal_link=vt.personal_link, format_code=vt.format_code, named=named, options=vt.options,
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(), share_levels=sh.LEVELS["vote"],
                  codes=[v for v in vote.voters if v.source == "code"], is_open=vt.is_open(vote), dms_areas=dms_areas)


@app.get("/votes/{vote_id:int}/edit")
def vote_edit(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.EDIT)
    return render(request, "vote_edit.html", user, **_editor_ctx(vote),
                  locked=db.scalar(select(VoteBallot.id).where(VoteBallot.vote_id == vote.id).limit(1)) is not None)


@app.post("/votes/{vote_id:int}/edit", dependencies=[Depends(check_csrf)])
async def vote_save(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.EDIT)
    data = await request.form()
    _apply(vote, data)
    if data.get("questions_json") is not None:
        try:
            raw = json.loads(str(data.get("questions_json", "[]")))
        except ValueError:
            raw = []
        if db.scalar(select(VoteBallot.id).where(VoteBallot.vote_id == vote.id).limit(1)) is None:
            err = vt.set_questions(db, vote, raw)
            if err:
                db.rollback()
                flash(request, err, "error")
                return redirect(f"/votes/{vote.id}/edit")
    db.commit()
    flash(request, "Gespeichert.")
    return redirect(f"/votes/{vote.id}")


@app.post("/votes/{vote_id:int}/state", dependencies=[Depends(check_csrf)])
def vote_state(request: Request, vote_id: int, action: str = Form(...), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    vote, level = _vote(db, vote_id, user, sh.INVITE)
    if action == "start" and vote.status != "closed":
        if not vote.questions:
            flash(request, "Bitte zuerst Fragen anlegen.", "error")
            return redirect(f"/votes/{vote.id}")
        if vote.ends_at and vote.ends_at < utcnow():
            flash(request, "Das Ende liegt in der Vergangenheit – bitte unter „Bearbeiten“ ändern.", "error")
            return redirect(f"/votes/{vote.id}")
        vote.status = "open"
        vote.opened_at = vote.opened_at or utcnow()
        n = vt.send_pending_invites(db, vote, user)
        flash(request, "Abstimmung läuft." + (f" {n} Einladung(en) verschickt." if n else ""))
    elif action == "pause" and vote.status == "open":
        vote.status = "draft"
        flash(request, "Abstimmung angehalten – bis zum erneuten Start kann niemand abstimmen.")
    elif action == "close" and vote.status != "closed":
        if level < sh.EDIT and vote.results != "live":
            raise HTTPException(403)
        vt.close(db, vote)
        flash(request, "Abstimmung beendet, Ergebnis festgeschrieben.")
    db.commit()
    nxt = request.query_params.get("next", "")
    return redirect(nxt if nxt in (f"/votes/{vote.id}/live",) else f"/votes/{vote.id}")


@app.post("/votes/{vote_id:int}/invite", dependencies=[Depends(check_csrf)])
async def vote_invite(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    data = await request.form()
    emails, invalid = parse_emails(str(data.get("emails", "")))
    ids = lambda key: [int(x) for x in data.getlist(key) if str(x).isdigit()]  # noqa: E731
    added, skipped = vt.invite(db, vote, user, ids("users"), ids("groups"), emails)
    if "invite" not in vt.access_modes(vote):
        vote.access = ",".join(sorted(vt.access_modes(vote) | {"invite"}))
    db.commit()
    msg = f"{added} Wahlberechtigte eingetragen" + (" und eingeladen." if vote.status == "open" else " – die Einladungen gehen beim Start raus.")
    if skipped:
        msg += f" {skipped} waren schon eingetragen."
    if invalid:
        msg += f" Ungültig: {', '.join(invalid[:5])}"
    flash(request, msg)
    return redirect(f"/votes/{vote.id}#waehler")


@app.post("/votes/{vote_id:int}/remind", dependencies=[Depends(check_csrf)])
def vote_remind(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    n = vt.remind(db, vote, user) if vt.is_open(vote) else 0
    db.commit()
    flash(request, f"{n} Erinnerung(en) verschickt." if n else "Niemand zu erinnern (oder Abstimmung läuft nicht).")
    return redirect(f"/votes/{vote.id}#waehler")


@app.post("/votes/{vote_id:int}/voters/{voter_id:int}/delete", dependencies=[Depends(check_csrf)])
def vote_voter_delete(request: Request, vote_id: int, voter_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    voter = db.get(VoteVoter, voter_id)
    if voter is None or voter.vote_id != vote.id:
        raise HTTPException(404)
    if voter.voted:
        flash(request, "Wer schon abgestimmt hat, bleibt im Wählerverzeichnis.", "error")
    else:
        db.delete(voter)
        db.commit()
        flash(request, "Aus dem Wählerverzeichnis entfernt – der Link gilt nicht mehr.")
    return redirect(f"/votes/{vote.id}#waehler")


@app.post("/votes/{vote_id:int}/codes", dependencies=[Depends(check_csrf)])
def vote_codes(request: Request, vote_id: int, count: int = Form(10), label: str = Form(""),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    n = vt.make_codes(db, vote, count, " ".join(label.split()))
    if "codes" not in vt.access_modes(vote):
        vote.access = ",".join(sorted(vt.access_modes(vote) | {"codes"}))
    db.commit()
    flash(request, f"{n} Zugangscodes erzeugt.")
    return redirect(f"/votes/{vote.id}#codes")


@app.get("/votes/{vote_id:int}/codes/print")
def vote_codes_print(request: Request, vote_id: int, only_new: str = "", user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    codes = [v for v in vote.voters if v.source == "code" and not (only_new and v.voted)]
    return render(request, "vote_codes.html", user, vote=vote, codes=codes, format_code=vt.format_code,
                  public_link=vt.public_link(vote), personal_link=vt.personal_link)


@app.get("/votes/{vote_id:int}/qr/{token}.svg")
def vote_code_qr(vote_id: int, token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.INVITE)
    if token == "public":
        target = vt.public_link(vote)
    else:
        voter = db.scalar(select(VoteVoter).where(VoteVoter.vote_id == vote.id, VoteVoter.token == token))
        if voter is None:
            raise HTTPException(404)
        target = vt.personal_link(voter)
    data, media = sl.qr_image(target, sl.qr_options("svg", 6))
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=300"})


@app.get("/votes/{vote_id:int}/live")
def vote_live(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, level = _vote(db, vote_id, user, sh.INVITE)
    return render(request, "vote_live.html", user, vote=vote, level=level, public_link=vt.public_link(vote),
                  statuses=vt.STATUSES, modes=vt.access_modes(vote))


def _results_json(db, vote: Vote) -> dict:
    ballots = vt.ballots(db, vote)
    t = vt.turnout(vote, len(ballots))
    if vote.secrecy == "anonymous":
        t = {"ballots": t["ballots"]}
    return {"status": vote.status, "turnout": t, "results": vt.frozen(vote) or vt.tally(db, vote)}


@app.get("/votes/{vote_id:int}/results.json")
def vote_results_json(vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.VIEW)
    return JSONResponse(_results_json(db, vote), headers={"Cache-Control": "no-store"})


@app.get("/votes/{vote_id:int}/export.csv")
def vote_export(vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.VIEW)
    if vote.status != "closed" and vote.results != "live":
        raise HTTPException(403, "Die Stimmzettel lassen sich erst nach dem Ende exportieren.")
    return Response(vt.to_csv(db, vote), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="abstimmung-{vote.id}.csv"'})


@app.get("/votes/{vote_id:int}/protocol.pdf")
def vote_protocol(vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.VIEW)
    return Response(vt.protocol_pdf(db, vote), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="ergebnisprotokoll-{vote.id}.pdf"'})


@app.post("/votes/{vote_id:int}/dms", dependencies=[Depends(check_csrf)])
async def vote_to_dms(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from . import dms
    from .db import DmsArea, DmsRecord
    vote, _ = _vote(db, vote_id, user, sh.VIEW)
    data = await request.form()
    area = db.get(DmsArea, int(data["area_id"])) if str(data.get("area_id", "")).isdigit() else None
    if area is None or dms.levels(db, user).get(area.id, 0) < dms.WRITE:
        flash(request, "Bitte einen Ablagebereich wählen, in dem Sie ablegen dürfen.", "error")
        return redirect(f"/votes/{vote.id}")
    record = DmsRecord(area_id=area.id, kind="manuell", title=f"Ergebnisprotokoll: {vote.title}"[:300], ref_no="",
                       note=f"Abstimmung #{vote.id}, {vt.SECRECY[vote.secrecy][0]}", created_by=user.name,
                       received_at=vote.closed_at or utcnow(), closed_at=utcnow())
    db.add(record)
    db.flush()
    dms._store(record, f"Ergebnisprotokoll {vote.title[:80]}.pdf", vt.protocol_pdf(db, vote), "upload", user.name,
               "aus der Abstimmung", "application/pdf")
    by_id = {a.id: a for a in dms.areas(db)}
    record.retention_until = dms.retention_date(record.closed_at, dms.retention_years(area, by_id))
    record.text = f"{record.title} {record.note}".lower()
    dms.log(db, user, "abgelegt", f"Ergebnisprotokoll „{vote.title}“ in {area.name}")
    db.commit()
    flash(request, "Ergebnisprotokoll in der Ablage abgelegt.")
    return redirect(f"/dms/r/{record.id}")


@app.post("/votes/{vote_id:int}/copy", dependencies=[Depends(check_csrf)])
def vote_copy(request: Request, vote_id: int, user: User = Depends(vote_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.VIEW)
    clone = Vote(owner_id=user.id, title=(vote.title + " (Kopie)")[:255], description=vote.description,
                 secrecy=vote.secrecy, access=vote.access, results=vote.results, allow_change=vote.allow_change,
                 public_token=new_link_token())
    db.add(clone)
    vt.set_questions(db, clone, [{**q, "id": None} for q in vt.editor_data(vote)])
    db.commit()
    flash(request, "Kopie angelegt (ohne Wählerverzeichnis und Stimmen).")
    return redirect(f"/votes/{clone.id}/edit")


@app.post("/votes/{vote_id:int}/delete", dependencies=[Depends(check_csrf)])
def vote_delete(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.EDIT)
    db.query(VoteBallot).filter(VoteBallot.vote_id == vote.id).delete()
    db.delete(vote)
    db.commit()
    flash(request, "Abstimmung gelöscht.")
    return redirect("/votes")


@app.post("/votes/{vote_id:int}/shares", dependencies=[Depends(check_csrf)])
async def vote_share_add(request: Request, vote_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.OWNER)
    added, level = sh.add(db, "vote", vote, await request.form())
    db.commit()
    flash(request, f"{added} Freigabe(n) mit Stufe „{sh.LEVELS['vote'][level][0]}“." if added else "Bitte Personen oder Gruppen wählen.")
    return redirect(f"/votes/{vote.id}#teilen")


@app.post("/votes/{vote_id:int}/shares/{share_id:int}", dependencies=[Depends(check_csrf)])
def vote_share_update(request: Request, vote_id: int, share_id: int, action: str = Form("save"), level: int = Form(1),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    vote, _ = _vote(db, vote_id, user, sh.OWNER)
    msg = sh.update(db, "vote", vote, share_id, action, level)
    db.commit()
    flash(request, msg or "Freigabe nicht gefunden.")
    return redirect(f"/votes/{vote.id}#teilen")


# --- Öffentlich: abstimmen --------------------------------------------------------------------

def _public_vote(db, token: str) -> Vote:
    _module_on()
    vote = db.scalar(select(Vote).where(Vote.public_token == token)) if token else None
    if vote is None or vote.status == "draft" and not vote.opened_at:
        raise HTTPException(404, "Diese Abstimmung gibt es nicht oder sie hat noch nicht begonnen.")
    return vote


def _voter(db, token: str) -> VoteVoter:
    _module_on()
    voter = db.scalar(select(VoteVoter).where(VoteVoter.token == token)) if token else None
    if voter is None:
        raise HTTPException(404, "Dieser Link ist nicht (mehr) gültig.")
    return voter


def _remember(request: Request, token: str) -> None:
    seen = [t for t in request.session.get(SESSION_KEY, []) if t != token][-20:]
    request.session[SESSION_KEY] = seen + [token]


def _session_voter(request: Request, db, vote: Vote) -> VoteVoter | None:
    tokens = request.session.get(SESSION_KEY, [])
    if tokens:
        voter = db.scalar(select(VoteVoter).where(VoteVoter.vote_id == vote.id, VoteVoter.token.in_(tokens)))
        if voter:
            return voter
    user = session_user(request, db)
    if user is not None:
        return db.scalar(select(VoteVoter).where(VoteVoter.vote_id == vote.id, VoteVoter.user_id == user.id))
    return None


def _ballot_page(request: Request, db, vote: Vote, voter: VoteVoter | None, **extra):
    show = vt.results_visible_to_voter(vote, voter)
    results = (vt.frozen(vote) or vt.tally(db, vote)) if show else None
    return render(request, "vote_ballot.html", session_user(request, db), vote=vote, voter=voter, results=results,
                  options=vt.options, kinds=vt.KINDS, secrecy=vt.SECRECY, modes=vt.access_modes(vote),
                  is_open=vt.is_open(vote), can_vote=bool(voter and vt.can_vote(vote, voter)),
                  turnout=vt.turnout(vote, len(vt.ballots(db, vote))) if show and vote.secrecy != "anonymous" else None,
                  previous=json.loads(vt.existing_ballot(db, vote, voter).answers_json) if voter and vote.allow_change
                  and vt.existing_ballot(db, vote, voter) else {}, **extra)


@app.get("/v/{token}")
def vote_public(request: Request, token: str, db: Session = Depends(get_db)):
    vote = _public_vote(db, token)
    voter = _session_voter(request, db, vote)
    if voter is not None and vt.can_vote(vote, voter):
        return redirect(f"/v/p/{voter.token}")
    return _ballot_page(request, db, vote, voter, public=True, notice=request.session.pop("vote_notice", ""))


@app.post("/v/{token}/signup", dependencies=[Depends(check_csrf)])
def vote_signup(request: Request, token: str, name: str = Form(""), email: str = Form(""),
                db: Session = Depends(get_db)):
    vote = _public_vote(db, token)
    if "public" not in vt.access_modes(vote) or not vt.is_open(vote):
        raise HTTPException(403, "Eine Anmeldung ist für diese Abstimmung nicht möglich.")
    rate_limit(request, "vote-signup", limit=10, window=600)
    rate_limit(request, "vote-signup-mail", limit=3, window=3600, key=email.strip().lower())
    voter = vt.signup(db, vote, name, email)
    db.commit()
    request.session["vote_notice"] = ("Bitte prüfen Sie Ihr Postfach: Wir haben Ihnen Ihren persönlichen Link zum Abstimmen "
                                      "geschickt. Erst damit ist Ihre E-Mail-Adresse bestätigt.") if voter else \
        "Bitte eine gültige E-Mail-Adresse angeben."
    return redirect(f"/v/{token}")


@app.post("/v/{token}/code", dependencies=[Depends(check_csrf)])
def vote_code(request: Request, token: str, code: str = Form(""), db: Session = Depends(get_db)):
    vote = _public_vote(db, token)
    rate_limit(request, "vote-code", limit=15, window=600)
    voter = vt.voter_by_code(db, vote, code) if "codes" in vt.access_modes(vote) else None
    if voter is None:
        request.session["vote_notice"] = "Dieser Code ist nicht gültig. Bitte genau so eingeben, wie er auf dem Zettel steht."
        return redirect(f"/v/{token}")
    return redirect(f"/v/p/{voter.token}")


@app.get("/v/p/{token}")
def vote_personal(request: Request, token: str, db: Session = Depends(get_db)):
    voter = _voter(db, token)
    vote = voter.vote
    if not voter.confirmed:
        voter.confirmed = True       # Klick auf den Link aus der Mail = Adresse bestätigt
        db.commit()
    _remember(request, token)
    return _ballot_page(request, db, vote, voter, receipt=request.session.pop("vote_receipt", ""))


@app.post("/v/p/{token}", dependencies=[Depends(check_csrf)])
async def vote_cast(request: Request, token: str, db: Session = Depends(get_db)):
    voter = _voter(db, token)
    vote = voter.vote
    if not vt.can_vote(vote, voter):
        flash(request, "Abstimmen ist nicht (mehr) möglich – die Abstimmung ist beendet oder Ihre Stimme ist schon abgegeben.", "error")
        return redirect(f"/v/p/{token}")
    data = await request.form()
    answers, errors = vt.read_ballot(vote, data)
    if errors:
        for e in errors:
            flash(request, e, "error")
        return _ballot_page(request, db, vote, voter, draft=data)
    receipt = vt.cast(db, vote, voter, answers)
    db.commit()
    request.session["vote_receipt"] = receipt
    _remember(request, token)
    return redirect(f"/v/p/{token}#danke")


@app.get("/v/{token}/results.json")
def vote_public_results(request: Request, token: str, db: Session = Depends(get_db)):
    vote = _public_vote(db, token)
    if not vt.results_visible_to_voter(vote, _session_voter(request, db, vote)):
        raise HTTPException(403, "Das Ergebnis ist noch nicht sichtbar.")
    return JSONResponse(_results_json(db, vote), headers={"Cache-Control": "no-store"})


@app.get("/v/{token}/receipt")
def vote_receipt(request: Request, token: str, code: str = "", db: Session = Depends(get_db)):
    vote = _public_vote(db, token)
    rate_limit(request, "vote-receipt", limit=30, window=600)
    ok = bool(code) and db.scalar(select(VoteBallot.id).where(VoteBallot.vote_id == vote.id,
                                                              VoteBallot.receipt == code.strip().upper())) is not None
    return JSONResponse({"ok": ok})
