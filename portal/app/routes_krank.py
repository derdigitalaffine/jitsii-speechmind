"""BlueOtter Krankmelder: öffentliche Meldewege (/krank, einbettbar unter /krank-embed), Statusseite,
„Meine Krankmeldungen“ und die Bearbeitung durch die Personalverwaltung (/krankmelder)."""

import json
import tempfile
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import krank, links, notify, shortlinks as sl
from .db import (
    DmsArea, Group, KrankAccess, KrankEmployer, KrankFeedback, KrankReport, KrankResponsible, Notification, User,
    get_settings, set_setting,
)
from .main import (
    app, check_csrf, current_user, enabled_modules, flash, get_db, rate_limit, redirect, render, session_user,
)
from .security import csrf_valid

PUBLIC, EMBED = "/krank", "/krank-embed"
PAGE = 50

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(["table", "strikethrough"])

DEFAULT_INSTRUCTIONS = """## So melden Sie sich krank

1. **Meldeweg wählen**
   - *Krankmeldung ohne AU*: nur für heute (Montag bis Freitag). Ab dem 4. Kalendertag brauchen Sie eine ärztliche Bescheinigung.
   - *eAU*: Sie sind gesetzlich versichert und waren beim Arzt. Die Praxis meldet die Arbeitsunfähigkeit elektronisch an Ihre Krankenkasse; die Personalverwaltung ruft sie dort ab. Übertragen Sie die Daten **genau wie auf Ihrem Ausdruck**: *arbeitsunfähig seit*, *voraussichtlich arbeitsunfähig bis*, *festgestellt am* und ob es eine Erst- oder Folgebescheinigung ist.
   - *Meldung mit AU*: Sie haben eine Bescheinigung auf Papier (z. B. privat versichert) – als PDF oder Foto hochladen.
   - *Kind krank*: Betreuung eines erkrankten Kindes (§ 45 SGB V), Bescheinigung hochladen oder nachreichen.
2. **Angaben ausfüllen und absenden.** Mit einer privaten E-Mail-Adresse erhalten Sie eine Bestätigung mit einem persönlichen Link zur Statusseite.
3. **Statusseite:** Dort sehen Sie den Stand, reichen Nachweise nach und beantworten Rückfragen.

Ihre Angaben werden verschlüsselt gespeichert und nur von der zuständigen Personalverwaltung eingesehen.
"""

DEFAULT_STAFF = """## Krankmeldungen bearbeiten

- **Übersicht:** heute eingegangene und offene Meldungen, Kennzahlen. **Liste:** Filter nach Art, Stand, Arbeitgeber und Zeitraum, Suche nach Name, Aktenzeichen oder Personalnummer, CSV-Export.
- **Stand setzen:** *Neu → In Bearbeitung → Bearbeitet*. Fehlt der Nachweis, steht die Meldung auf *Nachweis fehlt*; reicht die Person ihn über die Statusseite nach, wird sie wieder *Neu* und Sie erhalten eine Mail.
- **eAU:** Die Meldung startet mit *Abruf offen*. Rufen Sie die eAU mit den gemeldeten Daten (AU-Beginn!) beim GKV-Kommunikationsserver ab und setzen Sie *eAU abgerufen* oder *Abruf erfolglos*. Bei *Abruf erfolglos* schreiben Sie der Person eine **Nachricht** – sie antwortet oder reicht einen Nachweis über die Statusseite nach.
- **Notizen** sind intern; **Nachrichten** sieht die meldende Person auf ihrer Statusseite (und per Mail, falls sie eine Adresse angegeben hat).
- **Datenschutz:** Jeder Zugriff wird protokolliert. Bearbeitete Meldungen werden nach der eingestellten Frist automatisch gelöscht.
"""


def md(text: str) -> Markup:
    return Markup(_md.render(text or ""))


def _on() -> None:
    if "krank" not in enabled_modules():
        raise HTTPException(404, "Der Krankmelder ist auf diesem Server nicht eingeschaltet.")


def _ctx(request: Request, embed: bool, db: Session) -> dict:
    cfg = get_settings(db)
    return {"layout": "base_embed.html" if embed else "base.html", "R": EMBED if embed else PUBLIC, "embed": embed,
            "embed_label": cfg.get("krank_title") or "Krankmeldung", "embed_icon": "fa-notes-medical",
            "embed_public_path": request.url.path.replace(EMBED, PUBLIC, 1), "cfg": cfg, "kinds": krank.KINDS,
            "statuses": krank.STATUSES}


def _access(request: Request, db: Session, ticket: str | None) -> tuple[User | None, str | None]:
    """(angemeldete Person, gültiges Ticket) – Zugang besteht, wenn eines von beiden vorhanden ist."""
    user = session_user(request, db)
    if user is not None:
        return user, None
    if not krank.public_open(get_settings(db)):
        return None, None
    for t in (ticket, request.session.get("krank_ticket")):
        if krank.ticket_valid(t):
            return None, t
    return None, None


def _with_k(url: str, ticket: str | None, embed: bool) -> str:
    return f"{url}{'&' if '?' in url else '?'}k={quote(ticket)}" if (ticket and embed) else url


# --- Öffentlich: Einstieg, Passwort, Zugangslink -----------------------------------------------------

