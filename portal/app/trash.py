"""Löschen mit Papierkorb (Verwaltung › Löschen & Papierkorb).

Ein Eintrag wird mit allen abhängigen Daten gesichert, bevor er gelöscht wird: Die Datenbank kennt über die
Fremdschlüssel, welche Zeilen mitgelöscht werden (ON DELETE CASCADE) und welche nur ihren Verweis verlieren
(ON DELETE SET NULL). Beides wird als JSON abgelegt, zugehörige Dateien wandern in den Ordner trash/<nr>.
Wiederherstellen schreibt die Zeilen mit ihren alten Nummern zurück und setzt Verweise wieder, soweit die
verweisenden Einträge noch existieren. Nach Ablauf der Frist (30 Tage) wird endgültig gelöscht.
"""

import base64
import json
import secrets
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, delete, func, insert, or_, select, update

from .config import settings
from .db import (
    Base, Circulation, CirculationBundle, DeletionLog, DmsArea, DmsFile, DmsRecord, FormResponse, Payment, Poll, Resource, ResourceBooking, SessionLocal, ShortLink, UserMap,
    TrashItem, Vote, to_local, utcnow,
)

from .trash_identity import install as _install_identity_guards

_install_identity_guards()

KEEP_DAYS = 30
MAX_BULK = 5000


def trash_dir() -> Path:
    return settings.data_dir / "trash"


# --- Bereiche ----------------------------------------------------------------------------------
# kind: (Modell, Bezeichnung, Symbol, Suchfelder, Datumsfeld für „älter als“, Anzeige, Dateiordner, Statusfeld)

def _booking_label(b: ResourceBooking) -> str:
    return f"{b.ref} – {b.resource.name if b.resource else '?'}, {to_local(b.starts_at).strftime('%d.%m.%Y')}, {b.name}"


def _response_label(r: FormResponse) -> str:
    return f"{r.ref_no or 'Antwort ' + str(r.id)} – {r.form.title if r.form else '?'}" + (f", {r.name}" if r.name else "")


KINDS = {
    "user_map": {"model": UserMap, "label": "Eigene Karten", "icon": "fa-map", "search": ("title", "description"),
                 "date": "created_at", "show": lambda o: o.title, "files": lambda o: []},
    "dms_file": {"model": DmsFile, "label": "DMS-Dateien", "icon": "fa-file", "search": ("name",),
                 "date": "created_at", "show": lambda o: o.name,
                 "files": lambda o: [settings.data_dir / "dms" / str(o.record_id) / o.file]},
    "dms_area": {"model": DmsArea, "label": "DMS-Ordner", "icon": "fa-folder", "search": ("name", "code"),
                 "date": "created_at", "show": lambda o: f"{o.code} {o.name}".strip(), "files": lambda o: []},
    "circulation_bundle": {"model":CirculationBundle,"label":"Sammelmappen","icon":"fa-folder-open","search":("draft_json",),"date":"created_at",
        "show":lambda o:json.loads(o.draft_json or '{}').get('title') or 'Neue Sammelmappe',
        "files":lambda o:[settings.data_dir / 'circulation-bundles' / str(o.id)]},
    "circulation_draft": {"model":Circulation,"label":"Umlaufentwürfe","icon":"fa-bullhorn","search":("draft_json",),"date":"created_at",
        "show":lambda o:json.loads(o.draft_json or '{}').get('title') or 'Neuer Umlaufentwurf',
        "files":lambda o:[settings.data_dir / 'circulations' / str(o.id)]},
    "booking": {"model": ResourceBooking, "label": "Buchungen (Ressourcen)", "icon": "fa-calendar-check",
                "search": ("ref", "name", "email", "title"), "date": "ends_at", "status": "status",
                "statuses": {"cancelled": "storniert", "rejected": "abgelehnt", "expired": "verfallen",
                             "confirmed": "bestätigt", "requested": "Anfrage", "unconfirmed": "unbestätigt"},
                "show": _booking_label, "files": lambda o: [settings.data_dir / "resources" / "bookings" / str(o.id)]},
    "resource": {"model": Resource, "label": "Ressourcen", "icon": "fa-building", "search": ("name", "category", "location"),
                 "date": "created_at", "show": lambda o: o.name,
                 "files": lambda o: [settings.data_dir / "resources" / str(o.id)]},
    "payment": {"model": Payment, "label": "Zahlungen", "icon": "fa-euro-sign", "search": ("ref", "purpose", "payer_name", "payer_email"),
                "date": "created_at", "status": "status",
                "statuses": {"cancelled": "storniert", "paid": "bezahlt", "open": "offen", "refunded": "erstattet"},
                "show": lambda o: f"{o.ref} – {o.purpose}", "files": lambda o: []},
    "application": {"model": FormResponse, "label": "Online-Anträge und Formularantworten", "icon": "fa-file-signature",
                    "search": ("ref_no", "name", "email"), "date": "created_at", "status": "status",
                    "statuses": {"done": "erledigt", "approved": "genehmigt", "rejected": "abgelehnt", "withdrawn": "zurückgezogen"},
                    "show": _response_label, "files": lambda o: [settings.data_dir / "forms" / str(o.form_id) / str(o.id)]},
    "dms": {"model": DmsRecord, "label": "Ablage-Einträge (DMS)", "icon": "fa-box-archive",
            "search": ("title", "ref_no", "applicant"), "date": "received_at",
            "show": lambda o: f"{o.ref_no or ''} {o.title}".strip(), "files": lambda o: [settings.data_dir / "dms" / str(o.id)]},
    "poll": {"model": Poll, "label": "Terminumfragen", "icon": "fa-calendar-days", "search": ("title",), "date": "created_at",
             "show": lambda o: o.title, "files": lambda o: []},
    "vote": {"model": Vote, "label": "Abstimmungen", "icon": "fa-check-to-slot", "search": ("title",), "date": "created_at",
             "status": "status", "statuses": {"closed": "beendet", "draft": "Entwurf", "open": "läuft"},
             "show": lambda o: o.title, "files": lambda o: []},
    "shortlink": {"model": ShortLink, "label": "Kurzlinks", "icon": "fa-link", "search": ("code", "title", "target_url"),
                  "date": "created_at", "show": lambda o: f"/{o.code} – {o.title or o.target_url}", "files": lambda o: []},
}


