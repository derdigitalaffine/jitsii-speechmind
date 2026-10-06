"""Rechtstexte: öffentliche Ansicht unter /recht, Pflege unter /laws (Recht „laws“)."""

import re
from datetime import date

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import law_io, laws as lx, links, sessions
from .db import Form as FormModel
from .db import (
    LawAttachment, LawLevel, LawSection, LawText, LawVersion, User, get_settings, set_setting,
)
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
            "level_path": lx.level_path, "level_ids": lx.descendant_ids, "expired": lx.expired}


def related_forms(db: Session, law: LawText) -> list[FormModel]:
    """Online-Anträge im Katalog, die diesen Text als Rechtsgrundlage nennen."""
    out = []
    import json
    rows = db.scalars(select(FormModel).where(FormModel.kind == "application", FormModel.app_catalog.is_(True),
                                              FormModel.active.is_(True), FormModel.public_token.is_not(None),
                                              FormModel.legal_json.like("%law_id%"))).all()
    for form in rows:
        try:
            refs = json.loads(form.legal_json or "[]")
        except ValueError:
            continue
        if any(isinstance(r, dict) and r.get("law_id") == law.id for r in refs):
            out.append(form)
    return out


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
    archived = [law for law in all_laws if lx.expired(law)]
    for law in all_laws:
        if not lx.expired(law):
            by_level.setdefault(law.level_id, []).append(law)
    recent = sorted((x for x in all_laws if x.published and not lx.expired(x)), key=lambda x: x.updated_at, reverse=True)[:6]
    return _cookieless(request, render(request, "recht.html", user, roots=lx.level_tree(db), by_level=by_level,
                  counts=lx.law_counts(db, published_only=not editor), recent=[] if embed else recent,
                  total=len(all_laws), archived=archived, **ctx))


def _search(request: Request, db: Session, embed: bool, q: str, ebene: int | None, gesetz: str, art: str = "",
            alle: str = ""):
    user, ctx = _ctx(db, request, embed)
    level = db.get(LawLevel, ebene) if ebene else None
    law = db.scalar(select(LawText).where(LawText.slug == gesetz)) if gesetz else None
    if law is not None and not law.published and not ctx["editor"]:
        law = None
    opts = {"published_only": not ctx["editor"], "level": level, "law": law, "doc_type": art,
            "in_force_only": alle != "1" and law is None}
    found_laws, hits = lx.search(db, q, **opts)
    corrected = ""
    if q and not hits and not found_laws:
        corrected = lx.did_you_mean(db, q)
        if corrected:   # gleich mit der Korrektur suchen und das anzeigen
            found_laws, hits = lx.search(db, corrected, **opts)
    grouped: dict[int, dict] = {}
    for section, snip in hits:
        grouped.setdefault(section.law_id, {"law": section.law, "hits": []})["hits"].append((section, snip))
    return _cookieless(request, render(request, "recht_search.html", user, q=q, level=level, law=law, found_laws=found_laws,
                  grouped=list(grouped.values()), hit_count=len(hits), words=lx.terms(corrected or q),
                  corrected=corrected, art=art, alle=alle, level_options=lx.level_options(db), **ctx))


def _suggest(request: Request, db: Session, embed: bool, q: str):
    user, ctx = _ctx(db, request, embed)
    from .main import rate_limit
    rate_limit(request, "recht-suggest", limit=300, window=60)
    items = lx.quick(db, q, published_only=not ctx["editor"])
    R = ctx["R"]
    return JSONResponse([{"label": i["label"], "url": f"{R}/{i['slug']}" + (f"/{i['anchor']}" if i["anchor"] else "")}
                         for i in items], headers={"Cache-Control": "no-store"})


def _level(request: Request, db: Session, embed: bool, level_id: int):
    user, ctx = _ctx(db, request, embed)
    level = db.get(LawLevel, level_id)
    if level is None:
        raise HTTPException(404, "Ebene nicht gefunden.")
    q = select(LawText).where(LawText.level_id.in_(lx.descendant_ids(level))).order_by(LawText.title)
    if not ctx["editor"]:
        q = q.where(LawText.published.is_(True))
    by_level: dict[int | None, list[LawText]] = {}
    archived = []
    for law in db.scalars(q):
        if lx.expired(law):
            archived.append(law)
        else:
            by_level.setdefault(law.level_id, []).append(law)
    return _cookieless(request, render(request, "recht.html", user, roots=[level], by_level=by_level, focus=level,
                  counts=lx.law_counts(db, published_only=not ctx["editor"]), recent=[], archived=archived,
                  total=sum(len(v) for v in by_level.values()), **ctx))


