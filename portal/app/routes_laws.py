"""Rechtstexte: öffentliche Ansicht unter /recht, Pflege unter /laws (Recht „laws“)."""

import re
from datetime import date

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import laws as lx, links, sessions
from .config import settings
from .db import LawLevel, LawSection, LawText, LawVersion, User, get_settings, set_setting
from .main import app, check_csrf, flash, get_db, redirect, render, require, session_user
from .main import embed_enabled as main_embed_enabled

law_user = require("laws")
MAX_VERSIONS = 50
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ORIGIN_RE = re.compile(r"^https?://[a-z0-9.-]+(:\d+)?$|^https?://\*\.[a-z0-9.-]+$", re.I)


def _editor(user: User | None) -> bool:
    return bool(user and user.can("laws"))


def _visible_law(db: Session, slug: str, user: User | None) -> LawText:
    law = db.scalar(select(LawText).where(LawText.slug == slug))
    if law is None or (not law.published and not _editor(user)):
        raise HTTPException(404, "Dieser Rechtstext ist nicht (mehr) veröffentlicht.")
    return law


def _fmt_date(value: str) -> str:
    try:
        return date.fromisoformat(value).strftime("%d.%m.%Y") if value else ""
    except ValueError:
        return value


def _common(db: Session, user: User | None) -> dict:
    return {"kinds": lx.LEVEL_KINDS, "doc_types": lx.DOC_TYPES, "editor": _editor(user), "fmt_date": _fmt_date,
            "level_path": lx.level_path, "level_ids": lx.descendant_ids}


# --- Öffentlich ----------------------------------------------------------------
#
# Jede öffentliche Seite gibt es zweimal: unter /recht mit Portal-Rahmen und unter /recht-embed ohne Menüs zum
# Einbinden per <iframe> in die eigene Homepage. Eingebettet wird immer die öffentliche Sicht gezeigt.

EMBED = "/recht-embed"


def embed_enabled(db: Session) -> bool:
    return main_embed_enabled(db, EMBED)


def _ctx(db: Session, request: Request, embed: bool) -> tuple[User | None, dict]:
    """(Person, gemeinsame Angaben). Eingebettet: immer öffentliche Sicht und schlanker Rahmen."""
    if embed and not embed_enabled(db):
        raise HTTPException(404, "Das Einbinden der Rechtstexte ist auf diesem Server abgeschaltet.")
    user = None if embed else session_user(request, db)
    return user, {**_common(db, user), "layout": "base_embed.html" if embed else "base.html",
                  "R": EMBED if embed else "/recht", "embed": embed}


def _cookieless(request: Request, response):
    """Wer ohne Sitzung kommt (Bürger:innen, eingebettete Rahmen), bekommt auch kein Cookie gesetzt."""
    if sessions.COOKIE_NAME not in request.cookies:
        request.session.clear()
    return response


def _index(request: Request, db: Session, embed: bool):
    user, ctx = _ctx(db, request, embed)
    editor = ctx["editor"]
    q = select(LawText).order_by(LawText.title)
    if not editor:
        q = q.where(LawText.published.is_(True))
    all_laws = list(db.scalars(q))
    by_level: dict[int | None, list[LawText]] = {}
    for law in all_laws:
        by_level.setdefault(law.level_id, []).append(law)
    recent = sorted((x for x in all_laws if x.published), key=lambda x: x.updated_at, reverse=True)[:6]
    return _cookieless(request, render(request, "recht.html", user, roots=lx.level_tree(db), by_level=by_level,
                  counts=lx.law_counts(db, published_only=not editor), recent=[] if embed else recent,
                  total=len(all_laws), **ctx))


def _search(request: Request, db: Session, embed: bool, q: str, ebene: int | None, gesetz: str):
    user, ctx = _ctx(db, request, embed)
    level = db.get(LawLevel, ebene) if ebene else None
    law = db.scalar(select(LawText).where(LawText.slug == gesetz)) if gesetz else None
    if law is not None and not law.published and not ctx["editor"]:
        law = None
    found_laws, hits = lx.search(db, q, published_only=not ctx["editor"], level=level, law=law)
    grouped: dict[int, dict] = {}
    for section, snip in hits:
        grouped.setdefault(section.law_id, {"law": section.law, "hits": []})["hits"].append((section, snip))
    return _cookieless(request, render(request, "recht_search.html", user, q=q, level=level, law=law, found_laws=found_laws,
                  grouped=list(grouped.values()), hit_count=len(hits), words=lx.terms(q),
                  level_options=lx.level_options(db), **ctx))