def _start(request: Request, embed: bool, k: str, db: Session):
    _on()
    ctx = _ctx(request, embed, db)
    user, ticket = _access(request, db, k)
    if user is None and ticket is None:
        return render(request, "krank_start.html", None if embed else session_user(request, db), gate=True,
                      public=krank.public_open(ctx["cfg"]), has_password=bool(ctx["cfg"].get("krank_password_hash")),
                      **ctx)
    return render(request, "krank_start.html", user, gate=False, ticket=ticket,
                  enabled=krank.enabled_kinds(ctx["cfg"]), intro=md(ctx["cfg"].get("krank_intro") or ""), **ctx)


@app.get(PUBLIC)
def krank_start(request: Request, k: str = "", db: Session = Depends(get_db)):
    return _start(request, False, k, db)


@app.get(EMBED)
def krank_start_embed(request: Request, k: str = "", db: Session = Depends(get_db)):
    return _start(request, True, k, db)


async def _login(request: Request, embed: bool, db: Session):
    _on()
    rate_limit(request, "krank-pw", limit=10, window=900)
    form = await request.form()
    cfg = get_settings(db)
    R = EMBED if embed else PUBLIC
    if cfg.get("krank_public") != "1" or not krank.check_password(cfg, str(form.get("password") or "")):
        flash(request, "Das Passwort ist nicht korrekt.", "error")
        return redirect(R + ("?fehler=1" if embed else ""))
    ticket = krank.make_ticket()
    request.session["krank_ticket"] = ticket
    return redirect(_with_k(R, ticket, embed))


@app.post(PUBLIC + "/login")
async def krank_login(request: Request, db: Session = Depends(get_db)):
    return await _login(request, False, db)


@app.post(EMBED + "/login")
async def krank_login_embed(request: Request, db: Session = Depends(get_db)):
    return await _login(request, True, db)


def _token_login(request: Request, token: str, embed: bool, db: Session):
    _on()
    rate_limit(request, "krank-token", limit=30, window=900)
    cfg = get_settings(db)
    if cfg.get("krank_public") != "1" or not krank.token_matches(cfg, token):
        raise HTTPException(404, "Dieser Zugangslink ist nicht (mehr) gültig. Bitte wenden Sie sich an die Personalverwaltung.")
    ticket = krank.make_ticket()
    request.session["krank_ticket"] = ticket
    return redirect(_with_k(EMBED if embed else PUBLIC, ticket, embed))


@app.get(PUBLIC + "/z/{token}")
def krank_token(request: Request, token: str, db: Session = Depends(get_db)):
    return _token_login(request, token, False, db)


@app.get(EMBED + "/z/{token}")
def krank_token_embed(request: Request, token: str, db: Session = Depends(get_db)):
    return _token_login(request, token, True, db)


def _help(request: Request, embed: bool, db: Session):
    _on()
    ctx = _ctx(request, embed, db)
    return render(request, "krank_help.html", None if embed else session_user(request, db),
                  text=md(ctx["cfg"].get("krank_text_instructions") or DEFAULT_INSTRUCTIONS), title="Anleitung", **ctx)


@app.get(PUBLIC + "/anleitung")
def krank_help(request: Request, db: Session = Depends(get_db)):
    return _help(request, False, db)


@app.get(EMBED + "/anleitung")
def krank_help_embed(request: Request, db: Session = Depends(get_db)):
    return _help(request, True, db)


# --- Status, Fertig, PDF (feste Pfade vor /krank/{kind}) ------------------------------------------------

def _done(request: Request, embed: bool, r: int, d: str, s: str, db: Session):
    _on()
    report = db.get(KrankReport, r)
    if report is None or not krank.download_valid(r, d):
        raise HTTPException(404, "Diese Bestätigungsseite ist abgelaufen. Den Stand Ihrer Meldung sehen Sie über den "
                                 "Link in der Bestätigungsmail.")
    user = None if embed else session_user(request, db)
    ctx = _ctx(request, embed, db)
    return render(request, "krank_done.html", user, report=report, d=d, s=s, data=krank.data(report),
                  kind_label=krank.kind_label(report.kind), status_url=f"{ctx['R']}/s/{s}" if krank.by_track(db, s) is report else "",
                  thanks=request.query_params.get("danke") == "1", **ctx)


@app.get(PUBLIC + "/fertig")
def krank_done(request: Request, r: int = 0, d: str = "", s: str = "", db: Session = Depends(get_db)):
    return _done(request, False, r, d, s, db)


@app.get(EMBED + "/fertig")
def krank_done_embed(request: Request, r: int = 0, d: str = "", s: str = "", db: Session = Depends(get_db)):
    return _done(request, True, r, d, s, db)


def _pdf_response(report: KrankReport) -> Response:
    return Response(krank.pdf(report), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{report.ref_no}.pdf"',
                             "Cache-Control": "no-store"})


@app.get(PUBLIC + "/pdf/{report_id}")
@app.get(EMBED + "/pdf/{report_id}")
def krank_pdf_public(report_id: int, t: str = "", db: Session = Depends(get_db)):
    _on()
    report = db.get(KrankReport, report_id)
    if report is None or not krank.download_valid(report_id, t):
        raise HTTPException(404, "Der Download-Link ist abgelaufen (1 Stunde gültig).")
    krank.audit(db, None, report, "pdf", "meldende Person (Bestätigungsseite)")
    db.commit()
    return _pdf_response(report)


