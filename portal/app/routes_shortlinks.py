"""Seiten und Weiterleitung des Kurzlink-Dienstes inkl. QR-Generator."""

import io
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import csvsafe, proxy, shortlinks as sl
from .config import settings
from .db import LOCAL_TZ, ShortLink, ShortVisit, User, get_settings, set_setting, to_local
from .main import (
    admin_user, app, check_csrf, flash, get_db, rate_limit, redirect, render, require, safe_next,
)

shortlink_user = require("shortlinks")


def _own_link(db: Session, link_id: int, user: User) -> ShortLink:
    link = db.get(ShortLink, link_id)
    if link is None or (link.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Kurzlink nicht gefunden.")
    return link


def _parse_local(value: str) -> datetime | None:
    """Datum/Uhrzeit aus einem datetime-local-Feld (Ortszeit) als UTC (naiv)."""
    try:
        local = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None) if local else None


def _local_input(dt: datetime | None) -> str:
    return to_local(dt).strftime("%Y-%m-%dT%H:%M") if dt else ""


def _apply(link: ShortLink, db: Session, form) -> str:
    """Formularwerte übernehmen. Gibt eine Fehlermeldung zurück oder ''."""
    target = sl.clean_url(str(form.get("target_url", "")))
    if not target:
        return "Bitte eine gültige Zieladresse angeben (beginnt mit http:// oder https://)."
    code = sl.normalize_code(str(form.get("code", "")))
    if code:
        if not sl.valid_code(code):
            return "Das Kürzel darf nur Kleinbuchstaben, Ziffern, - und _ enthalten (höchstens 64 Zeichen)."
        if code != link.code and sl.code_taken(db, code, link.id):
            return f"Das Kürzel „{code}“ ist schon vergeben."
        link.code = code
    elif not link.code:
        link.code = sl.new_code(db, int(get_settings(db).get("short_code_length") or 6))
    link.target_url = target
    link.title = " ".join(str(form.get("title", "")).split())[:255]
    link.tags = sl.clean_tags(str(form.get("tags", "")))
    link.valid_from = _parse_local(str(form.get("valid_from", "")))
    link.valid_until = _parse_local(str(form.get("valid_until", "")))
    if link.valid_from and link.valid_until and link.valid_until <= link.valid_from:
        return "„Gültig bis“ muss nach „Gültig ab“ liegen."
    max_visits = str(form.get("max_visits", "")).strip()
    link.max_visits = int(max_visits) if max_visits.isdigit() and int(max_visits) > 0 else None
    link.forward_query = form.get("forward_query") == "1"
    link.active = form.get("active", "1") == "1"
    code_http = str(form.get("redirect_code", "302"))
    link.redirect_code = int(code_http) if code_http.isdigit() and int(code_http) in sl.REDIRECT_CODES else 302
    return ""


# --- Verwaltung ----------------------------------------------------------------