def _level(request: Request, db: Session, embed: bool, level_id: int):
    user, ctx = _ctx(db, request, embed)
    level = db.get(LawLevel, level_id)
    if level is None:
        raise HTTPException(404, "Ebene nicht gefunden.")
    q = select(LawText).where(LawText.level_id.in_(lx.descendant_ids(level))).order_by(LawText.title)
    if not ctx["editor"]:
        q = q.where(LawText.published.is_(True))
    by_level: dict[int | None, list[LawText]] = {}
    for law in db.scalars(q):
        by_level.setdefault(law.level_id, []).append(law)
    return _cookieless(request, render(request, "recht.html", user, roots=[level], by_level=by_level, focus=level,
                  counts=lx.law_counts(db, published_only=not ctx["editor"]), recent=[],
                  total=sum(len(v) for v in by_level.values()), **ctx))


def _markdown(request: Request, db: Session, embed: bool, slug: str):
    user, ctx = _ctx(db, request, embed)
    law = _visible_law(db, slug, user)
    text = (f"# {law.title}\n\n" if not law.body_md.lstrip().startswith("# ") else "") + law.body_md
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{law.slug}.md"'})


def _law_page(request: Request, db: Session, embed: bool, slug: str, anchor: str | None):
    user, ctx = _ctx(db, request, embed)
    law = _visible_law(db, slug, user)
    roots, flat = lx.tree(law)
    current = None
    if anchor is not None:
        current = next((v for v in flat if v.section.anchor == anchor), None)
        if current is None:
            raise HTTPException(404, "Diesen Abschnitt gibt es in diesem Rechtstext nicht.")
    idx = flat.index(current) if current else -1
    return _cookieless(request, render(request, "recht_law.html", user, law=law, roots=roots, flat=flat, current=current,
                  prev=flat[idx - 1] if current and idx > 0 else None,
                  next=flat[idx + 1] if current and idx + 1 < len(flat) else None,
                  path=lx.level_path(law.level), q=request.query_params.get("q", ""), **ctx))


for _prefix, _embed in (("/recht", False), (EMBED, True)):
    def _register(prefix: str, embed: bool):
        @app.get(prefix, name=f"recht_index{'_embed' if embed else ''}")
        def index(request: Request, db: Session = Depends(get_db)):
            return _index(request, db, embed)

        @app.get(prefix + "/suche", name=f"recht_search{'_embed' if embed else ''}")
        def search(request: Request, q: str = "", ebene: int | None = None, gesetz: str = "",
                   db: Session = Depends(get_db)):
            return _search(request, db, embed, q, ebene, gesetz)

        @app.get(prefix + "/ebene/{level_id}", name=f"recht_level{'_embed' if embed else ''}")
        def level(request: Request, level_id: int, db: Session = Depends(get_db)):
            return _level(request, db, embed, level_id)

        @app.get(prefix + "/{slug}.md", name=f"recht_markdown{'_embed' if embed else ''}")
        def markdown(request: Request, slug: str, db: Session = Depends(get_db)):
            return _markdown(request, db, embed, slug)

        @app.get(prefix + "/{slug}", name=f"recht_law{'_embed' if embed else ''}")
        def law(request: Request, slug: str, db: Session = Depends(get_db)):
            return _law_page(request, db, embed, slug, None)

        @app.get(prefix + "/{slug}/{anchor}", name=f"recht_section{'_embed' if embed else ''}")
        def section(request: Request, slug: str, anchor: str, db: Session = Depends(get_db)):
            return _law_page(request, db, embed, slug, anchor)

    _register(_prefix, _embed)


# --- Pflege: Rechtstexte -----------------------------------------------------