async def _feedback(request: Request, embed: bool, db: Session):
    _on()
    rate_limit(request, "krank-feedback", limit=5, window=3600)
    form = await request.form()
    R = EMBED if embed else PUBLIC
    r, d, s = str(form.get("r") or ""), str(form.get("d") or ""), str(form.get("s") or "")
    if not r.isdigit() or not krank.download_valid(int(r), d):
        raise HTTPException(400, "Die Seite ist abgelaufen.")
    try:
        rating = int(form.get("rating") or -1)
    except ValueError:
        rating = -1
    if 0 <= rating <= 5 and get_settings(db).get("krank_feedback") == "1":
        db.add(KrankFeedback(rating=rating, note=str(form.get("note") or "")[:1000]))
        db.commit()
    return redirect(f"{R}/fertig?" + urlencode({"r": r, "d": d, "s": s, "danke": "1"}))


@app.post(PUBLIC + "/feedback")
async def krank_feedback(request: Request, db: Session = Depends(get_db)):
    return await _feedback(request, False, db)


@app.post(EMBED + "/feedback")
async def krank_feedback_embed(request: Request, db: Session = Depends(get_db)):
    return await _feedback(request, True, db)


def _status(request: Request, embed: bool, token: str, db: Session):
    _on()
    rate_limit(request, "krank-status", limit=60, window=600)
    report = krank.by_track(db, token)
    if report is None:
        raise HTTPException(404, "Diese Meldung gibt es nicht (mehr). Bearbeitete Meldungen werden nach Ablauf der "
                                 "Aufbewahrungsfrist gelöscht.")
    ctx = _ctx(request, embed, db)
    events = [(e, krank.event_text(e)) for e in report.events if e.public]
    return render(request, "krank_status.html", None if embed else session_user(request, db), report=report,
                  token=token, data=krank.data(report), rows=krank.rows(report), events=events,
                  kind_label=krank.kind_label(report.kind), files=[(f, krank.file_name(f)) for f in report.files],
                  **ctx)


@app.get(PUBLIC + "/s/{token}")
def krank_status(request: Request, token: str, db: Session = Depends(get_db)):
    return _status(request, False, token, db)


@app.get(EMBED + "/s/{token}")
def krank_status_embed(request: Request, token: str, db: Session = Depends(get_db)):
    return _status(request, True, token, db)


async def _read_upload(form, field: str) -> tuple[str, bytes] | None:
    up = form.get(field)
    if up is None or not hasattr(up, "read") or not getattr(up, "filename", ""):
        return None
    content = await up.read(krank.MAX_FILE + 1)
    return (up.filename, content) if content else None


async def _status_post(request: Request, embed: bool, token: str, db: Session):
    _on()
    rate_limit(request, "krank-reply", limit=10, window=3600)
    report = krank.by_track(db, token)
    if report is None:
        raise HTTPException(404, "Diese Meldung gibt es nicht (mehr).")
    form = await request.form()
    R = EMBED if embed else PUBLIC
    try:
        upload = await _read_upload(form, "file")
        krank.employee_reply(db, report, str(form.get("text") or ""), upload)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return redirect(f"{R}/s/{token}")
    db.commit()
    flash(request, "Danke – Ihre Angaben sind bei der Personalverwaltung eingegangen.")
    return redirect(f"{R}/s/{token}" + ("?ok=1" if embed else ""))


@app.post(PUBLIC + "/s/{token}")
async def krank_status_post(request: Request, token: str, db: Session = Depends(get_db)):
    return await _status_post(request, False, token, db)


@app.post(EMBED + "/s/{token}")
async def krank_status_post_embed(request: Request, token: str, db: Session = Depends(get_db)):
    return await _status_post(request, True, token, db)


@app.get(PUBLIC + "/s/{token}/pdf")
@app.get(EMBED + "/s/{token}/pdf")
def krank_status_pdf(request: Request, token: str, db: Session = Depends(get_db)):
    _on()
    rate_limit(request, "krank-status", limit=60, window=600)
    report = krank.by_track(db, token)
    if report is None:
        raise HTTPException(404, "Diese Meldung gibt es nicht (mehr).")
    krank.audit(db, None, report, "pdf", "meldende Person (Statusseite)")
    db.commit()
    return _pdf_response(report)


# --- Meine Krankmeldungen ----------------------------------------------------------------------------