def _markdown(request: Request, db: Session, embed: bool, slug: str):
    user, ctx = _ctx(db, request, embed)
    law = _visible_law(db, slug, user)
    text = (f"# {law.title}\n\n" if not law.body_md.lstrip().startswith("# ") else "") + law.body_md
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{law.slug}.md"'})


def _law_page(request: Request, db: Session, embed: bool, slug: str, anchor: str | None, version: LawVersion | None = None):
    user, ctx = _ctx(db, request, embed)
    law = _visible_law(db, slug, user)
    day = request.query_params.get("am", "")
    if version is None and DATE_RE.match(day):
        found = lx.version_for_date(law, day)
        if found is not None:
            return redirect(f"{ctx['R']}/{law.slug}/fassung/{found.id}" + (f"#{anchor}" if anchor else ""))
    roots, flat = lx.tree_of(version.body_md) if version is not None else lx.tree(law)
    current = None
    if anchor is not None:
        current = next((v for v in flat if v.section.anchor == anchor), None)
        if current is None:
            raise HTTPException(404, "Diesen Abschnitt gibt es in diesem Rechtstext nicht.")
    if request.query_params.get("format") == "json":   # Vorschau für Verweise (Formulare, Querverweise)
        target = current or (flat[0] if flat else None)
        return JSONResponse({"title": law.title, "short_title": law.short_title,
                             "label": target.label if current else (law.short_title or law.title),
                             "html": lx.link_refs(target.section.html, law.slug, set(), ctx["R"]) if target and current else "",
                             "url": f"{ctx['R']}/{law.slug}" + (f"/{current.section.anchor}" if current else "")},
                            headers={"Cache-Control": "no-store"})
    anchors = {v.section.anchor for v in flat}
    idx = flat.index(current) if current else -1
    versions = lx.public_versions(law)
    return _cookieless(request, render(request, "recht_law.html", user, law=law, roots=roots, flat=flat, current=current,
                  prev=flat[idx - 1] if current and idx > 0 else None,
                  next=flat[idx + 1] if current and idx + 1 < len(flat) else None,
                  path=lx.level_path(law.level), q=request.query_params.get("q", ""), version=version,
                  versions=versions, is_expired=lx.expired(law), forms=[] if embed else related_forms(db, law),
                  base=f"{ctx['R']}/{law.slug}" + (f"/fassung/{version.id}" if version else ""),
                  link=lambda v: lx.link_refs(v.section.html, law.slug, anchors, ctx["R"]) if version is None else v.html,
                  **ctx))


def _version(db: Session, law_slug: str, version_id: int, user) -> tuple[LawText, LawVersion]:
    law = _visible_law(db, law_slug, user)
    version = db.get(LawVersion, version_id)
    if version is None or version.law_id != law.id or not (version.public or _editor(user)):
        raise HTTPException(404, "Diese Fassung gibt es nicht.")
    return law, version


def _compare(request: Request, db: Session, embed: bool, slug: str, a: str, b: str):
    from .main import rate_limit
    rate_limit(request, "law-compare", limit=60, window=600)
    user, ctx = _ctx(db, request, embed)
    law = _visible_law(db, slug, user)
    versions = lx.public_versions(law) if not ctx["editor"] else list(law.versions)

    def pick(key: str):
        if key in ("", "aktuell"):
            return None, law.body_md
        v = next((x for x in versions if str(x.id) == key), None)
        if v is None:
            raise HTTPException(404, "Diese Fassung gibt es nicht.")
        return v, v.body_md
    if not a and versions:
        a = str(versions[0].id)
    old_v, old_md = pick(a)
    new_v, new_md = pick(b)
    rows = lx.compare(old_md, new_md)
    changed = [r for r in rows if r["status"] != "same"]
    return _cookieless(request, render(request, "recht_compare.html", user, law=law, rows=rows, changed=changed,
                  old_v=old_v, new_v=new_v, a=a, b=b or "aktuell", versions=versions, **ctx))