@app.get("/laws")
def laws_list(request: Request, level: int | None = None, user: User = Depends(law_user),
              db: Session = Depends(get_db)):
    q = select(LawText).order_by(LawText.title)
    selected = db.get(LawLevel, level) if level else None
    if selected is not None:
        q = q.where(LawText.level_id.in_(lx.descendant_ids(selected)))
    items = list(db.scalars(q))
    sections = dict(db.execute(select(LawSection.law_id, func.count(LawSection.id))
                               .where(LawSection.kind == "norm").group_by(LawSection.law_id)).all())
    return render(request, "laws.html", user, items=items, norms=sections, selected=selected,
                  level_options=lx.level_options(db), counts=lx.law_counts(db, published_only=False),
                  roots=lx.level_tree(db), **_common(db, user))


def _form_page(request: Request, db: Session, user: User, law: LawText | None, values: dict | None = None):
    return render(request, "law_edit.html", user, law=law, v=values or {}, level_options=lx.level_options(db),
                  **_common(db, user))


@app.get("/laws/new")
def law_new(request: Request, level: int | None = None, user: User = Depends(law_user),
            db: Session = Depends(get_db)):
    return _form_page(request, db, user, None, {"level_id": level, "doc_type": "satzung"})


async def _read_md(file: UploadFile | None, fallback: str) -> tuple[str, str | None]:
    """(Markdown, Fehlermeldung). Eine hochgeladene Datei hat Vorrang vor dem Textfeld."""
    if file is not None and file.filename:
        data = await file.read(lx.MAX_SIZE + 1)
        if len(data) > lx.MAX_SIZE:
            return fallback, "Die Datei ist größer als 2 MB."
        return lx.decode_upload(data), None
    if len(fallback.encode()) > lx.MAX_SIZE:
        return fallback, "Der Text ist größer als 2 MB."
    return fallback, None


def _apply(db: Session, law: LawText, data, md: str, user: User) -> str | None:
    """Felder übernehmen; gibt eine Fehlermeldung zurück oder None."""
    parsed = lx.parse(md)
    title = " ".join((data.get("title") or "").split())[:400] or parsed.title
    if not title:
        return "Bitte einen Titel angeben (oder den Text mit „# Titel“ beginnen)."
    level_id = data.get("level_id")
    level = db.get(LawLevel, int(level_id)) if level_id and str(level_id).isdigit() else None
    for key in ("issued_on", "valid_from", "valid_until"):
        value = (data.get(key) or "").strip()
        if value and not DATE_RE.match(value):
            return "Bitte Datumsangaben im Format TT.MM.JJJJ wählen."
    if law.id and law.body_md and law.body_md != md:
        db.add(LawVersion(law_id=law.id, saved_by=law.editor.name if law.editor else "", body_md=law.body_md,
                          version_note=law.version_note, saved_at=law.updated_at))
        old = db.scalars(select(LawVersion).where(LawVersion.law_id == law.id)
                         .order_by(LawVersion.saved_at.desc()).offset(MAX_VERSIONS - 1)).all()
        for v in old:
            db.delete(v)
    law.title = title
    law.short_title = " ".join((data.get("short_title") or "").split())[:80]
    law.level_id = level.id if level else None
    law.doc_type = data.get("doc_type") if data.get("doc_type") in lx.DOC_TYPES else "sonstiges"
    law.version_note = " ".join((data.get("version_note") or "").split())[:255]
    law.issued_on = (data.get("issued_on") or "").strip()
    law.valid_from = (data.get("valid_from") or "").strip()
    law.valid_until = (data.get("valid_until") or "").strip()
    law.published = data.get("published") == "1"
    law.body_md = md
    law.updated_by = user.id
    wanted = (data.get("slug") or "").strip() or law.slug or law.short_title or title
    law.slug = lx.unique_slug(db, wanted, law.id)
    return None


