"""Startseite für Bürger:innen („/“ ohne Anmeldung), Suche über alle öffentlichen Bereiche und die Verwaltung
des öffentlichen Menüs (Verwaltung › Öffentliches Menü)."""

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import public_nav as pn
from .db import BookingPage, Resource, User, get_settings, set_setting
from .main import admin_user, app, check_csrf, enabled_modules, flash, get_db, rate_limit, redirect, render, session_user

MAX_HITS = 8


def _no_cookie(request: Request, response, user):
    """Wie die übrigen öffentlichen Seiten: Wer nicht angemeldet ist, bekommt kein Cookie."""
    if user is None and "jsm_session" not in request.cookies:
        request.session.clear()
    return response


def public_home(request: Request, db: Session):
    cfg = get_settings(db)
    tiles = [i for i in pn.items(enabled_modules()) if i["key"]]
    links = [i for i in pn.items(enabled_modules()) if not i["key"]]
    return _no_cookie(request, render(request, "public_home.html", None, tiles=tiles, links=links,
                                      home_title=cfg.get("public_home_title") or "",
                                      home_text=cfg.get("public_home_text") or "",
                                      contact=cfg.get("public_contact") or ""), None)


def search_all(db: Session, query: str) -> list[dict]:
    """Treffer je Bereich: [{key, label, icon, url, hits: [{title, text, url}]}] – nur sichtbare Bereiche."""
    words = [w for w in query.lower().split() if len(w) >= 2][:6]
    if not words:
        return []
    shown = {i["key"]: i for i in pn.items(enabled_modules()) if i["key"]}

    def match(*parts) -> bool:
        text = " ".join(str(p or "") for p in parts).lower()
        return all(w in text for w in words)

    out = []

    def add(key: str, hits: list[dict]):
        if hits:
            item = shown[key]
            out.append({"key": key, "label": item["label"], "icon": item["icon"], "url": item["url"], "hits": hits[:MAX_HITS],
                        "more": len(hits) > MAX_HITS})
    if "antraege" in shown:
        from . import applications as apps, forms as fm
        add("antraege", [{"title": f.title, "text": (f.app_category or ""), "url": fm.public_link(f) or "/antraege"}
                         for f in apps.catalog(db) if match(f.title, f.description, f.app_category)])
    if "raeume" in shown:
        rows = db.scalars(select(Resource).where(Resource.active.is_(True), Resource.public.is_(True))
                          .order_by(Resource.position, Resource.name)).all()
        add("raeume", [{"title": r.name, "text": r.location or r.category, "url": f"/r/{r.slug}"}
                       for r in rows if match(r.name, r.location, r.description, r.category)])
    if "termine" in shown:
        pages = db.scalars(select(BookingPage).where(BookingPage.listed.is_(True), BookingPage.active.is_(True),
                                                     BookingPage.invite_only.is_(False))).all()
        add("termine", [{"title": p.title, "text": p.location, "url": f"/b/{p.public_token}"}
                        for p in pages if match(p.title, p.description, p.location)])
    if "recht" in shown:
        from . import laws as lx
        laws, sections = lx.search(db, query, published_only=True, limit=MAX_HITS + 1)
        hits = [{"title": law.title, "text": law.short_title, "url": f"/recht/{law.slug}"} for law in laws]
        hits += [{"title": f"{s.number} {s.title}".strip() + f" – {s.law.short_title or s.law.title}", "text": "",
                  "url": f"/recht/{s.law.slug}/{s.anchor}"} for s, _snip in sections]
        add("recht", hits)
    return out


@app.get("/suche")
def public_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    rate_limit(request, "public-search", limit=60, window=300)
    query = " ".join(q.split())[:100]
    user = session_user(request, db)
    groups = search_all(db, query) if query else []
    return _no_cookie(request, render(request, "public_search.html", user, q=query, groups=groups,
                                      total=sum(len(g["hits"]) for g in groups)), user)


# --- Verwaltung ----------------------------------------------------------------------------------

@app.get("/admin/oeffentlich")
def public_nav_admin(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    return render(request, "admin_public_nav.html", user, entries=pn.entries(db, cfg, enabled_modules()),
                  links=pn.config(cfg)["links"], max_links=pn.MAX_LINKS, cfg=cfg)


@app.post("/admin/oeffentlich", dependencies=[Depends(check_csrf)])
async def public_nav_save(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    import json
    data = await request.form()
    order = [k for k in data.getlist("order") if k in pn.ITEMS]
    shown = set(data.getlist("show"))
    links, bad = [], []
    for label, url in zip(data.getlist("link_label"), data.getlist("link_url")):
        if not str(label).strip() and not str(url).strip():
            continue
        cleaned = pn.clean_link(label, url)
        if cleaned is None:
            bad.append(str(label or url)[:40])
        else:
            links.append(cleaned)
    set_setting(db, "public_nav", json.dumps({"order": order, "hidden": [k for k in order if k not in shown],
                                              "links": links[:pn.MAX_LINKS]}, ensure_ascii=False))
    set_setting(db, "public_home", "1" if data.get("public_home") == "1" else "0")
    set_setting(db, "public_home_title", " ".join(str(data.get("public_home_title", "")).split())[:120])
    set_setting(db, "public_home_text", str(data.get("public_home_text", "")).replace("\r\n", "\n").strip()[:2000])
    set_setting(db, "public_contact", str(data.get("public_contact", "")).replace("\r\n", "\n").strip()[:2000])
    db.commit()
    pn.invalidate()
    flash(request, "Öffentliches Menü und Startseite gespeichert.")
    if bad:
        flash(request, "Nicht übernommen (Adresse muss mit https:// oder / beginnen): " + ", ".join(bad), "error")
    return redirect("/admin/oeffentlich")