for _prefix, _embed in (("/recht", False), (EMBED, True)):
    def _register(prefix: str, embed: bool):
        @app.get(prefix, name=f"recht_index{'_embed' if embed else ''}")
        def index(request: Request, db: Session = Depends(get_db)):
            return _index(request, db, embed)

        @app.get(prefix + "/suche", name=f"recht_search{'_embed' if embed else ''}")
        def search(request: Request, q: str = "", ebene: int | None = None, gesetz: str = "", art: str = "",
                   alle: str = "", db: Session = Depends(get_db)):
            return _search(request, db, embed, q, ebene, gesetz, art, alle)

        @app.get(prefix + "/suche.json", name=f"recht_suggest{'_embed' if embed else ''}")
        def suggest(request: Request, q: str = "", db: Session = Depends(get_db)):
            return _suggest(request, db, embed, q)

        @app.get(prefix + "/ebene/{level_id}", name=f"recht_level{'_embed' if embed else ''}")
        def level(request: Request, level_id: int, db: Session = Depends(get_db)):
            return _level(request, db, embed, level_id)

        @app.get(prefix + "/{slug}.md", name=f"recht_markdown{'_embed' if embed else ''}")
        def markdown(request: Request, slug: str, db: Session = Depends(get_db)):
            return _markdown(request, db, embed, slug)

        @app.get(prefix + "/{slug}", name=f"recht_law{'_embed' if embed else ''}")
        def law(request: Request, slug: str, db: Session = Depends(get_db)):
            return _law_page(request, db, embed, slug, None)

        @app.get(prefix + "/{slug}/vergleich", name=f"recht_compare{'_embed' if embed else ''}")
        def compare(request: Request, slug: str, a: str = "", b: str = "", db: Session = Depends(get_db)):
            return _compare(request, db, embed, slug, a, b)

        @app.get(prefix + "/{slug}/fassung/{version_id:int}", name=f"recht_version{'_embed' if embed else ''}")
        def version(request: Request, slug: str, version_id: int, db: Session = Depends(get_db)):
            user, _ = _ctx(db, request, embed)
            _law_obj, ver = _version(db, slug, version_id, user)
            return _law_page(request, db, embed, slug, None, ver)

        @app.get(prefix + "/{slug}/fassung/{version_id:int}/{anchor}", name=f"recht_version_section{'_embed' if embed else ''}")
        def version_section(request: Request, slug: str, version_id: int, anchor: str, db: Session = Depends(get_db)):
            user, _ = _ctx(db, request, embed)
            _law_obj, ver = _version(db, slug, version_id, user)
            return _law_page(request, db, embed, slug, anchor, ver)

        @app.get(prefix + "/{slug}/anlage/{att_id:int}", name=f"recht_attachment{'_embed' if embed else ''}")
        def attachment(request: Request, slug: str, att_id: int, db: Session = Depends(get_db)):
            user, _ = _ctx(db, request, embed)
            law_obj = _visible_law(db, slug, user)
            att = db.get(LawAttachment, att_id)
            if att is None or att.law_id != law_obj.id or not (law_io.files_dir(law_obj.id) / att.file).is_file():
                raise HTTPException(404, "Diese Anlage gibt es nicht.")
            return FileResponse(law_io.files_dir(law_obj.id) / att.file, media_type="application/pdf",
                                headers={"Content-Disposition": f'inline; filename="{_ascii(att.name)}"',
                                         "X-Content-Type-Options": "nosniff"})

        @app.get(prefix + "/{slug}/{anchor}", name=f"recht_section{'_embed' if embed else ''}")
        def section(request: Request, slug: str, anchor: str, db: Session = Depends(get_db)):
            return _law_page(request, db, embed, slug, anchor)

    _register(_prefix, _embed)


def _ascii(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120] or "Anlage.pdf"


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


MAX_UPLOAD = 25 * 1024 * 1024   # Word/PDF dürfen größer sein; der Text daraus muss unter 2 MB bleiben


