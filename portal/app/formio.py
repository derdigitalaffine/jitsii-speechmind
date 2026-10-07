"""Formulare und Online-Anträge als Datei exportieren und auf einem anderen Server wieder importieren.

Die Exportdatei enthält immer Aufbau und Einstellungen; wahlweise zusätzlich den verknüpften Prozess, die
verwendeten Datenblöcke und die Einsendungen (dann als ZIP mit den hochgeladenen Dateien). Der Import erkennt
selbst, was enthalten ist. Bezüge, die es nur auf dem Quellserver gibt (zuständige Person/Gruppe,
Funktionspostfach, Weiterleitungsregeln, Ablage, öffentlicher Link), werden nicht übernommen; das importierte
Formular ist zunächst geschlossen.
"""

import io
import json
import re
import secrets
import zipfile
from datetime import datetime

from sqlalchemy import select

from . import applications as apps, fees, forms as fm, workflow as wf
from .db import ApplicationEvent, Form, FormBlock, FormResponse, User, utcnow

FORMAT = "jitsii-formular-1"
MAX_JSON = 20 * 1024 * 1024
MAX_ZIP = 500 * 1024 * 1024
MAX_FILES = 20000
FILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}(\.[a-z0-9]{1,10})?$")

SETTINGS = ("description", "anonymous", "multiple", "submit_message", "confirm_mail", "notify", "notify_answers",
            "notify_pdf", "notify_files", "pdf_uploads", "confirm_csv", "confirm_json", "confirm_pdf", "confirm_files",
            "notify_json", "notify_csv", "notify_scope", "review", "kind", "app_prefix", "app_category", "app_info",
            "app_fee", "app_duration", "app_deadline_days", "app_catalog", "app_pdf")
RESPONSE_FIELDS = ("name", "email", "source", "ref_no", "status")
RESPONSE_DATES = ("created_at", "status_at", "due_at", "closed_at")


class FormImportError(ValueError):
    pass