@app.get("/shortlinks")
def shortlinks_list(request: Request, tag: str = "", all: str = "", new: str = "", title: str = "",
                    next: str = "", user: User = Depends(shortlink_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    show_all = user.is_admin and all == "1"
    q = select(ShortLink).options(joinedload(ShortLink.owner)).order_by(ShortLink.created_at.desc())
    if not show_all:
        q = q.where(ShortLink.owner_id == user.id)
    links = db.scalars(q).all()
    tags = sorted({t for link in links for t in link.tag_list})
    if tag:
        links = [link for link in links if tag in link.tag_list]
    return render(request, "shortlinks.html", user, links=links, tags=tags, tag=tag, show_all=show_all,
                  base=sl.short_base(cfg), cfg=cfg, usable=sl.usable, redirect_codes=sl.REDIRECT_CODES,
                  totals=sl.totals(db, None if show_all else user.id),
                  prefill=request.session.pop("shortlink_prefill", None)
                  or ({"target_url": new, "title": title, "next": safe_next(next) if next else ""} if new else None))


@app.post("/shortlinks", dependencies=[Depends(check_csrf)])
async def shortlinks_create(request: Request, user: User = Depends(shortlink_user), db: Session = Depends(get_db)):
    form = await request.form()
    link = ShortLink(owner_id=user.id, code="")
    error = _apply(link, db, form)
    if error:
        flash(request, error, "error")
        request.session["shortlink_prefill"] = {k: str(v) for k, v in form.items() if k != "csrf"}
        return redirect("/shortlinks#neu")
    db.add(link)
    db.commit()
    flash(request, f"Kurzlink angelegt: {sl.short_url(get_settings(db), link)}")
    nxt = str(form.get("next", ""))
    return redirect(safe_next(nxt) if nxt else f"/shortlinks/{link.id}")


@app.get("/shortlinks/qr")
def shortlinks_qr_tool(request: Request, text: str = "", user: User = Depends(shortlink_user)):
    """QR-Generator für beliebige Texte und Adressen."""
    return render(request, "qr.html", user, text=text, errors=sl.QR_ERRORS, link=None)


@app.get("/shortlinks/qr/image")
def shortlinks_qr_image(text: str = "", fmt: str = "svg", size: int = 8, dark: str = "#000000",
                        light: str = "#ffffff", error: str = "m", border: int = 2, download: str = "",
                        user: User = Depends(shortlink_user)):
    text = text[:2000]
    if not text:
        raise HTTPException(400, "Kein Inhalt für den QR-Code.")
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    try:
        data, media = sl.qr_image(text, opts)
    except ValueError as exc:  # zu lang für einen QR-Code
        raise HTTPException(400, f"QR-Code nicht möglich: {exc}") from exc
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="qr-code.{opts["fmt"]}"'
    return Response(data, media_type=media, headers=headers)


@app.get("/shortlinks/{link_id}")
def shortlink_detail(request: Request, link_id: int, days: int = 30, bots: str = "",
                     user: User = Depends(shortlink_user), db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    cfg = get_settings(db)
    days = days if days in (7, 30, 90, 365) else 30
    return render(request, "shortlink.html", user, link=link, url=sl.short_url(cfg, link), cfg=cfg,
                  stats=sl.stats(db, link, days, bots == "1"), days=days, bots=bots == "1",
                  state=sl.usable(link), redirect_codes=sl.REDIRECT_CODES, errors=sl.QR_ERRORS,
                  local_input=_local_input)


@app.post("/shortlinks/{link_id}", dependencies=[Depends(check_csrf)])
async def shortlink_update(request: Request, link_id: int, user: User = Depends(shortlink_user),
                           db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    form = await request.form()
    error = _apply(link, db, form)
    if error:
        db.rollback()
        flash(request, error, "error")
    else:
        db.commit()
        flash(request, "Kurzlink gespeichert.")
    return redirect(f"/shortlinks/{link.id}")


@app.post("/shortlinks/{link_id}/toggle", dependencies=[Depends(check_csrf)])
def shortlink_toggle(request: Request, link_id: int, next: str = Form("/shortlinks"),
                     user: User = Depends(shortlink_user), db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    link.active = not link.active
    db.commit()
    flash(request, f"Kurzlink /{link.code} " + ("aktiviert." if link.active else "deaktiviert."))
    return redirect(safe_next(next))


@app.post("/shortlinks/{link_id}/reset", dependencies=[Depends(check_csrf)])
def shortlink_reset(request: Request, link_id: int, user: User = Depends(shortlink_user),
                    db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    for visit in db.scalars(select(ShortVisit).where(ShortVisit.link_id == link.id)):
        db.delete(visit)
    link.visit_count, link.bot_count, link.last_visit_at = 0, 0, None
    db.commit()
    flash(request, "Statistik zurückgesetzt.")
    return redirect(f"/shortlinks/{link.id}")


@app.post("/shortlinks/{link_id}/delete", dependencies=[Depends(check_csrf)])
def shortlink_delete(request: Request, link_id: int, user: User = Depends(shortlink_user),
                     db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    db.delete(link)
    db.commit()
    flash(request, f"Kurzlink /{link.code} gelöscht. Die Adresse ist ab sofort wieder frei.")
    return redirect("/shortlinks")


@app.get("/shortlinks/{link_id}/qr.{fmt}")
def shortlink_qr(link_id: int, fmt: str, size: int = 10, dark: str = "#000000", light: str = "#ffffff",
                 error: str = "m", border: int = 2, download: str = "", user: User = Depends(shortlink_user),
                 db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    data, media = sl.qr_image(sl.short_url(get_settings(db), link), opts)
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="qr-{link.code}.{opts["fmt"]}"'
    return Response(data, media_type=media, headers=headers)


@app.get("/shortlinks/{link_id}/visits.csv")
def shortlink_visits_csv(link_id: int, user: User = Depends(shortlink_user), db: Session = Depends(get_db)):
    link = _own_link(db, link_id, user)
    buf = io.StringIO()
    writer = csvsafe.writer(buf, delimiter=";")
    writer.writerow(["Zeitpunkt", "Herkunft", "Browser", "Betriebssystem", "Gerät", "Bot"])
    for v in db.scalars(select(ShortVisit).where(ShortVisit.link_id == link.id).order_by(ShortVisit.at)):
        writer.writerow([to_local(v.at).strftime("%d.%m.%Y %H:%M:%S"), v.referer_host, v.browser, v.os,
                         v.device, "ja" if v.bot else "nein"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="aufrufe-{link.code}.csv"'})


@app.post("/shortlinks-settings", dependencies=[Depends(check_csrf)])
def shortlinks_settings(request: Request, short_domain: str = Form(""), short_fallback_url: str = Form(""),
                        short_code_length: str = Form("6"), user: User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    domain = short_domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    fallback = sl.clean_url(short_fallback_url) if short_fallback_url.strip() else ""
    if fallback is None:
        flash(request, "Die Adresse für unbekannte Kurzlinks ist ungültig.", "error")
        return redirect("/shortlinks#einstellungen")
    cfg = get_settings(db)
    if domain != cfg.get("short_domain", ""):
        from . import modhosts
        if domain and (not proxy.DOMAIN_RE.match(domain) or domain in proxy.hosts().values()
                       or domain in modhosts.host_map(cfg)):
            flash(request, "Die Kurz-Domain ist ungültig oder wird schon für Konferenz, Portal oder ein Modul verwendet.", "error")
            return redirect("/shortlinks#einstellungen")
        try:
            if proxy.available():
                proxy.write({**cfg, "short_domain": domain})
        except (ValueError, OSError) as exc:
            flash(request, f"Proxy-Konfiguration nicht geschrieben: {exc}", "error")
            return redirect("/shortlinks#einstellungen")
    set_setting(db, "short_domain", domain)
    set_setting(db, "short_fallback_url", fallback or "")
    length = short_code_length if short_code_length.isdigit() and 4 <= int(short_code_length) <= 20 else "6"
    set_setting(db, "short_code_length", length)
    db.commit()
    flash(request, "Einstellungen gespeichert." + (
        f" Die Kurz-Domain {domain} braucht einen DNS-Eintrag auf diesen Server; das Zertifikat holt der "
        "Proxy automatisch." if domain else ""))
    return redirect("/shortlinks#einstellungen")


# --- Öffentliche Weiterleitung -------------------------------------------------

def _fallback(db: Session) -> str:
    return get_settings(db).get("short_fallback_url") or ""


@app.get("/s/")
@app.get("/s")
def short_root(db: Session = Depends(get_db)):
    return RedirectResponse(_fallback(db) or settings.portal_base_url + "/", status_code=302)


@app.api_route("/s/{code}", methods=["GET", "HEAD"])
def short_redirect(request: Request, code: str, db: Session = Depends(get_db)):
    link = db.scalar(select(ShortLink).where(ShortLink.code == sl.normalize_code(code.rstrip("/"))))
    reason = "unbekannt" if link is None else sl.usable(link)
    if reason:
        fallback = _fallback(db)
        if fallback:
            return RedirectResponse(fallback, status_code=302)
        page = render(request, "short_invalid.html", None, reason=reason)
        page.status_code = 404
        return page
    if request.method == "GET":
        rate_limit(request, "short", limit=600, window=60)
        sl.record_visit(db, link, request.headers.get("user-agent", ""), request.headers.get("referer", ""))
        db.commit()
    response = RedirectResponse(sl.target_for(link, request.url.query), status_code=link.redirect_code or 302)
    response.headers["Cache-Control"] = "private, max-age=0" if link.redirect_code in (302, 307) else "max-age=3600"
    response.headers["X-Robots-Tag"] = "noindex"
    return response


def quick_link_url(target: str, title: str, next_url: str) -> str:
    """Adresse des Kurzlink-Formulars, vorausgefüllt (z. B. von Formularen oder Meetings aus)."""
    return "/shortlinks?" + urlencode({"new": target, "title": title, "next": next_url}) + "#neu"