async def _read_md(file: UploadFile | None, fallback: str) -> tuple[str, str | None]:
    """(Markdown, Fehlermeldung). Eine hochgeladene Datei (Markdown, Text, Word, PDF) hat Vorrang vor dem Textfeld."""
    if file is not None and file.filename:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            return fallback, "Die Datei ist größer als 25 MB."
        try:
            md = law_io.to_markdown(file.filename, data)
        except law_io.LawImportError as exc:
            return fallback, str(exc)
        if len(md.encode()) > lx.MAX_SIZE:
            return fallback, "Der Text ist größer als 2 MB."
        return md, None
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
        # „Neue Fassung“: der bisherige Stand bleibt mit Geltungszeitraum öffentlich abrufbar; sonst interne Sicherung
        new_version = data.get("new_version") == "1"
        until = (data.get("valid_from") or "").strip() if new_version else ""
        lx.snapshot(db, law, public=new_version, valid_until=until if DATE_RE.match(until) else lx.today_iso())
        old = db.scalars(select(LawVersion).where(LawVersion.law_id == law.id, LawVersion.public.is_(False))
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
    lx.invalidate_refs()
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
    lx.invalidate_refs()
    flash(request, f"Gespeichert: {parsed.norms} Paragrafen/Artikel, {parsed.groups} Gliederungsebenen.")
    return redirect(f"/laws/{law.id}/edit")


@app.post("/laws/preview", dependencies=[Depends(check_csrf)])
async def law_preview(request: Request, file: UploadFile | None = File(None), user: User = Depends(law_user)):
    data = await request.form()
    md, error = await _read_md(file, data.get("body_md", ""))
    if error:
        return JSONResponse({"ok": False, "error": error})
    parsed = lx.parse(md)
    full = data.get("html") == "1"
    return JSONResponse({"ok": True, "title": parsed.title, "norms": parsed.norms, "groups": parsed.groups,
                         "body_md": md if file is not None and file.filename else None,
                         "warnings": lx.check_outline(parsed),
                         "toc": [{"depth": n.depth, "kind": n.kind, "label": n.label, "anchor": n.anchor,
                                  "chars": len(n.plain), **({"html": n.html} if full else {})} for n in parsed.nodes]})


@app.post("/laws/{law_id}/publish", dependencies=[Depends(check_csrf)])
def law_publish(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    law.published = not law.published
    law.updated_by = user.id
    db.commit()
    lx.invalidate_refs()
    flash(request, f"„{law.title}“ ist jetzt " + ("öffentlich sichtbar." if law.published else "nicht mehr öffentlich."))
    from urllib.parse import urlparse
    from .main import safe_next
    ref = urlparse(request.headers.get("referer") or "")
    return redirect(safe_next(ref.path + (f"?{ref.query}" if ref.query else "")) if ref.path else "/laws")


@app.post("/laws/{law_id}/delete", dependencies=[Depends(check_csrf)])
def law_delete(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    title = law.title
    import shutil
    db.delete(law)
    db.commit()
    shutil.rmtree(law_io.files_dir(law_id), ignore_errors=True)
    lx.invalidate_refs()
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
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            problems.append(f"{upload.filename}: größer als 25 MB")
            continue
        try:
            md = law_io.to_markdown(upload.filename, data)
        except law_io.LawImportError as exc:
            problems.append(f"{upload.filename}: {exc}")
            continue
        if len(md.encode()) > lx.MAX_SIZE:
            problems.append(f"{upload.filename}: Text größer als 2 MB")
            continue
        if not md.strip():
            problems.append(f"{upload.filename}: Datei ist leer")
            continue
        parsed = lx.parse(md)
        stem = re.sub(r"\.(md|markdown|txt|docx|pdf)$", "", upload.filename, flags=re.I)
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
    lx.invalidate_refs()
    if created:
        flash(request, f"{len(created)} Rechtstext(e) übernommen: " + "; ".join(created))
    if problems:
        flash(request, "Nicht übernommen: " + "; ".join(problems), "error")
    return redirect("/laws")


# --- Pflege: geplante Fassung, Anlagen, Ex-/Import ---------------------------------------

@app.get("/laws/{law_id}/plan")
def law_plan(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    return render(request, "law_plan.html", user, law=law, body=law.planned_md or law.body_md, **_common(db, user))


@app.post("/laws/{law_id}/plan", dependencies=[Depends(check_csrf)])
async def law_plan_save(request: Request, law_id: int, file: UploadFile | None = File(None), user: User = Depends(law_user),
                        db: Session = Depends(get_db)):
    law = _law(db, law_id)
    data = await request.form()
    if data.get("action") == "delete":
        law.planned_md, law.planned_valid_from, law.planned_note = "", "", ""
        db.commit()
        flash(request, "Die vorbereitete Fassung wurde verworfen.")
        return redirect(f"/laws/{law.id}/edit")
    md, error = await _read_md(file, str(data.get("body_md", "")))
    day = str(data.get("valid_from", "")).strip()
    if not error and not DATE_RE.match(day):
        error = "Bitte das Datum des Inkrafttretens angeben."
    elif not error and day <= lx.today_iso():
        error = "Das Datum muss in der Zukunft liegen – für sofort geltende Änderungen den Text direkt bearbeiten."
    if error:
        flash(request, error, "error")
        return render(request, "law_plan.html", user, law=law, body=md, v=dict(data), **_common(db, user))
    law.planned_md, law.planned_valid_from = md, day
    law.planned_note = " ".join(str(data.get("version_note", "")).split())[:255]
    db.commit()
    flash(request, f"Neue Fassung vorbereitet – sie gilt automatisch ab {_fmt_date(day)}; die bisherige bleibt als frühere Fassung abrufbar.")
    return redirect(f"/laws/{law.id}/edit")


@app.post("/laws/{law_id}/attachments", dependencies=[Depends(check_csrf)])
async def law_attachment_add(request: Request, law_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    data = await request.form()
    n = 0
    for f in data.getlist("files"):
        if not hasattr(f, "read") or not getattr(f, "filename", ""):
            continue
        content = await f.read(law_io.MAX_ATTACHMENT + 1)
        if not content.startswith(b"%PDF") or len(content) > law_io.MAX_ATTACHMENT:
            flash(request, f"„{f.filename}“ übersprungen – nur PDF bis 20 MB.", "error")
            continue
        name = " ".join(str(data.get("name", "")).split())[:255] if len(data.getlist("files")) == 1 and data.get("name") else f.filename
        law_io.add_attachment(law, name, content)
        n += 1
    db.commit()
    if n:
        flash(request, f"{n} Anlage(n) hinzugefügt.")
    return redirect(f"/laws/{law.id}/edit#anlagen")


@app.post("/laws/{law_id}/attachments/{att_id}/delete", dependencies=[Depends(check_csrf)])
def law_attachment_delete(request: Request, law_id: int, att_id: int, user: User = Depends(law_user), db: Session = Depends(get_db)):
    law = _law(db, law_id)
    att = db.get(LawAttachment, att_id)
    if att is not None and att.law_id == law.id:
        (law_io.files_dir(law.id) / att.file).unlink(missing_ok=True)
        db.delete(att)
        db.commit()
        flash(request, "Anlage entfernt.")
    return redirect(f"/laws/{law.id}/edit#anlagen")


@app.get("/laws/export")
def laws_export(level: int | None = None, versions: str = "1", attachments: str = "1", user: User = Depends(law_user),
                db: Session = Depends(get_db)):
    q = select(LawText).order_by(LawText.title)
    selected = db.get(LawLevel, level) if level else None
    if selected is not None:
        q = q.where(LawText.level_id.in_(lx.descendant_ids(selected)))
    body = law_io.export(db, list(db.scalars(q)), versions=versions == "1", attachments=attachments == "1")
    name = lx.slugify(selected.name, 40) if selected else "alle"
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="rechtstexte-{name}-{lx.today_iso()}.json"'})


@app.post("/laws/import", dependencies=[Depends(check_csrf)])
async def laws_import(request: Request, user: User = Depends(law_user), db: Session = Depends(get_db)):
    data = await request.form()
    f = data.get("file")
    try:
        if not hasattr(f, "read"):
            raise law_io.LawImportError("Bitte eine Exportdatei wählen.")
        created, updated = law_io.import_(db, await f.read(500 * 1024 * 1024), user,
                                          update_existing=data.get("update") == "1")
    except law_io.LawImportError as exc:
        db.rollback()
        flash(request, str(exc), "error")
        return redirect("/laws")
    db.commit()
    flash(request, f"Import: {created} neu angelegt, {updated} als neue Fassung aktualisiert. Ebenen wurden bei Bedarf angelegt.")
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