@app.get(PUBLIC + "/meine")
def krank_mine(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _on()
    reports = db.scalars(select(KrankReport).where(KrankReport.user_id == user.id)
                         .order_by(KrankReport.created_at.desc())).all() if user.krank_history else []
    return render(request, "krank_mine.html", user, reports=reports, krank=krank, **_ctx(request, False, db))


@app.post(PUBLIC + "/meine/einstellung", dependencies=[Depends(check_csrf)])
async def krank_mine_setting(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _on()
    form = await request.form()
    if form.get("on") == "1":
        user.krank_history = True
        flash(request, "„Meine Krankmeldungen“ ist eingeschaltet. Künftige Meldungen, die Sie angemeldet abgeben, "
                       "erscheinen hier – verschlüsselt gespeichert.")
    else:
        n = krank.forget_user(db, user)
        flash(request, f"„Meine Krankmeldungen“ ist ausgeschaltet; {n} Meldung(en) sind nicht mehr mit Ihrem Konto "
                       "verknüpft. Bei der Personalverwaltung bleiben sie unverändert.")
    db.commit()
    return redirect(PUBLIC + "/meine")


@app.post(PUBLIC + "/meine/uebernehmen", dependencies=[Depends(check_csrf)])
async def krank_mine_keep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _on()
    form = await request.form()
    r, d = str(form.get("r") or ""), str(form.get("d") or "")
    report = db.get(KrankReport, int(r)) if r.isdigit() else None
    if report is None or not krank.download_valid(report.id, d):
        raise HTTPException(400, "Die Bestätigungsseite ist abgelaufen.")
    krank.keep_for_user(db, report, user)
    db.commit()
    flash(request, f"Meldung {report.ref_no} steht jetzt unter „Meine Krankmeldungen“ (verschlüsselt gespeichert).")
    return redirect(PUBLIC + "/meine")


@app.get(PUBLIC + "/meine/{report_id}/pdf")
def krank_mine_pdf(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _on()
    report = db.get(KrankReport, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(404, "Meldung nicht gefunden.")
    krank.audit(db, user, report, "pdf", "eigene Meldung")
    db.commit()
    return _pdf_response(report)


# --- Melden (Formulare) ----------------------------------------------------------------------------

def _form(request: Request, embed: bool, kind: str, k: str, db: Session):
    _on()
    ctx = _ctx(request, embed, db)
    if kind not in krank.enabled_kinds(ctx["cfg"]):
        raise HTTPException(404, "Diesen Meldeweg gibt es hier nicht.")
    user, ticket = _access(request, db, k)
    if user is None and ticket is None:
        return redirect(ctx["R"])
    prefill = {}
    if user is not None:
        parts = user.name.split()
        prefill = {"first_name": " ".join(parts[:-1]) if len(parts) > 1 else user.name,
                   "last_name": parts[-1] if len(parts) > 1 else "", "email": user.email}
    stored = request.session.pop("krank_form", None) if not embed else None
    return render(request, "krank_form.html", user, kind=kind, ticket=ticket, employers=krank.employers(db),
                  values=(stored or {}).get("values") or prefill, error=(stored or {}).get("error") or request.query_params.get("fehler", ""),
                  today=krank.today(), weekday_ok=krank.today().weekday() <= 4, **ctx)


async def _submit(request: Request, embed: bool, kind: str, db: Session):
    _on()
    ctx = _ctx(request, embed, db)
    R = ctx["R"]
    if kind not in krank.enabled_kinds(ctx["cfg"]):
        raise HTTPException(404, "Diesen Meldeweg gibt es hier nicht.")
    form = await request.form()
    ticket = str(form.get("k") or "")
    user, ticket = _access(request, db, ticket)
    if user is None and ticket is None:
        flash(request, "Ihre Sitzung ist abgelaufen. Bitte erneut anmelden bzw. das Passwort eingeben.", "error")
        return redirect(R)
    if user is not None and not csrf_valid(request.session, form.get("csrf")):
        raise HTTPException(400, "Sitzung abgelaufen. Bitte Seite neu laden und erneut versuchen.")
    rate_limit(request, "krank-submit", limit=20, window=3600)
    values = {k: str(v) for k, v in form.items() if isinstance(v, str) and k not in ("csrf", "k")}
    emp_id = values.get("employer", "")
    employer = db.get(KrankEmployer, int(emp_id)) if emp_id.isdigit() else None
    try:
        upload = await _read_upload(form, "file")
        report, track, _warnings = krank.create(db, kind, values, employer, upload, user)
    except ValueError as exc:
        db.rollback()
        if embed:
            return redirect(_with_k(f"{R}/{kind}?fehler={quote(str(exc))}", ticket, True))
        request.session["krank_form"] = {"values": values, "error": str(exc)}
        return redirect(f"{R}/{kind}")
    db.commit()
    from . import worker
    worker.wake()
    return redirect(f"{R}/fertig?" + urlencode({"r": report.id, "d": krank.download_token(report.id), "s": track}))


@app.get(PUBLIC + "/{kind}")
def krank_form(request: Request, kind: str, k: str = "", db: Session = Depends(get_db)):
    return _form(request, False, kind, k, db)


@app.get(EMBED + "/{kind}")
def krank_form_embed(request: Request, kind: str, k: str = "", db: Session = Depends(get_db)):
    return _form(request, True, kind, k, db)


@app.post(PUBLIC + "/{kind}")
async def krank_submit(request: Request, kind: str, db: Session = Depends(get_db)):
    return await _submit(request, False, kind, db)


@app.post(EMBED + "/{kind}")
async def krank_submit_embed(request: Request, kind: str, db: Session = Depends(get_db)):
    return await _submit(request, True, kind, db)


# --- Personalverwaltung ------------------------------------------------------------------------------

def _staff(db: Session, user: User) -> None:
    _on()
    if not krank.uses_module(db, user):
        raise HTTPException(403, "Für Krankmeldungen fehlt die Berechtigung bzw. die Zuständigkeit für einen Arbeitgeber. "
                                 "Bitte wenden Sie sich an die Verwaltung des Krankmelders.")


def _manager(user: User) -> None:
    _on()
    if not krank.manager(user):
        raise HTTPException(403, "Dafür fehlt das Recht „Krankmelder verwalten“.")


def _report(db: Session, user: User, report_id: int) -> KrankReport:
    _staff(db, user)
    report = db.get(KrankReport, report_id)
    if report is None or not krank.can_see(db, user, report):
        raise HTTPException(404, "Meldung nicht gefunden.")
    return report


def _visible_employers(db: Session, user: User) -> list[KrankEmployer]:
    ids = krank.scope(db, user)
    return [e for e in krank.employers(db) if ids is None or e.id in ids]


@app.get("/krankmelder")
def krank_overview(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _staff(db, user)
    st = krank.stats(db, user)
    open_reports = db.scalars(krank.reports_query(db, user).where(KrankReport.status != "done")
                              .order_by(KrankReport.created_at.desc()).limit(15)).all()
    return render(request, "krank_overview.html", user, stats=st, today=krank.today_list(db, user), open_reports=open_reports,
                  krank=krank, cfg=get_settings(db))


@app.get("/krankmelder/liste")
def krank_list(request: Request, page: int = 1, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _staff(db, user)
    f = {k: request.query_params.get(k, "").strip()[:100] for k in krank.FILTERS}
    items = krank.search(db, user, f)
    page = max(1, min(page, 1000))
    qs = urlencode({k: v for k, v in f.items() if v})
    return render(request, "krank_list.html", user, items=items[(page - 1) * PAGE: page * PAGE], total=len(items), page=page,
                  pages=(len(items) + PAGE - 1) // PAGE, f=f, qs=qs, employers=_visible_employers(db, user), krank=krank)


@app.get("/krankmelder/export.csv")
def krank_export(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _staff(db, user)
    f = {k: request.query_params.get(k, "").strip()[:100] for k in krank.FILTERS}
    items = krank.search(db, user, f)
    krank.audit(db, user, None, "export", f"{len(items)} Meldungen, Filter: {json.dumps({k: v for k, v in f.items() if v}, ensure_ascii=False)}",
                ref_no="Export")
    db.commit()
    return Response(krank.csv_export(items), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="krankmeldungen.csv"', "Cache-Control": "no-store"})


@app.get("/krankmelder/statistik")
def krank_stats(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _staff(db, user)
    return render(request, "krank_stats.html", user, stats=krank.stats(db, user), krank=krank,
                  feedback=db.scalars(select(KrankFeedback).where(KrankFeedback.note != "")
                                      .order_by(KrankFeedback.created_at.desc()).limit(20)).all() if krank.manager(user) else [])


@app.get("/krankmelder/hilfe")
def krank_staff_help(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _staff(db, user)
    cfg = get_settings(db)
    return render(request, "krank_help.html", user, text=md(cfg.get("krank_text_staff") or DEFAULT_STAFF),
                  title="Anleitung für die Personalverwaltung", layout="base.html", R=PUBLIC, embed=False, cfg=cfg)


@app.get("/krankmelder/protokoll")
def krank_log(request: Request, ref: str = "", page: int = 1, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    q = select(KrankAccess).order_by(KrankAccess.id.desc())
    if ref.strip():
        q = q.where(KrankAccess.ref_no == ref.strip()[:30])
    page = max(1, min(page, 1000))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.limit(100).offset((page - 1) * 100)).all()
    mails = db.scalars(select(Notification).where(Notification.kind == "krank").order_by(Notification.id.desc()).limit(100)).all()
    return render(request, "krank_log.html", user, rows=rows, ref=ref, page=page, pages=(total + 99) // 100, mails=mails,
                  cfg=get_settings(db))


@app.post("/krankmelder/testmail", dependencies=[Depends(check_csrf)])
async def krank_testmail(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    rate_limit(request, "krank-testmail", limit=5, window=600, key=str(user.id))
    form = await request.form()
    to = str(form.get("to") or "").strip()
    if not krank.EMAIL_RE.match(to):
        flash(request, "Bitte eine gültige E-Mail-Adresse angeben.", "error")
    else:
        try:
            notify.test_smtp(get_settings(db), to)
            flash(request, f"Testnachricht an {to} versendet.")
        except notify.MailError as exc:
            flash(request, str(exc), "error")
    return redirect("/krankmelder/protokoll#mails")


@app.get("/krankmelder/{report_id:int}")
def krank_detail(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    krank.audit(db, user, report, "angesehen")
    db.commit()
    return render(request, "krank_detail.html", user, report=report, data=krank.data(report), rows=krank.rows(report),
                  events=[(e, krank.event_text(e)) for e in reversed(report.events)], krank=krank,
                  files=[(f, krank.file_name(f)) for f in report.files], status_link=krank.status_link(db, report),
                  manager=krank.manager(user), dms_on="dms" in enabled_modules())


@app.get("/krankmelder/{report_id:int}/pdf")
def krank_detail_pdf(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    krank.audit(db, user, report, "pdf")
    db.commit()
    return _pdf_response(report)


@app.get("/krankmelder/{report_id:int}/datei/{file_id:int}")
def krank_file(report_id: int, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    f = next((x for x in report.files if x.id == file_id), None)
    if f is None:
        raise HTTPException(404, "Datei nicht gefunden.")
    name = krank.file_name(f)
    krank.audit(db, user, report, "datei", name)
    db.commit()
    return Response(krank.read_file(f), media_type=f.mime,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "no-store"})


@app.post("/krankmelder/{report_id:int}/status", dependencies=[Depends(check_csrf)])
async def krank_set_status(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    form = await request.form()
    if krank.set_status(db, report, str(form.get("status") or ""), user, str(form.get("note") or "").strip()[:2000]):
        db.commit()
        flash(request, f"Stand: {krank.status_label(report.status)}.")
    return redirect(f"/krankmelder/{report.id}")


@app.post("/krankmelder/{report_id:int}/notiz", dependencies=[Depends(check_csrf)])
async def krank_note(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    text = str((await request.form()).get("text") or "").strip()
    if text:
        krank.add_note(db, report, user, text)
        db.commit()
        flash(request, "Notiz gespeichert (nur intern sichtbar).")
    return redirect(f"/krankmelder/{report.id}#verlauf")


@app.post("/krankmelder/{report_id:int}/nachricht", dependencies=[Depends(check_csrf)])
async def krank_message(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    text = str((await request.form()).get("text") or "").strip()
    if text:
        mailed = krank.message(db, report, user, text)
        db.commit()
        from . import worker
        worker.wake()
        flash(request, "Nachricht gespeichert und auf der Statusseite sichtbar" + (" – per E-Mail verschickt." if mailed else
              ". Es ist keine E-Mail-Adresse hinterlegt; bitte die Person anderweitig informieren."))
    return redirect(f"/krankmelder/{report.id}#verlauf")


@app.post("/krankmelder/{report_id:int}/datei", dependencies=[Depends(check_csrf)])
async def krank_staff_upload(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    upload = await _read_upload(await request.form(), "file")
    if upload is None:
        flash(request, "Bitte eine Datei auswählen.", "error")
    else:
        try:
            krank.add_staff_file(db, report, user, *upload)
            db.commit()
            flash(request, "Datei hinzugefügt (verschlüsselt gespeichert).")
        except ValueError as exc:
            flash(request, str(exc), "error")
    return redirect(f"/krankmelder/{report.id}")


@app.post("/krankmelder/{report_id:int}/loeschen", dependencies=[Depends(check_csrf)])
async def krank_delete(request: Request, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _report(db, user, report_id)
    _manager(user)
    reason = str((await request.form()).get("reason") or "").strip()[:300] or "ohne Angabe"
    ref = report.ref_no
    krank.delete_report(db, report, user, reason)
    db.commit()
    flash(request, f"Meldung {ref} gelöscht (protokolliert).")
    return redirect("/krankmelder/liste")


@app.post("/krankmelder/archivieren", dependencies=[Depends(check_csrf)])
async def krank_bulk_delete(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Sammellöschen je Arbeitgeber (wie „Archivieren“ im Krankmelder), optional nur Bearbeitete bis zu einem Datum."""
    _manager(user)
    form = await request.form()
    ids = [int(x) for x in form.getlist("employer") if str(x).isdigit()]
    only_done = form.get("only_done") == "1"
    until = str(form.get("until") or "")
    reason = str(form.get("reason") or "").strip()[:300] or "Sammellöschung"
    if not ids:
        flash(request, "Bitte mindestens einen Arbeitgeber auswählen.", "error")
        return redirect("/krankmelder/verwaltung#loeschen")
    f = {"to": until}
    items = [r for r in krank.search(db, user, f) if r.employer_id in ids and (not only_done or r.status == "done")]
    for r in items:
        krank.delete_report(db, r, user, reason)
    db.commit()
    flash(request, f"{len(items)} Meldung(en) gelöscht (protokolliert).")
    return redirect("/krankmelder/verwaltung#loeschen")


# --- Verwaltung des Moduls ----------------------------------------------------------------------------

@app.get("/krankmelder/verwaltung")
def krank_admin(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    cfg = get_settings(db)
    from . import dms
    return render(request, "krank_admin.html", user, cfg=cfg, krank=krank, employers=krank.employers(db),
                  enabled=krank.enabled_kinds(cfg), access_link=krank.access_link(db, cfg),
                  public_url=links.module_url(db, "krank", PUBLIC, cfg), embed_url=links.module_url(db, "krank", EMBED, cfg),
                  default_instructions=DEFAULT_INSTRUCTIONS, default_staff=DEFAULT_STAFF,
                  areas=dms.tree(db) if "dms" in enabled_modules() else [], errors=sl.QR_ERRORS,
                  shortlink_new=("/shortlinks?new=" + quote(krank.access_link(db, cfg) or links.module_url(db, "krank", PUBLIC, cfg))
                                 + "&title=" + quote(cfg.get("krank_title") or "Krankmeldung")),
                  counts=dict(db.execute(select(KrankReport.employer_id, func.count(KrankReport.id)).group_by(KrankReport.employer_id)).all()))


@app.post("/krankmelder/verwaltung/allgemein", dependencies=[Depends(check_csrf)])
async def krank_admin_general(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    form = await request.form()
    kinds = [k for k in krank.KINDS if form.get(f"kind_{k}") == "1"]
    if not kinds:
        flash(request, "Mindestens ein Meldeweg muss angeboten werden.", "error")
        return redirect("/krankmelder/verwaltung")
    email = str(form.get("global_email") or "").strip().lower()
    if email and not krank.EMAIL_RE.match(email):
        flash(request, "Die Adresse der Personalverwaltung ist ungültig.", "error")
        return redirect("/krankmelder/verwaltung")

    def num(key, lo, hi):
        try:
            return str(min(max(int(form.get(key) or 0), lo), hi))
        except ValueError:
            return "0"
    old_days = get_settings(db).get("krank_retention_days")
    for key, value in (("krank_title", str(form.get("title") or "Krankmeldung").strip()[:120] or "Krankmeldung"),
                       ("krank_intro", str(form.get("intro") or "")[:5000]),
                       ("krank_kinds", ",".join(kinds)), ("krank_global_email", email),
                       ("krank_subject_prefix", str(form.get("subject_prefix") or "").strip()[:100]),
                       ("krank_public", "1" if form.get("public") == "1" else "0"),
                       ("krank_feedback", "1" if form.get("feedback") == "1" else "0"),
                       ("krank_retention_days", num("retention_days", 0, 3650)),
                       ("krank_proof_reminder_days", num("reminder_days", 0, 60)),
                       ("krank_embed", "1" if form.get("embed") == "1" else "0"),
                       ("krank_embed_origins", " ".join(str(form.get("embed_origins") or "").split())[:2000])):
        set_setting(db, key, value)
    db.flush()
    if get_settings(db).get("krank_retention_days") != old_days:
        krank.recompute_retention(db)
    krank.audit(db, user, None, "einstellungen", "Allgemein, Meldewege, Datenschutz", ref_no="Verwaltung")
    db.commit()
    flash(request, "Einstellungen gespeichert.")
    return redirect("/krankmelder/verwaltung")


@app.post("/krankmelder/verwaltung/zugang", dependencies=[Depends(check_csrf)])
async def krank_admin_access(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    form = await request.form()
    action = form.get("action")
    if action == "password":
        pw = str(form.get("password") or "")
        if len(pw) < 6:
            flash(request, "Das Passwort muss mindestens 6 Zeichen haben.", "error")
            return redirect("/krankmelder/verwaltung#zugang")
        krank.set_password(db, pw)
        flash(request, "Neues Passwort gespeichert. Bitte den Beschäftigten mitteilen.")
    elif action == "clear_password":
        krank.set_password(db, "")
        flash(request, "Passwort entfernt – Zugang ohne Konto nur noch über den Zugangslink.")
    elif action == "new_token":
        krank.new_access_token(db)
        flash(request, "Neuer Zugangslink erzeugt. Der bisherige Link (und QR-Code) funktioniert nicht mehr.")
    elif action == "clear_token":
        set_setting(db, "krank_access_token_enc", "")
        flash(request, "Zugangslink entfernt.")
    krank.audit(db, user, None, "zugang", str(action), ref_no="Verwaltung")
    db.commit()
    return redirect("/krankmelder/verwaltung#zugang")


@app.get("/krankmelder/qr.{fmt}")
def krank_qr(fmt: str, size: int = 10, dark: str = "#000000", light: str = "#ffffff", error: str = "m", border: int = 2,
             download: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    cfg = get_settings(db)
    target = krank.access_link(db, cfg) or links.module_url(db, "krank", PUBLIC, cfg)
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    data, media = sl.qr_image(target, opts)
    return Response(data, media_type=media, headers={"Cache-Control": "no-store",
                                                     "Content-Disposition": f'{"attachment" if download else "inline"}; filename="krankmelder-qr.{opts["fmt"]}"'})


@app.post("/krankmelder/verwaltung/texte", dependencies=[Depends(check_csrf)])
async def krank_admin_texts(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    form = await request.form()
    for key in ("instructions", "staff"):
        text = str(form.get(key) or "").replace("\r\n", "\n")[:50000]
        default = DEFAULT_INSTRUCTIONS if key == "instructions" else DEFAULT_STAFF
        set_setting(db, f"krank_text_{key}", "" if text.strip() == default.strip() else text)
    db.commit()
    flash(request, "Anleitungen gespeichert.")
    return redirect("/krankmelder/verwaltung#texte")


@app.post("/krankmelder/arbeitgeber/neu", dependencies=[Depends(check_csrf)])
async def krank_employer_new(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    name = " ".join(str((await request.form()).get("name") or "").split())[:200]
    if not name:
        flash(request, "Bitte einen Namen angeben.", "error")
        return redirect("/krankmelder/verwaltung#arbeitgeber")
    if db.scalar(select(KrankEmployer.id).where(KrankEmployer.name == name)) is not None:
        flash(request, f"„{name}“ gibt es schon.", "error")
        return redirect("/krankmelder/verwaltung#arbeitgeber")
    pos = (db.scalar(select(func.max(KrankEmployer.position))) or 0) + 1
    emp = KrankEmployer(name=name, position=pos)
    db.add(emp)
    db.commit()
    flash(request, f"Arbeitgeber „{name}“ angelegt. Bitte Empfänger und Zuständige festlegen.")
    return redirect(f"/krankmelder/arbeitgeber/{emp.id}")


@app.get("/krankmelder/arbeitgeber/{emp_id:int}")
def krank_employer(request: Request, emp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    emp = db.get(KrankEmployer, emp_id)
    if emp is None:
        raise HTTPException(404, "Arbeitgeber nicht gefunden.")
    from . import dms
    return render(request, "krank_employer.html", user, emp=emp,
                  users=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all(),
                  groups=db.scalars(select(Group).order_by(Group.name)).all(),
                  sel_users={r.user_id for r in emp.responsible if r.user_id},
                  sel_groups={r.group_id for r in emp.responsible if r.group_id},
                  areas=dms.tree(db) if "dms" in enabled_modules() else [], dms_on="dms" in enabled_modules(),
                  recipients=krank.staff_recipients(db, emp, get_settings(db)),
                  without_right=[r.user for r in emp.responsible if r.user and not r.user.can("krank")])


@app.post("/krankmelder/arbeitgeber/{emp_id:int}", dependencies=[Depends(check_csrf)])
async def krank_employer_save(request: Request, emp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    emp = db.get(KrankEmployer, emp_id)
    if emp is None:
        raise HTTPException(404, "Arbeitgeber nicht gefunden.")
    form = await request.form()
    name = " ".join(str(form.get("name") or "").split())[:200]
    if name and name != emp.name:
        if db.scalar(select(KrankEmployer.id).where(KrankEmployer.name == name)) is not None:
            flash(request, f"„{name}“ gibt es schon.", "error")
            return redirect(f"/krankmelder/arbeitgeber/{emp.id}")
        emp.name = name
    addrs = [a.strip().lower() for a in str(form.get("emails") or "").replace(",", "\n").replace(";", "\n").split("\n") if a.strip()]
    bad = [a for a in addrs if not krank.EMAIL_RE.match(a)]
    if bad:
        flash(request, "Ungültige Adresse(n): " + ", ".join(bad[:5]), "error")
        return redirect(f"/krankmelder/arbeitgeber/{emp.id}")
    emp.emails = "\n".join(dict.fromkeys(addrs))
    color = str(form.get("color") or "")
    emp.color = color if sl.COLOR_RE.match(color) else emp.color
    emp.active = form.get("active") == "1"
    emp.send_global_copy = form.get("send_global_copy") == "1"
    emp.allow_remarks = form.get("allow_remarks") == "1"
    emp.attach_files = form.get("attach_files") == "1"
    emp.subject_prefix = str(form.get("subject_prefix") or "").strip()[:100]
    emp.dms_enabled = form.get("dms_enabled") == "1"
    area = str(form.get("dms_area_id") or "")
    emp.dms_area_id = int(area) if area.isdigit() and db.get(DmsArea, int(area)) else None
    users = {int(x) for x in form.getlist("users") if str(x).isdigit()}
    groups = {int(x) for x in form.getlist("groups") if str(x).isdigit()}
    emp.responsible.clear()
    db.flush()
    for uid in users:
        if db.get(User, uid):
            emp.responsible.append(KrankResponsible(user_id=uid))
    for gid in groups:
        if db.get(Group, gid):
            emp.responsible.append(KrankResponsible(group_id=gid))
    krank.audit(db, user, None, "arbeitgeber", f"„{emp.name}“ geändert", ref_no="Verwaltung")
    db.commit()
    flash(request, f"„{emp.name}“ gespeichert.")
    return redirect(f"/krankmelder/arbeitgeber/{emp.id}")


@app.post("/krankmelder/arbeitgeber/{emp_id:int}/verschieben", dependencies=[Depends(check_csrf)])
async def krank_employer_move(request: Request, emp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    direction = str((await request.form()).get("dir") or "")
    items = krank.employers(db)
    idx = next((i for i, e in enumerate(items) if e.id == emp_id), None)
    if idx is not None:
        other = idx - 1 if direction == "up" else idx + 1
        if 0 <= other < len(items):
            items[idx], items[other] = items[other], items[idx]
        for i, e in enumerate(items):
            e.position = i
        db.commit()
    return redirect("/krankmelder/verwaltung#arbeitgeber")


@app.post("/krankmelder/arbeitgeber/{emp_id:int}/loeschen", dependencies=[Depends(check_csrf)])
async def krank_employer_delete(request: Request, emp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    emp = db.get(KrankEmployer, emp_id)
    if emp is not None:
        n = db.scalar(select(func.count(KrankReport.id)).where(KrankReport.employer_id == emp.id)) or 0
        if n:
            flash(request, f"„{emp.name}“ hat noch {n} Meldung(en). Bitte zuerst löschen oder den Arbeitgeber deaktivieren.", "error")
            return redirect("/krankmelder/verwaltung#arbeitgeber")
        krank.audit(db, user, None, "arbeitgeber", f"„{emp.name}“ gelöscht", ref_no="Verwaltung")
        db.delete(emp)
        db.commit()
        flash(request, "Arbeitgeber gelöscht.")
    return redirect("/krankmelder/verwaltung#arbeitgeber")


@app.post("/krankmelder/import", dependencies=[Depends(check_csrf)])
async def krank_import(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _manager(user)
    up = (await request.form()).get("archive")
    if up is None or not getattr(up, "filename", ""):
        flash(request, "Bitte eine ZIP-Datei auswählen.", "error")
        return redirect("/krankmelder/verwaltung#import")
    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        while chunk := await up.read(1024 * 1024):
            tmp.write(chunk)
        tmp.flush()
        try:
            counts = krank.import_archive(db, Path(tmp.name), user)
        except Exception as exc:  # noqa: BLE001  (defekte ZIP/DB: verständliche Meldung, nichts halb übernehmen)
            db.rollback()
            flash(request, f"Import nicht möglich: {exc}", "error")
            return redirect("/krankmelder/verwaltung#import")
    db.commit()
    flash(request, (f"Import abgeschlossen: {counts['reports']} Meldungen ({counts['skipped']} schon vorhanden), "
                    f"{counts['files']} Dateien ({counts['missing_files']} nicht gefunden), {counts['employers']} Arbeitgeber, "
                    f"{counts['feedback']} Bewertungen, {counts['settings']} Einstellungen."))
    return redirect("/krankmelder/verwaltung#import")


@app.get("/krankmelder/verwaltung/vorschau.txt")
def krank_preview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hilfe beim Einrichten: Empfänger je Arbeitgeber als Text (ohne personenbezogene Meldungsdaten)."""
    _manager(user)
    cfg = get_settings(db)
    lines = [f"{e.name}: {', '.join(krank.staff_recipients(db, e, cfg)) or '– keine Empfänger –'}" for e in krank.employers(db)]
    return PlainTextResponse("\n".join(lines) + "\n")