@app.post("/laws/new", dependencies=[Depends(check_csrf)])
async def law_create(request: Request, file: UploadFile | None = File(None), user: User = Depends(law_user),
                     db: Session = Depends(get_db)):
    data = await request.form()
    md, error = await _read_md(file, data.get("body_md", ""))
    law = LawText(created_by=user.id)
    error = error or _apply(db, law, data, md, user)
    if error:
        flash(request, error, "error")
        return _form_page(request, db, user, None, {**dict(data), "body_md": md})
    db.add(law)
    db.flush()
    parsed = lx.store(db, law)
    db.commit()
    flash(request, f"„{law.title}“ gespeichert: {parsed.norms} Paragrafen/Artikel in {parsed.groups} Gliederungsebenen erkannt."
          + ("" if law.published else " Der Text ist noch nicht veröffentlicht."))
    return redirect(f"/laws/{law.id}/edit")


def _law(db: Session, law_id: int) -> LawText:
    law = db.get(LawText, law_id)
    if law is None:
        raise HTTPException(404, "Rechtstext nicht gefunden.")
    return law


@app.get("/laws/{law_id}/edit")
def law_edit(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    values = {k: getattr(law, k) for k in ("title", "short_title", "slug", "level_id", "doc_type", "version_note",
                                           "issued_on", "valid_from", "valid_until", "body_md")}
    values["published"] = "1" if law.published else ""
    return _form_page(request, db, user, law, values)


@app.post("/laws/{law_id}/edit", dependencies=[Depends(check_csrf)])
async def law_update(request: Request, law_id: int, file: UploadFile | None = File(None),
                     user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    data = await request.form()
    md, error = await _read_md(file, data.get("body_md", ""))
    error = error or _apply(db, law, data, md, user)
    if error:
        db.rollback()
        flash(request, error, "error")
        return _form_page(request, db, user, law, {**dict(data), "body_md": md})
    parsed = lx.store(db, law)
    db.commit()
    flash(request, f"Gespeichert: {parsed.norms} Paragrafen/Artikel, {parsed.groups} Gliederungsebenen.")
    return redirect(f"/laws/{law.id}/edit")


@app.post("/laws/preview", dependencies=[Depends(check_csrf)])
async def law_preview(request: Request, file: UploadFile | None = File(None), user: User = Depends(law_user)):
    data = await request.form()
    md, error = await _read_md(file, data.get("body_md", ""))
    if error:
        return JSONResponse({"ok": False, "error": error})
    parsed = lx.parse(md)
    return JSONResponse({"ok": True, "title": parsed.title, "norms": parsed.norms, "groups": parsed.groups,
                         "body_md": md if file is not None and file.filename else None,
                         "toc": [{"depth": n.depth, "kind": n.kind, "label": n.label, "anchor": n.anchor,
                                  "chars": len(n.plain)} for n in parsed.nodes]})


@app.post("/laws/{law_id}/publish", dependencies=[Depends(check_csrf)])
def law_publish(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    law.published = not law.published
    law.updated_by = user.id
    db.commit()
    flash(request, f"„{law.title}“ ist jetzt " + ("öffentlich sichtbar." if law.published else "nicht mehr öffentlich."))
    return redirect(request.headers.get("referer") or "/laws")


@app.post("/laws/{law_id}/delete", dependencies=[Depends(check_csrf)])
def law_delete(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    title = law.title
    db.delete(law)
    db.commit()
    flash(request, f"„{title}“ wurde gelöscht.")
    return redirect("/laws")


@app.get("/laws/{law_id}/versions/{version_id}")
def law_version(request: Request, law_id: int, version_id: int, user: User = Depends(law_user),
                db: Session = Depends(get_db)):
    version = db.get(LawVersion, version_id)
    if version is None or version.law_id != law_id:
        raise HTTPException(404, "Fassung nicht gefunden.")
    return Response(version.body_md, media_type="text/plain; charset=utf-8")


@app.post("/laws/{law_id}/versions/{version_id}/restore", dependencies=[Depends(check_csrf)])
def law_version_restore(request: Request, law_id: int, version_id: int, user: User = Depends(law_user),
                        db: Session = Depends(get_db)):
    law = _law(db, law_id)
    version = db.get(LawVersion, version_id)
    if version is None or version.law_id != law_id:
        raise HTTPException(404, "Fassung nicht gefunden.")
    data = {"title": law.title, "short_title": law.short_title, "slug": law.slug, "level_id": str(law.level_id or ""),
            "doc_type": law.doc_type, "version_note": version.version_note, "issued_on": law.issued_on,
            "valid_from": law.valid_from, "valid_until": law.valid_until, "published": "1" if law.published else ""}
    _apply(db, law, data, version.body_md, user)
    lx.store(db, law)
    db.commit()
    flash(request, f"Die Fassung vom {version.saved_at:%d.%m.%Y} wurde wiederhergestellt; der bisherige Stand liegt "
                   "jetzt in der Versionsliste.")
    return redirect(f"/laws/{law.id}/edit")


@app.get("/laws/upload")
def laws_upload_form(request: Request, level: int | None = None, user: User = Depends(law_user),
                     db: Session = Depends(get_db)):
    return render(request, "law_upload.html", user, level_options=lx.level_options(db), level_id=level,
                  **_common(db, user))


@app.post("/laws/upload", dependencies=[Depends(check_csrf)])
async def laws_upload(request: Request, files: list[UploadFile] = File(...), level_id: str = Form(""),
                      doc_type: str = Form("satzung"), published: str = Form(""), user: User = Depends(law_user),
                      db: Session = Depends(get_db)):
    created, problems = [], []
    for upload in files[:50]:
        if not upload.filename:
            continue
        data = await upload.read(lx.MAX_SIZE + 1)
        if len(data) > lx.MAX_SIZE:
            problems.append(f"{upload.filename}: größer als 2 MB")
            continue
        md = lx.decode_upload(data)
        if not md.strip():
            problems.append(f"{upload.filename}: Datei ist leer")
            continue
        parsed = lx.parse(md)
        stem = re.sub(r"\.(md|markdown|txt)$", "", upload.filename, flags=re.I)
        law = LawText(created_by=user.id)
        error = _apply(db, law, {"title": parsed.title or stem.replace("_", " "), "level_id": level_id,
                                 "doc_type": doc_type, "published": published, "slug": stem}, md, user)
        if error:
            problems.append(f"{upload.filename}: {error}")
            continue
        db.add(law)
        db.flush()
        lx.store(db, law)
        created.append(f"{law.title} ({parsed.norms} §§/Art.)")
    db.commit()
    if created:
        flash(request, f"{len(created)} Rechtstext(e) übernommen: " + "; ".join(created))
    if problems:
        flash(request, "Nicht übernommen: " + "; ".join(problems), "error")
    return redirect("/laws")


# --- Pflege: Öffentlicher Link und Einbinden --------------------------------

@app.get("/laws/embed")
def laws_embed(request: Request, user: User = Depends(law_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    laws = list(db.scalars(select(LawText).where(LawText.published.is_(True)).order_by(LawText.title)))
    return render(request, "law_embed.html", user, enabled=cfg.get("laws_embed", "1") == "1",
                  origins=cfg.get("laws_embed_origins", ""), base_url=links.base("laws"),
                  level_options=lx.level_options(db), laws=laws, **_common(db, user))


@app.post("/laws/embed", dependencies=[Depends(check_csrf)])
def laws_embed_save(request: Request, enabled: str = Form(""), origins: str = Form(""), user: User = Depends(law_user),
                    db: Session = Depends(get_db)):
    items = [o.strip().rstrip("/") for o in re.split(r"[\s,;]+", origins) if o.strip()]
    bad = [o for o in items if not ORIGIN_RE.match(o)]
    if bad:
        flash(request, "Ungültige Adresse(n): " + ", ".join(bad) + " – bitte in der Form https://www.example.de "
                       "angeben (ohne Pfad).", "error")
        return redirect("/laws/embed")
    set_setting(db, "laws_embed", "1" if enabled == "1" else "0")
    set_setting(db, "laws_embed_origins", " ".join(items))
    db.commit()
    flash(request, "Einstellungen zum Einbinden gespeichert.")
    return redirect("/laws/embed")


# --- Pflege: Ebenen ------------------------------------------------------------

@app.get("/laws/levels")
def law_levels(request: Request, user: User = Depends(law_user), db: Session = Depends(get_db)):
    return render(request, "law_levels.html", user, roots=lx.level_tree(db), options=lx.level_options(db),
                  counts=lx.law_counts(db, published_only=False), **_common(db, user))


def _level_fields(db: Session, level: LawLevel, name: str, kind: str, parent_id: str, description: str) -> str | None:
    name = " ".join(name.split())[:200]
    if not name:
        return "Bitte einen Namen angeben."
    parent = db.get(LawLevel, int(parent_id)) if parent_id.isdigit() else None
    if parent is not None and level.id and parent.id in lx.descendant_ids(level):
        return "Eine Ebene kann nicht unter sich selbst oder ihre Unterebenen verschoben werden."
    if parent is not level.parent or level.id is None:
        siblings = parent.children if parent else lx.level_tree(db)
        level.position = max((s.position for s in siblings if s is not level), default=-1) + 1
    level.name, level.parent = name, parent
    level.kind = kind if kind in lx.LEVEL_KINDS else "sonstige"
    level.description = description.strip()[:2000]
    return None


@app.post("/laws/levels", dependencies=[Depends(check_csrf)])
def law_level_add(request: Request, name: str = Form(""), kind: str = Form("sonstige"), parent_id: str = Form(""),
                  description: str = Form(""), user: User = Depends(law_user), db: Session = Depends(get_db)):
    level = LawLevel()
    error = _level_fields(db, level, name, kind, parent_id, description)
    if error:
        flash(request, error, "error")
        return redirect("/laws/levels")
    db.add(level)
    db.commit()
    flash(request, f"Ebene „{level.name}“ angelegt.")
    return redirect(f"/laws/levels#ebene-{level.id}")


@app.post("/laws/levels/{level_id}", dependencies=[Depends(check_csrf)])
def law_level_save(request: Request, level_id: int, name: str = Form(""), kind: str = Form("sonstige"),
                   parent_id: str = Form(""), description: str = Form(""), user: User = Depends(law_user),
                   db: Session = Depends(get_db)):
    level = db.get(LawLevel, level_id)
    if level is None:
        raise HTTPException(404, "Ebene nicht gefunden.")
    error = _level_fields(db, level, name, kind, parent_id, description)
    if error:
        db.rollback()
        flash(request, error, "error")
    else:
        db.commit()
        flash(request, f"Ebene „{level.name}“ gespeichert.")
    return redirect(f"/laws/levels#ebene-{level_id}")


@app.post("/laws/levels/{level_id}/move", dependencies=[Depends(check_csrf)])
def law_level_move(request: Request, level_id: int, direction: str = Form("up"), user: User = Depends(law_user),
                   db: Session = Depends(get_db)):
    level = db.get(LawLevel, level_id)
    if level is None:
        raise HTTPException(404, "Ebene nicht gefunden.")
    siblings = list(level.parent.children if level.parent else lx.level_tree(db))
    i = siblings.index(level)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(siblings):
        siblings[i], siblings[j] = siblings[j], siblings[i]
        for pos, s in enumerate(siblings):
            s.position = pos
        db.commit()
    return redirect(f"/laws/levels#ebene-{level_id}")


@app.post("/laws/levels/{level_id}/delete", dependencies=[Depends(check_csrf)])
def law_level_delete(request: Request, level_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    level = db.get(LawLevel, level_id)
    if level is None:
        raise HTTPException(404, "Ebene nicht gefunden.")
    ids = lx.descendant_ids(level)
    count = db.scalar(select(func.count(LawText.id)).where(LawText.level_id.in_(ids)))
    if count:
        flash(request, f"„{level.name}“ enthält noch {count} Rechtstext(e) (auch in Unterebenen). Bitte diese zuerst "
                       "einer anderen Ebene zuordnen oder löschen.", "error")
        return redirect(f"/laws/levels#ebene-{level_id}")
    name = level.name
    db.delete(level)
    db.commit()
    flash(request, f"Ebene „{name}“" + (" mit allen Unterebenen" if len(ids) > 1 else "") + " gelöscht.")
    return redirect("/laws/levels")
