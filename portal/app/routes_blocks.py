"""Datenblöcke: zentrale Bibliothek gruppierter Formularfelder (z. B. „Antragsteller:in“, „Hund“)."""

import json
import re

from fastapi import Depends, Form as FormField, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import forms as fm
from .db import Form, FormBlock, User, utcnow
from .main import app, check_csrf, current_user, enabled_modules, flash, get_db, redirect, render, require

blocks_user = require("formblocks")
ICONS = ["fa-cubes", "fa-user", "fa-building", "fa-house", "fa-building-columns", "fa-dog", "fa-car", "fa-id-card",
         "fa-baby", "fa-tree", "fa-truck", "fa-hammer", "fa-store", "fa-calendar-day", "fa-file-contract"]


def _module_on() -> None:
    if "forms" not in enabled_modules():
        raise HTTPException(404, "Der Formularserver ist abgeschaltet.")


def usage(db: Session) -> dict[int, list[Form]]:
    """Welche Formulare nutzen welchen Block (Suche im gespeicherten Aufbau)."""
    out: dict[int, list[Form]] = {}
    for form in db.scalars(select(Form).where(Form.schema_json.like('%"block_id"%'))):
        for item in fm.raw_schema(form):
            if item.get("type") == "block" and isinstance(item.get("block_id"), int):
                lst = out.setdefault(item["block_id"], [])
                if form not in lst:
                    lst.append(form)
    return out


def _block(db: Session, block_id: int) -> FormBlock:
    block = db.get(FormBlock, block_id)
    if block is None:
        raise HTTPException(404, "Datenblock nicht gefunden.")
    return block


@app.get("/forms/blocks")
def blocks_page(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _module_on()
    if not (user.can("forms") or user.can("formblocks")):
        raise HTTPException(403)
    blocks = db.scalars(select(FormBlock).order_by(FormBlock.name)).all()
    items = {b.id: [i for i in json.loads(b.schema_json or "[]") if isinstance(i, dict)] for b in blocks}
    return render(request, "blocks.html", user, blocks=blocks, items=items, usage=usage(db), types=fm.TYPES,
                  can_edit=user.can("formblocks"))


@app.post("/forms/blocks/new", dependencies=[Depends(check_csrf)])
def blocks_new(request: Request, name: str = FormField(""), user: User = Depends(blocks_user), db: Session = Depends(get_db)):
    _module_on()
    block = FormBlock(name=" ".join(name.split())[:200] or "Neuer Datenblock", schema_json="[]")
    db.add(block)
    db.commit()
    return redirect(f"/forms/blocks/{block.id}")


@app.get("/forms/blocks/{block_id:int}")
def block_builder(request: Request, block_id: int, user: User = Depends(blocks_user), db: Session = Depends(get_db)):
    _module_on()
    from .routes_forms import builder_extras
    block = _block(db, block_id)
    extras = builder_extras(db, user)
    extras["blocks"], extras["block_order"] = {}, []   # keine Blöcke in Blöcken
    extras["hidden_types"] = set(fm.HIDDEN_TYPES) | {"pagebreak"}
    return render(request, "block_builder.html", user, block=block, schema=json.loads(block.schema_json or "[]"),
                  subtypes=fm.SUBTYPES, max_file_mb=fm.MAX_FILE_MB, types=fm.TYPES, icons=ICONS,
                  used_in=usage(db).get(block.id, []), **extras)


@app.post("/forms/blocks/{block_id:int}/schema", dependencies=[Depends(check_csrf)])
async def block_save(request: Request, block_id: int, user: User = Depends(blocks_user), db: Session = Depends(get_db)):
    _module_on()
    block = _block(db, block_id)
    data = await request.form()
    block.name = " ".join(str(data.get("title", "")).split())[:200] or block.name
    block.description = str(data.get("description", "")).replace("\r\n", "\n").strip()[:2000]
    icon = str(data.get("icon", ""))
    block.icon = icon if icon in ICONS else block.icon
    items = [i for i in fm.clean_schema(str(data.get("items_json", "[]"))) if i["type"] not in ("block", "pagebreak")]
    # IDs lesbar halten: aus dem Titel, falls neu (bestehende IDs bleiben – sonst gingen Antworten verloren)
    old = {i.get("id") for i in json.loads(block.schema_json or "[]") if isinstance(i, dict)}
    taken = set(old)
    for item in items:
        if item["id"] in old:
            continue
        base = re.sub(r"[^a-z0-9]+", "", item.get("title", "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))[:16] or "feld"
        new, n = base, 2
        while new in taken:
            new, n = f"{base}{n}", n + 1
        mapping = {item["id"]: new}
        for other in items:   # Bedingungen innerhalb des Blocks mitziehen
            for key in ("show_if", "required_if"):
                if other.get(key):
                    other[key]["rules"] = [{**r, "q": mapping.get(r["q"], r["q"])} for r in other[key]["rules"]]
        item["id"] = new
        taken.add(new)
    block.schema_json = json.dumps(items, ensure_ascii=False)
    block.updated_at = utcnow()
    db.commit()
    n = len(usage(db).get(block.id, []))
    flash(request, f"Datenblock gespeichert ({len(fm.questions(items))} Felder)." + (f" Gilt sofort in {n} Formular(en)." if n else ""))
    return redirect(f"/forms/blocks/{block.id}")


@app.post("/forms/blocks/{block_id:int}/copy", dependencies=[Depends(check_csrf)])
def block_copy(request: Request, block_id: int, user: User = Depends(blocks_user), db: Session = Depends(get_db)):
    _module_on()
    block = _block(db, block_id)
    clone = FormBlock(name=(block.name + " (Kopie)")[:200], description=block.description, icon=block.icon,
                      schema_json=block.schema_json)
    db.add(clone)
    db.commit()
    flash(request, "Datenblock kopiert.")
    return redirect(f"/forms/blocks/{clone.id}")


@app.post("/forms/blocks/{block_id:int}/delete", dependencies=[Depends(check_csrf)])
def block_delete(request: Request, block_id: int, user: User = Depends(blocks_user), db: Session = Depends(get_db)):
    _module_on()
    block = _block(db, block_id)
    used = usage(db).get(block.id, [])
    if used:
        flash(request, "Der Block wird noch verwendet in: " + ", ".join(f.title for f in used[:5]) +
              ". Bitte zuerst dort entfernen.", "error")
        return redirect(f"/forms/blocks/{block.id}")
    db.delete(block)
    db.commit()
    flash(request, "Datenblock gelöscht.")
    return redirect("/forms/blocks")