def _dt(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _parse_dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _block_ids(items: list[dict]) -> set[int]:
    return {i["block_id"] for i in items if i.get("type") == "block" and isinstance(i.get("block_id"), int)}


def export(db, form: Form, *, process: bool, blocks: bool, responses: bool) -> tuple[bytes, str]:
    """Liefert (Inhalt, Dateiendung): JSON, mit Einsendungen ZIP (formular.json + Dateien)."""
    items = fm.raw_schema(form)
    used = db.scalars(select(FormBlock).where(FormBlock.id.in_(_block_ids(items)))).all() if _block_ids(items) else []
    data = {
        "format": FORMAT, "exported_at": _dt(utcnow()), "title": form.title,
        "settings": {k: getattr(form, k) for k in SETTINGS},
        "schema": items,
        "fee": fees.config(form),
        # Namen genügen, um Datenblöcke auf dem Zielserver wiederzufinden, auch wenn sie nicht mitkommen
        "block_names": {str(b.id): b.name for b in used},
    }
    if blocks:
        data["blocks"] = [{"id": b.id, "name": b.name, "description": b.description, "icon": b.icon,
                           "schema": json.loads(b.schema_json or "[]")} for b in used]
    if process and form.process is not None:
        data["process"] = wf.export_data(form.process)
    if not responses:
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "json"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        data["responses"] = []
        for n, resp in enumerate(form.responses):
            entry = {k: getattr(resp, k) for k in RESPONSE_FIELDS} | {k: _dt(getattr(resp, k)) for k in RESPONSE_DATES}
            entry |= {"answers": resp.answers, "fields": resp.fields, "checksum": resp.checksum,
                      "events": [{"at": _dt(e.at), "kind": e.kind, "actor_name": e.actor_name, "status": e.status,
                                  "text": e.text, "public": e.public} for e in resp.events]}
            folder = fm.files_dir(form.id, resp.id)
            for files in resp.answers.values():
                for f in files if isinstance(files, list) else []:
                    name = f.get("file") if isinstance(f, dict) else None
                    if name and FILE_RE.match(name) and (folder / name).is_file():
                        zf.write(folder / name, f"dateien/{n}/{name}")
            data["responses"].append(entry)
        zf.writestr("formular.json", json.dumps(data, ensure_ascii=False, indent=2))
    return buf.getvalue(), "zip"


def read(raw: bytes) -> tuple[dict, zipfile.ZipFile | None]:
    """Erkennt JSON oder ZIP und prüft das Format."""
    archive = None
    if raw[:4] == b"PK\x03\x04":
        if len(raw) > MAX_ZIP:
            raise FormImportError("Die Datei ist zu groß.")
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
            infos = archive.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > 4 * MAX_ZIP:
                raise FormImportError("Das Archiv ist zu groß.")
            info = archive.getinfo("formular.json")
            if info.file_size > MAX_JSON:
                raise FormImportError("Die Datei ist zu groß.")
            raw = archive.read(info)
        except (zipfile.BadZipFile, KeyError):
            raise FormImportError("Das ZIP enthält kein exportiertes Formular.") from None
    elif len(raw) > MAX_JSON:
        raise FormImportError("Die Datei ist zu groß.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise FormImportError("Die Datei ist kein exportiertes Formular.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("schema"), list):
        raise FormImportError("Die Datei ist kein exportiertes Formular.")
    return data, archive


def describe(data: dict) -> list[str]:
    """Was die Datei enthält – für die Rückmeldung nach dem Import."""
    parts = ["Online-Antrag" if (data.get("settings") or {}).get("kind") == "application" else "Formular"]
    if data.get("process"):
        parts.append("Prozess")
    if data.get("blocks"):
        parts.append(f"{len(data['blocks'])} Datenblock/-blöcke")
    if data.get("responses") is not None:
        parts.append(f"{len(data['responses'])} Einsendung(en)")
    return parts


def _map_blocks(db, data: dict) -> tuple[dict[int, int], list[str], int]:
    """Alte Block-ID → Block auf diesem Server: gleichnamigen nutzen, sonst (wenn mitgeliefert) anlegen."""
    names = {int(k): str(v) for k, v in (data.get("block_names") or {}).items() if str(k).isdigit()}
    given = {b["id"]: b for b in data.get("blocks") or [] if isinstance(b, dict) and isinstance(b.get("id"), int)}
    for bid, b in given.items():
        names.setdefault(bid, str(b.get("name") or ""))
    existing = {b.name.strip().lower(): b for b in db.scalars(select(FormBlock))}
    mapping, missing, created = {}, [], 0
    for bid, name in names.items():
        name = " ".join(name.split())[:200]
        found = existing.get(name.lower())
        if found is None and bid in given:
            src = given[bid]
            found = FormBlock(name=name or "Importierter Datenblock", description=str(src.get("description") or "")[:5000],
                              icon=str(src.get("icon") or "fa-cubes")[:40] if re.fullmatch(r"fa-[a-z0-9-]{1,36}", str(src.get("icon") or "")) else "fa-cubes",
                              schema_json=json.dumps([i for i in fm.clean_schema(src.get("schema") or []) if i["type"] != "block"],
                                                     ensure_ascii=False))
            db.add(found)
            db.flush()
            existing[found.name.lower()] = found
            created += 1
        if found is None:
            missing.append(name or f"#{bid}")
        else:
            mapping[bid] = found.id
    return mapping, missing, created


def import_form(db, data: dict, archive: zipfile.ZipFile | None, user: User, *, with_process: bool) -> tuple[Form, list[str]]:
    """Legt das Formular (und Mitgeliefertes) an. Gibt das Formular und Hinweise für die Rückmeldung zurück."""
    notes = []
    mapping, missing, created = _map_blocks(db, data)
    db.commit()   # Datenblöcke müssen für die Prüfung des Aufbaus (eigene Sitzung) sichtbar sein
    if created:
        notes.append(f"{created} Datenblock/-blöcke neu angelegt.")
    if missing:
        notes.append("Nicht gefundene Datenblöcke wurden weggelassen: " + ", ".join(missing) + ".")
    items = []
    for item in data["schema"]:
        if isinstance(item, dict) and item.get("type") == "block":
            if item.get("block_id") not in mapping:
                continue
            item = {**item, "block_id": mapping[item["block_id"]]}
        items.append(item)
    items = fm.clean_schema(items)

    cfg = data.get("settings") or {}
    form = Form(owner_id=user.id, title=" ".join(str(data.get("title") or "Importiertes Formular").split())[:255],
                schema_json=json.dumps(items, ensure_ascii=False), active=False, public_token=None)
    for key in SETTINGS:
        column = Form.__table__.c[key]
        default, value = column.default.arg, cfg.get(key)
        if isinstance(default, bool):
            setattr(form, key, bool(value) if value is not None else default)
        elif isinstance(default, int):
            try:
                setattr(form, key, max(0, min(3650, int(value))))
            except (TypeError, ValueError):
                setattr(form, key, default)
        else:
            setattr(form, key, str(value if value is not None else default)[:column.type.length or 20000])
    if form.kind not in ("survey", "application"):
        form.kind = "survey"
    if "confirm_pdf" not in cfg:
        form.confirm_pdf = form.kind == "application" and form.app_pdf
    if form.notify_scope not in ("single", "all"):
        form.notify_scope = "single"
    if form.app_prefix and not apps.PREFIX_RE.match(form.app_prefix):
        form.app_prefix = ""
    db.add(form)
    db.flush()

    fee = data.get("fee") if isinstance(data.get("fee"), dict) else {}
    if fee:
        fee = {**fee, "base": f"{int(fee.get('base') or 0) / 100:.2f}" if isinstance(fee.get("base"), int) else "",
               "methods": str(fee.get("methods") or "").split(",")}
        form.fee_json = json.dumps(fees.clean(fee, form), ensure_ascii=False)

    if isinstance(data.get("process"), dict) and isinstance(data["process"].get("definition"), dict):
        if with_process:
            form.process = wf.import_process(db, data["process"], user)
            notes.append(f"Prozess „{form.process.name}“ als Entwurf angelegt – bitte Zuständigkeiten prüfen und veröffentlichen.")
        else:
            notes.append("Der mitgelieferte Prozess wurde nicht übernommen (keine Berechtigung für Prozesse).")

    responses = data.get("responses")
    if isinstance(responses, list):
        count = _import_responses(db, form, responses, archive, user)
        notes.append(f"{count} Einsendung(en) übernommen.")
    if form.kind == "application":
        notes.append("Zuständigkeit, Funktionspostfach, Weiterleitungsregeln und Ablage bitte neu festlegen.")
    return form, notes


def _import_responses(db, form: Form, responses: list, archive: zipfile.ZipFile | None, user: User) -> int:
    names = set(archive.namelist()) if archive else set()
    last: dict[int, int] = {}   # Jahr → höchste laufende Nummer der übernommenen Aktenzeichen
    count = 0
    for n, src in enumerate(responses):
        if not isinstance(src, dict) or not isinstance(src.get("answers"), dict):
            continue
        resp = FormResponse(form_id=form.id, answers_json=json.dumps(src["answers"], ensure_ascii=False),
                            fields_json=json.dumps(src.get("fields") if isinstance(src.get("fields"), dict) else {},
                                                   ensure_ascii=False))
        for key in RESPONSE_FIELDS:
            limit = getattr(FormResponse, key).type.length
            value = src.get(key)
            setattr(resp, key, str(value)[:limit] if value else (None if key == "ref_no" else ""))
        if resp.source not in ("public", "invite", "user"):
            resp.source = "public"
        if resp.status and resp.status not in apps.STATUSES:
            resp.status = "received"
        for key in RESPONSE_DATES:
            setattr(resp, key, _parse_dt(src.get(key)))
        resp.created_at = resp.created_at or utcnow()
        db.add(resp)
        db.flush()
        _restore_files(form, resp, n, names, archive)
        if resp.ref_no:
            if m := re.search(r"-(\d{4})-(\d+)$", resp.ref_no):
                year, seq = int(m.group(1)), int(m.group(2))
                last[year] = max(last.get(year, 0), seq)
            for ev in src.get("events") or []:
                if isinstance(ev, dict):
                    resp.events.append(ApplicationEvent(
                        at=_parse_dt(ev.get("at")) or resp.created_at, kind=str(ev.get("kind") or "note")[:12],
                        actor_name=str(ev.get("actor_name") or "")[:255], status=str(ev.get("status") or "")[:16],
                        text=str(ev.get("text") or "")[:20000], public=bool(ev.get("public"))))
            original = str(src.get("checksum") or "")[:64]
            resp.checksum = apps.checksum(resp)
            resp.events.append(ApplicationEvent(kind="note", actor_id=user.id, actor_name=user.name,
                                                text="Aus Exportdatei importiert." + (f" Prüfsumme auf dem Quellserver: {original}" if original else "")))
        count += 1
    if last:   # neue Anträge setzen die Nummerierung fort, statt Aktenzeichen doppelt zu vergeben
        form.app_seq_year = max(last)
        form.app_seq = last[form.app_seq_year]
    return count


def _restore_files(form: Form, resp: FormResponse, n: int, names: set[str], archive: zipfile.ZipFile | None) -> None:
    """Dateien aus dem ZIP zurückschreiben; Einträge ohne Datei bleiben als Verweis stehen."""
    if archive is None:
        return
    answers = resp.answers
    target = fm.files_dir(form.id, resp.id)
    changed = False
    for qid, files in answers.items():
        if not isinstance(files, list):
            continue
        for f in files:
            name = f.get("file") if isinstance(f, dict) else None
            member = f"dateien/{n}/{name}"
            if not name or not FILE_RE.match(name) or member not in names:
                continue
            target.mkdir(parents=True, exist_ok=True)
            new = secrets.token_hex(8) + (("." + name.rsplit(".", 1)[1]) if "." in name else "")
            with archive.open(member) as src, open(target / new, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    out.write(chunk)
            f["file"] = new
            changed = True
    if changed:
        resp.answers_json = json.dumps(answers, ensure_ascii=False)