def _col(model, name):
    return getattr(model, name, None)


def search(db, kind: str, q: str = "", limit: int = 50) -> list:
    k = KINDS[kind]
    model = k["model"]
    stmt = select(model)
    if kind == "circulation_draft": stmt = stmt.where(Circulation.current_version == 0)
    if kind == "application":
        stmt = stmt.where(FormResponse.id.is_not(None))
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        conds = [_col(model, f).ilike(like) for f in k["search"] if _col(model, f) is not None]
        if q.isdigit():
            conds.append(model.id == int(q))
        stmt = stmt.where(or_(*conds))
    order = _col(model, k["date"])
    return list(db.scalars(stmt.order_by(order.desc() if order is not None else model.id.desc()).limit(limit)))


def bulk_query(kind: str, before: date | None, status: str = ""):
    k = KINDS[kind]
    model = k["model"]
    conds = []
    if before is not None:
        conds.append(_col(model, k["date"]) < datetime.combine(before, datetime.min.time()))
    if status and k.get("status"):
        conds.append(_col(model, k["status"]) == status)
    if conds and kind == "circulation_draft": conds.append(Circulation.current_version == 0)
    return model, (and_(*conds) if conds else None)


def bulk_count(db, kind: str, before: date | None, status: str = "") -> int:
    model, cond = bulk_query(kind, before, status)
    if cond is None:
        return 0      # ohne Bedingung wird nie alles gelöscht
    if kind in PROTECTED_KINDS:
        return sum(not protection(db, kind, obj) for obj in db.scalars(select(model).where(cond)))
    return db.scalar(select(func.count()).select_from(model).where(cond)) or 0


# --- Sichern und Wiederherstellen --------------------------------------------------------------

def _enc(value):
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {"$b": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _dec(value):
    if isinstance(value, dict):
        if "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if "$d" in value:
            return date.fromisoformat(value["$d"])
        if "$b" in value:
            return base64.b64decode(value["$b"])
    return value


def _refs(table):
    """Fremdschlüssel anderer Tabellen auf diese: [(Tabelle, Spalte, Zielspalte, ondelete)]."""
    out = []
    for other in Base.metadata.sorted_tables:
        for fk in other.foreign_keys:
            if fk.column.table is table:
                out.append((other, fk.parent, fk.column, (fk.ondelete or "").upper()))
    return out


def snapshot(db, table, where) -> dict:
    """Alle Zeilen, die beim Löschen verschwinden (mit Kaskade) bzw. ihren Verweis verlieren."""
    rows, nulls, seen = [], [], set()

    def walk(tbl, cond):
        found = db.execute(select(tbl).where(cond)).mappings().all()
        if not found:
            return
        pk = list(tbl.primary_key.columns)
        for r in found:
            key = (tbl.name, tuple(r[c.name] for c in pk))
            if key in seen:
                continue
            seen.add(key)
            rows.append({"table": tbl.name, "data": {k: _enc(v) for k, v in r.items()}})
        for other, col, target, ondelete in _refs(tbl):
            values = [r[target.name] for r in found if r[target.name] is not None]
            if not values:
                continue
            if ondelete == "CASCADE":
                walk(other, col.in_(values))
            elif ondelete == "SET NULL":
                opk = list(other.primary_key.columns)
                for ref in db.execute(select(other).where(col.in_(values))).mappings():
                    identity_keys = ['created_at'] if 'created_at' in other.c else [k for k in ref if k != col.name]
                    nulls.append({"table": other.name, "pk": {c.name: _enc(ref[c.name]) for c in opk},
                                  "col": col.name, "value": _enc(ref[col.name]),
                                  "identity": {k: _enc(ref[k]) for k in identity_keys}})

    walk(table, where)
    return {"rows": rows, "nulls": nulls}


def _table(name):
    return Base.metadata.tables[name]


def restore_rows(db, data: dict) -> None:
    """Zeilen in der gesicherten Reihenfolge (Eltern zuerst) zurückschreiben, dann Verweise wiederherstellen."""
    for item in data.get("rows", []):
        tbl = _table(item["table"])
        values = {k: _dec(v) for k, v in item["data"].items() if k in tbl.c}
        db.execute(insert(tbl).values(**values))
    for ref in data.get("nulls", []):
        tbl = _table(ref["table"])
        cond = and_(*[tbl.c[k] == _dec(v) for k, v in ref["pk"].items()], tbl.c[ref["col"]].is_(None),
                    *[tbl.c[k] == _dec(v) for k, v in ref.get("identity", {}).items() if k in tbl.c])
        db.execute(update(tbl).where(cond).values({ref["col"]: _dec(ref["value"])}))


def _move_files(paths: list[Path], item_id: int) -> list[list[str]]:
    moved = []
    for n, src in enumerate(paths):
        if src.exists():
            dst = trash_dir() / str(item_id) / str(n)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append([str(src), str(dst)])
    return moved


def log(db, actor: str, action: str, kind: str = "", count: int = 1, detail: str = "") -> None:
    db.add(DeletionLog(actor=actor[:255], action=action, kind=kind, count=count, detail=detail[:5000]))


PROTECTED_KINDS = {"dms", "dms_file", "dms_area", "circulation_bundle", "circulation_draft"}


def protection(db, kind: str, obj) -> str:
    """Apply the same preservation rules in object views and administration."""
    if kind == "circulation_draft" and obj.current_version:
        return "Veröffentlichte Umläufe können nicht als Entwurf gelöscht werden."
    if kind == "circulation_bundle":
        from .bundle_lifecycle import removable
        if not removable(db, obj):
            return "Geteilte oder verwendete Sammelmappen können nur archiviert werden."
    if kind in {"dms", "dms_file", "dms_area"}:
        from . import dms_lifecycle
        check = {"dms": dms_lifecycle.protection, "dms_file": dms_lifecycle.file_protection,
                 "dms_area": dms_lifecycle.area_protection}[kind]
        reasons = check(db, obj)
        return "; ".join(reasons) if isinstance(reasons, list) else reasons or ""
    return ""


def delete_obj(db, kind: str, obj, actor: str, batch: str = "") -> TrashItem:
    """In den Papierkorb: sichern, Dateien verschieben, löschen."""
    k = KINDS[kind]
    reason = protection(db, kind, obj)
    if reason:
        raise ValueError(reason)
    model = k["model"]
    label = k["show"](obj)[:300]
    files = k["files"](obj)
    if kind == "dms" and obj.response:
        obj.response.dms_removed = True
    table = model.__table__
    data = snapshot(db, table, table.c.id == obj.id)
    item = TrashItem(kind=kind, label=label, table_name=table.name, row_id=obj.id,
                     data_json=json.dumps(data, ensure_ascii=False), deleted_by=actor[:255], batch=batch,
                     expires_at=utcnow() + timedelta(days=KEEP_DAYS))
    db.add(item)
    db.flush()
    db.expunge(obj)
    db.execute(delete(table).where(table.c.id == obj.id))
    item.files_json = json.dumps(_move_files(files, item.id))
    return item


def delete_one(db, kind: str, obj_id: int, actor: str) -> TrashItem | None:
    obj = db.get(KINDS[kind]["model"], obj_id)
    if obj is None:
        return None
    reason = protection(db, kind, obj)
    if reason:
        raise ValueError(reason)
    item = delete_obj(db, kind, obj, actor)
    log(db, actor, "delete", kind, 1, item.label)
    return item


def delete_bulk(db, kind: str, before: date | None, status: str, actor: str) -> int:
    model, cond = bulk_query(kind, before, status)
    if cond is None:
        return 0
    batch = secrets.token_hex(8)
    ids = list(db.scalars(select(model.id).where(cond).limit(MAX_BULK)))
    n = 0
    for oid in ids:
        obj = db.get(model, oid)
        if obj is not None:
            if protection(db, kind, obj):
                continue
            delete_obj(db, kind, obj, actor, batch)
            n += 1
    crit = (f"vor {before.strftime('%d.%m.%Y')}" if before else "") + (f", Status {status}" if status else "")
    log(db, actor, "bulk", kind, n, f"{KINDS[kind]['label']}: {crit.strip(', ')}")
    return n


def restore(db, item: TrashItem, actor: str) -> str | None:
    """Wiederherstellen. Gibt eine Fehlermeldung zurück oder None."""
    if item.expires_at <= utcnow():
        return "Die Frist zur Wiederherstellung ist abgelaufen."
    for original, saved in json.loads(item.files_json or "[]"):
        if Path(original).exists():
            return "Am ursprünglichen Speicherort liegt bereits eine Datei. Bitte den Konflikt vor der Wiederherstellung klären."
        if not Path(saved).exists():
            return "Eine gesicherte Datei fehlt. Bitte die Wiederherstellung administrativ prüfen lassen."
    data = json.loads(item.data_json or "{}")
    if item.kind in {"dms", "dms_file", "dms_area"}:
        from .dms_lifecycle import restore_error
        error = restore_error(db, item)
        if error:
            return error
    if item.kind == "user_map":
        from .map_lifecycle import prepare_restore
        data = prepare_restore(db, data)
    tbl = _table(item.table_name)
    if db.execute(select(tbl.c.id).where(tbl.c.id == item.row_id)).first() is not None:
        return "Unter dieser Nummer gibt es inzwischen einen anderen Eintrag – Wiederherstellen nicht möglich."
    try:
        with db.begin_nested():
            restore_rows(db, data)
            if item.kind in {"dms", "dms_area"}:
                response_ids = [row['data'].get('response_id') for row in data.get('rows', []) if row.get('table') == 'dms_records']
                db.execute(update(FormResponse).where(FormResponse.id.in_([i for i in response_ids if i is not None])).values(dms_removed=False))
    except Exception as exc:  # noqa: BLE001  (z. B. ein übergeordneter Eintrag fehlt inzwischen)
        return f"Wiederherstellen nicht möglich: {str(exc).splitlines()[0][:200]}"
    for src, dst in json.loads(item.files_json or "[]"):
        if Path(dst).exists() and not Path(src).exists():
            Path(src).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dst, src)
    shutil.rmtree(trash_dir() / str(item.id), ignore_errors=True)
    log(db, actor, "restore", item.kind, 1, item.label)
    db.delete(item)
    return None


def purge(db, item: TrashItem, actor: str, action: str = "purge") -> None:
    shutil.rmtree(trash_dir() / str(item.id), ignore_errors=True)
    log(db, actor, action, item.kind, 1, item.label)
    db.delete(item)


def purge_expired() -> int:
    """Hintergrunddienst: abgelaufene Einträge endgültig löschen."""
    with SessionLocal() as db:
        items = db.scalars(select(TrashItem).where(TrashItem.expires_at < utcnow())).all()
        for item in items:
            purge(db, item, "automatisch", "expire")
        db.commit()
        return len(items)
