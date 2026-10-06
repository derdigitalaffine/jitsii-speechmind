"""Workflow-Engine für Online-Anträge.

Ein Prozess ist eine Folge von Arbeitsschritten. Jeder Schritt kann an eine Bedingung geknüpft sein
(sonst wird er übersprungen) und hat eine eigene Zuständigkeit und Frist. Schritttypen:

  task      Aufgabe mit Prüfpunkten (Checkliste) und internen Feldern (z. B. Gebührenbetrag)
  approval  Freigabe – genehmigen oder ablehnen, optional nach dem Vier-Augen-Prinzip
  request   Nachforderung – der Prozess wartet, bis die antragstellende Person Angaben/Dateien nachreicht
  auto      Automatik – Mail senden, Status setzen, Bescheid als PDF erzeugen, Zuständigkeit ändern

Bearbeitet wird im Prozesseditor ein Entwurf; veröffentlicht entsteht eine neue Version. Ein Antrag
bleibt immer auf der Version, mit der er gestartet ist.
"""

import base64
import io
import json
import re
import secrets
from datetime import timedelta

from sqlalchemy import or_, select

from . import applications as apps, forms as fm, mailtpl, notify
from .config import settings
from .db import (
    ApplicationDocument, ApplicationRequest, ApplicationTask, Form, FormResponse, Group, GroupMember, Process,
    ProcessVersion, RequestTemplate, SessionLocal, User, to_local, utcnow,
)
from .planning import EMAIL_RE

STEP_TYPES = {
    "task": ("Aufgabe", "fa-list-check", "Sachbearbeitung prüft anhand einer Checkliste und erfasst interne Angaben."),
    "approval": ("Freigabe", "fa-stamp", "Eine Person oder Gruppe genehmigt oder lehnt ab."),
    "request": ("Nachforderung", "fa-file-circle-question", "Die antragstellende Person reicht Angaben oder Dateien nach."),
    "auto": ("Automatik", "fa-robot", "Mail senden, Status setzen, Bescheid-PDF erzeugen – ohne Zutun."),
    "confirm": ("E-Mail bestätigen", "fa-envelope-circle-check",
                "Double-Opt-in: Der Prozess wartet, bis die antragstellende Person den Link in der Mail angeklickt hat."),
    "payment": ("Zahlung anfordern", "fa-euro-sign",
                "Gebühr (fest oder aus einem internen Feld) anfordern – der Prozess wartet, bis bezahlt ist."),
}
EXPIRE_ACTIONS = {"notify": "Zuständige informieren (Vorgang bleibt offen)", "withdraw": "Vorgang beenden (Status „Zurückgezogen“)"}
ASSIGN_MODES = {"case": "Zuständigkeit des Vorgangs", "user": "Bestimmte Person", "group": "Gruppe",
                "previous": "Wer den vorigen Schritt erledigt hat"}
OPS = {"eq": "ist gleich", "ne": "ist nicht", "contains": "enthält", "filled": "ist ausgefüllt",
       "empty": "ist leer", "gt": "ist größer als", "lt": "ist kleiner als"}
FIELD_TYPES = {"text": "Text", "textarea": "Langer Text", "number": "Zahl", "money": "Betrag (€)",
               "date": "Datum", "select": "Auswahl", "yesno": "Ja/Nein"}
ACTION_TYPES = {"mail": "E-Mail senden", "status": "Status setzen", "pdf": "Dokument (PDF) erzeugen",
                "assign": "Zuständigkeit des Vorgangs ändern"}
MAIL_TARGETS = {"applicant": "Antragsteller:in", "case": "Zuständige des Vorgangs", "email": "Feste Adresse"}
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
TOKEN_RE = re.compile(r"\{(feld|frage):([^{}]{1,200})\}|\{([a-z_]{1,30})\}")
REQUEST_TYPES = ("short", "long", "radio", "checkbox", "dropdown", "date", "file", "address", "geo", "text")
CLOSED = apps.CLOSED


# --- Definition bereinigen -----------------------------------------------------------------

def _s(value, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def _id(value) -> int | None:
    return int(value) if str(value or "").isdigit() else None


def _days(value, hi: int = 365) -> int:
    try:
        return max(0, min(hi, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _clean_condition(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("source") not in ("q", "f", "step") or raw.get("op") not in OPS:
        return None
    key = _s(raw.get("key"), 200)
    if not key:
        return None
    return {"source": raw["source"], "key": key, "op": raw["op"], "value": _s(raw.get("value"), 500)}


def _clean_fields(raw, seen: set | None = None) -> list[dict]:
    """Interne Felder einer Aufgabe. Der Schlüssel ist frei wählbar (Platzhalter {feld:schlüssel});
    ohne Angabe bekommt das Feld die nächste freie Nummer – eindeutig im ganzen Prozess."""
    out = []
    seen = seen if seen is not None else set()
    pending = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        label = _s(f.get("label"), 200)
        if not label:
            continue
        key = re.sub(r"[^a-z0-9_]", "_", _s(f.get("key"), 40).lower().replace("ä", "ae").replace("ö", "oe")
                     .replace("ü", "ue").replace("ß", "ss")).strip("_")[:40]
        if not key or key in seen or not KEY_RE.match(key):
            pending.append((len(out), f, label))
            out.append(None)
            continue
        seen.add(key)
        kind = f.get("type") if f.get("type") in FIELD_TYPES else "text"
        options = [o for o in (_s(x, 200) for x in (f.get("options") or [])) if o][:50] if kind == "select" else []
        out.append({"key": key, "label": label, "type": kind, "options": options, "required": bool(f.get("required"))})
    for pos, f, label in pending:
        n = 1
        while str(n) in seen:
            n += 1
        seen.add(str(n))
        kind = f.get("type") if f.get("type") in FIELD_TYPES else "text"
        options = [o for o in (_s(x, 200) for x in (f.get("options") or [])) if o][:50] if kind == "select" else []
        out[pos] = {"key": str(n), "label": label, "type": kind, "options": options, "required": bool(f.get("required"))}
    return [f for f in out if f][:30]


def _clean_actions(raw) -> list[dict]:
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            continue
        kind = a["type"]
        if kind == "mail":
            to = a.get("to") if a.get("to") in MAIL_TARGETS else "applicant"
            email = _s(a.get("email"), 255).lower()
            out.append({"type": kind, "to": to, "email": email if EMAIL_RE.match(email or "-") else "",
                        "subject": _s(a.get("subject"), 300), "body": _s(a.get("body"), 20000),
                        "attach": a.get("attach") if a.get("attach") in ("", "application", "documents") else ""})
        elif kind == "status":
            status = a.get("status") if a.get("status") in apps.STATUSES else "in_progress"
            out.append({"type": kind, "status": status, "message": _s(a.get("message"), 5000),
                        "inform": bool(a.get("inform"))})
        elif kind == "pdf":
            out.append({"type": kind, "title": _s(a.get("title"), 200) or "Bescheid", "body": _s(a.get("body"), 50000),
                        "public": bool(a.get("public")), "send": bool(a.get("send"))})
        elif kind == "assign":
            out.append({"type": kind, "user_id": _id(a.get("user_id")), "group_id": _id(a.get("group_id"))})
    return out[:20]


def clean_request_items(raw) -> list[dict]:
    """Felder einer Nachforderung: Teilmenge der Formular-Fragetypen, bereinigt wie im Baukasten."""
    items = [i for i in fm.clean_schema(raw if isinstance(raw, list) else []) if i["type"] in REQUEST_TYPES]
    return items[:40]


def clean_definition(raw) -> dict:
    """Bereinigt den Prozess aus dem Editor (unbekannte Felder fallen weg, Sprünge nur auf vorhandene Schritte)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    steps, seen, field_keys = [], set(), set()
    for src in raw.get("steps") if isinstance(raw.get("steps"), list) else []:
        if not isinstance(src, dict) or src.get("type") not in STEP_TYPES:
            continue
        kind = src["type"]
        sid = str(src.get("id") or "")
        if not STEP_ID_RE.match(sid) or sid in seen:
            sid = secrets.token_hex(4)
        seen.add(sid)
        assign = src.get("assign") if isinstance(src.get("assign"), dict) else {}
        escalate = src.get("escalate") if isinstance(src.get("escalate"), dict) else {}
        step = {
            "id": sid, "type": kind, "name": _s(src.get("name"), 200) or STEP_TYPES[kind][0],
            "public_name": _s(src.get("public_name"), 200), "description": _s(src.get("description"), 5000),
            "condition": _clean_condition(src.get("condition")),
            "status": src.get("status") if src.get("status") in apps.STATUSES else "",
        }
        if kind in ("task", "approval") or (kind == "request" and src.get("compose") == "clerk"):
            mode = assign.get("mode") if assign.get("mode") in ASSIGN_MODES else "case"
            step["assign"] = {"mode": mode, "user_id": _id(assign.get("user_id")) if mode == "user" else None,
                              "group_id": _id(assign.get("group_id")) if mode == "group" else None}
            step["due_days"] = _days(src.get("due_days"))
            step["escalate"] = {"user_id": _id(escalate.get("user_id")), "group_id": _id(escalate.get("group_id")),
                                "after_days": _days(escalate.get("after_days"), 90),
                                "reassign": bool(escalate.get("reassign"))}
            step["goto"] = _s(src.get("goto"), 40)
        if kind == "task":
            step["checklist"] = [c for c in (_s(x, 300) for x in (src.get("checklist") or [])) if c][:30]
            step["fields"] = _clean_fields(src.get("fields"), field_keys)
        elif kind == "approval":
            step["four_eyes"] = bool(src.get("four_eyes"))
            step["on_reject"] = _s(src.get("on_reject"), 40) or "end"
            step["reject_status"] = src.get("reject_status") if src.get("reject_status") in apps.STATUSES else "rejected"
        elif kind == "request":
            step["compose"] = "clerk" if src.get("compose") == "clerk" else "auto"
            step["compose_days"] = _days(src.get("compose_days")) if step["compose"] == "clerk" else 0
            step["message"] = _s(src.get("message"), 10000)
            step["items"] = clean_request_items(src.get("items"))
            step["reopen"] = [t for t in (_s(x, 500) for x in (src.get("reopen") or [])) if t][:40]
            step["due_days"] = _days(src.get("due_days")) or 14   # Frist für die antragstellende Person
            step["status"] = step["status"] or "query"
        elif kind == "auto":
            step["actions"] = _clean_actions(src.get("actions"))
        elif kind == "payment":
            from . import payments as pay
            step["label"] = _s(src.get("label"), 120) or "Gebühr"
            raw_amount = src.get("amount", "")
            step["amount"] = raw_amount if isinstance(raw_amount, int) else (pay.parse_amount(raw_amount) or 0)   # Cent
            step["field"] = _s(src.get("field"), 40)
            step["due_days"] = _days(src.get("due_days"), 90) or 14
            raw_methods = src.get("methods") or ["paypal", "transfer"]
            if isinstance(raw_methods, str):
                raw_methods = raw_methods.split(",")
            step["methods"] = [m for m in raw_methods if m in ("paypal", "transfer", "cash")] or ["transfer"]
            step["on_expire"] = src.get("on_expire") if src.get("on_expire") in EXPIRE_ACTIONS else "notify"
            step["cost_center"] = _s(src.get("cost_center"), 120)
            step["message"] = _s(src.get("message"), 5000)
        elif kind == "confirm":
            step["message"] = _s(src.get("message"), 5000)
            step["due_days"] = _days(src.get("due_days"), 60) or 7
            step["remind"] = src.get("remind") is not False
            step["on_expire"] = src.get("on_expire") if src.get("on_expire") in EXPIRE_ACTIONS else "notify"
        steps.append(step)
    ids = {s["id"] for s in steps}
    for step in steps:   # Sprünge auf gelöschte Schritte entfernen
        if step.get("goto") and step["goto"] not in ids:
            step["goto"] = ""
        if step["type"] == "approval" and step["on_reject"] not in ids and step["on_reject"] != "end":
            step["on_reject"] = "end"
        cond = step.get("condition")
        if cond and cond["source"] == "step" and cond["key"] not in ids:
            step["condition"] = None
    end_status = raw.get("end_status") if raw.get("end_status") in CLOSED - {"withdrawn"} else "done"
    return {"steps": steps[:60], "end_status": end_status, "end_inform": bool(raw.get("end_inform", True)),
            "end_message": _s(raw.get("end_message"), 5000)}


def check(definition: dict, db=None) -> list[str]:
    """Hinweise vor dem Veröffentlichen – alles, was im Betrieb hängen bleiben oder überraschen könnte."""
    hints = []
    steps = definition.get("steps", [])
    if not steps:
        hints.append("Der Prozess hat noch keine Schritte.")
    index = {s["id"]: n for n, s in enumerate(steps)}
    for n, s in enumerate(steps, start=1):
        label = f"Schritt {n} „{s['name']}“"
        assign = s.get("assign") or {}
        if assign.get("mode") == "user" and not assign.get("user_id"):
            hints.append(f"{label}: Es ist keine Person ausgewählt.")
        if assign.get("mode") == "group" and not assign.get("group_id"):
            hints.append(f"{label}: Es ist keine Gruppe ausgewählt.")
        if s["type"] == "request" and s.get("compose") != "clerk" and not s.get("items") and not s.get("reopen"):
            hints.append(f"{label}: Die Nachforderung fragt nichts ab.")
        if s["type"] == "auto" and not s.get("actions"):
            hints.append(f"{label}: Die Automatik hat keine Aktionen.")
        if s["type"] == "task" and not s.get("checklist") and not s.get("fields") and not s.get("description"):
            hints.append(f"{label}: Ohne Prüfpunkte oder Hinweise weiß die Sachbearbeitung nicht, was zu tun ist.")
        if s.get("goto") and index.get(s["goto"], n) < n and s["type"] == "task":
            hints.append(f"{label}: springt zurück – achten Sie darauf, dass keine Endlosschleife entsteht.")
        cond = s.get("condition")
        if cond and cond["source"] == "step" and index.get(cond["key"], -1) >= n - 1:
            hints.append(f"{label}: Die Bedingung bezieht sich auf einen späteren Schritt.")
    if db is not None:
        for s in steps:
            for a in s.get("actions", []):
                if a["type"] == "mail" and a["to"] == "email" and not a.get("email"):
                    hints.append(f"„{s['name']}“: Die Mail-Aktion hat keine Empfängeradresse.")
    return hints


def definition_of(process: Process) -> dict:
    try:
        return clean_definition(json.loads(process.draft_json or "{}"))
    except ValueError:
        return clean_definition({})


def version_definition(version: ProcessVersion | None) -> dict:
    if version is None:
        return {"steps": [], "end_status": "done", "end_inform": True, "end_message": ""}
    try:
        data = json.loads(version.definition_json or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) and isinstance(data.get("steps"), list) else {"steps": []}


def publish(db, process: Process, actor: User, note: str) -> ProcessVersion:
    definition = definition_of(process)
    number = (process.current.version if process.current else 0) + 1
    version = ProcessVersion(version=number, definition_json=json.dumps(definition, ensure_ascii=False),
                             note=_s(note, 500), published_by=actor.name)
    process.versions.insert(0, version)
    process.draft_changed = False
    return version


def export_data(process: Process) -> dict:
    return {"format": "jitsii-prozess-1", "name": process.name, "description": process.description,
            "definition": definition_of(process)}


def import_process(db, raw: dict, owner: User) -> Process:
    """Legt einen exportierten Prozess als Entwurf an; Personen und Gruppen gibt es auf diesem Server nicht."""
    definition = clean_definition(raw["definition"])
    for step in definition["steps"]:
        if step.get("assign"):
            step["assign"] = {"mode": "case", "user_id": None, "group_id": None}
        if step.get("escalate"):
            step["escalate"] = {"user_id": None, "group_id": None, "after_days": 0, "reassign": False}
        for a in step.get("actions", []):
            if a["type"] == "assign":
                a["user_id"] = a["group_id"] = None
    process = Process(name=" ".join(str(raw.get("name") or "Importierter Prozess").split())[:200],
                      description=str(raw.get("description") or "")[:5000], owner_id=owner.id,
                      draft_json=json.dumps(definition, ensure_ascii=False))
    db.add(process)
    return process


TEMPLATES = {
    "simple": ("Einfache Prüfung", "Eingang prüfen, bei Bedarf nachfordern, abschließen.", {
        "end_status": "done",
        "steps": [
            {"id": "pruefen", "type": "task", "name": "Antrag prüfen", "public_name": "Prüfung",
             "status": "in_progress", "assign": {"mode": "case"}, "due_days": 5,
             "checklist": ["Angaben vollständig und plausibel", "Erforderliche Unterlagen liegen bei"],
             "fields": [{"label": "Unterlagen nachfordern?", "key": "nachfordern", "type": "yesno"}]},
            {"id": "nachfordern", "type": "request", "name": "Fehlende Unterlagen nachfordern",
             "public_name": "Ergänzung Ihrer Angaben", "condition": {"source": "f", "key": "nachfordern", "op": "eq", "value": "Ja"},
             "message": "Bitte reichen Sie die fehlenden Unterlagen nach.", "due_days": 14,
             "items": [{"type": "file", "title": "Fehlende Unterlagen", "required": True, "max_files": 5}]},
            {"id": "abschluss", "type": "task", "name": "Antrag abschließend bearbeiten", "public_name": "Entscheidung",
             "assign": {"mode": "previous"}, "due_days": 5, "checklist": ["Entscheidung getroffen und dokumentiert"]},
        ]}),
    "approval": ("Prüfung, Freigabe und Bescheid", "Sachbearbeitung prüft und erfasst die Gebühr, die Leitung gibt "
                 "frei (Vier-Augen-Prinzip), der Bescheid geht automatisch als PDF raus.", {
        "end_status": "approved",
        "steps": [
            {"id": "pruefen", "type": "task", "name": "Fachliche Prüfung", "public_name": "Prüfung",
             "status": "in_progress", "assign": {"mode": "case"}, "due_days": 10,
             "checklist": ["Zuständigkeit geprüft", "Angaben vollständig", "Rechtliche Voraussetzungen erfüllt"],
             "fields": [{"label": "Gebühr", "key": "gebuehr", "type": "money", "required": True},
                        {"label": "Begründung / Auflagen", "key": "begruendung", "type": "textarea"}]},
            {"id": "freigabe", "type": "approval", "name": "Freigabe durch die Leitung", "public_name": "Freigabe",
             "assign": {"mode": "case"}, "due_days": 3, "four_eyes": True, "on_reject": "pruefen"},
            {"id": "bescheid", "type": "auto", "name": "Bescheid erzeugen und versenden", "public_name": "Bescheid",
             "actions": [{"type": "pdf", "title": "Bescheid", "public": True, "send": True, "body": (
                 "Sehr geehrte/r {name},\n\nIhrem Antrag „{titel}“ vom {eingang} (Aktenzeichen {aktenzeichen}) wird "
                 "entsprochen.\n\n{feld:begruendung}\n\nFür diese Entscheidung wird eine Gebühr von {feld:gebuehr} € "
                 "erhoben.\n\nMit freundlichen Grüßen\n{bearbeiter}")}]},
        ]}),
}


# --- Platzhalter ---------------------------------------------------------------------------

def _question_by_title(form: Form, title: str) -> dict | None:
    title = title.strip().lower()
    return next((q for q in fm.questions(fm.schema(form)) if (q.get("title") or "").strip().lower() == title), None)


def current_answers(resp: FormResponse) -> dict:
    """Antworten inklusive nachgereichter Korrekturen (die jüngste gilt)."""
    answers = dict(resp.answers)
    for req in resp.requests:
        if req.state == "answered":
            for qid in req.reopen:
                if qid in req.answers:
                    answers[qid] = req.answers[qid]
    return answers


def corrections(resp: FormResponse) -> dict:
    """Frage-ID → (Zeitpunkt der Korrektur, ursprünglicher Wert)."""
    out = {}
    original = resp.answers
    for req in resp.requests:
        if req.state == "answered":
            for qid in req.reopen:
                if qid in req.answers:
                    out[qid] = (req.answered_at, original.get(qid))
    return out


def _value_text(resp: FormResponse, source: str, key: str) -> str:
    if source == "frage":
        q = _question_by_title(resp.form, key)
        return fm.display(q, current_answers(resp).get(q["id"])) if q else ""
    value = resp.fields.get(key, "")
    return _format_field(value)


def _format_field(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "" if value is None else str(value)


def placeholders(resp: FormResponse, actor_name: str = "") -> dict:
    form = resp.form
    return {
        "aktenzeichen": resp.ref_no or "", "titel": form.title, "name": resp.name or resp.email or "",
        "email": apps.applicant_email(form, resp), "datum": to_local(utcnow()).strftime("%d.%m.%Y"),
        "eingang": to_local(resp.created_at).strftime("%d.%m.%Y"), "status": apps.status_label(resp.status),
        "frist": to_local(resp.due_at).strftime("%d.%m.%Y") if resp.due_at else "",
        "zustaendig": apps._common(form, resp)["zustaendig"], "bearbeiter": actor_name,
        "statuslink": apps.track_link(resp), "link": apps.staff_link(resp),
        "gebuehr": form.app_fee or "",
    }


def fill(text: str, resp: FormResponse, actor_name: str = "") -> str:
    """{aktenzeichen}, {name} … sowie {feld:schluessel} (interne Felder) und {frage:Titel} (Antragsfragen)."""
    base = placeholders(resp, actor_name)

    def repl(m):
        if m.group(1):
            return _value_text(resp, m.group(1), m.group(2))
        return base.get(m.group(3), m.group(0))
    return TOKEN_RE.sub(repl, text or "")


# --- Bedingungen ---------------------------------------------------------------------------

def _num(value):
    try:
        return float(str(value).replace(".", "").replace(",", ".")) if isinstance(value, str) and "," in value \
            else float(value)
    except (TypeError, ValueError):
        return None


def evaluate(cond: dict | None, resp: FormResponse) -> bool:
    if not cond:
        return True
    if cond["source"] == "q":
        q = _question_by_title(resp.form, cond["key"])
        value = current_answers(resp).get(q["id"]) if q else None
    elif cond["source"] == "f":
        value = resp.fields.get(cond["key"])
    else:
        done = [t for t in resp.tasks if t.step_id == cond["key"] and t.state == "done"]
        value = {"approved": "genehmigt", "rejected": "abgelehnt", "done": "erledigt"}.get(done[-1].outcome) if done else None
    values = value if isinstance(value, list) else [value]
    texts = [str(v).strip().lower() for v in values if v not in (None, "")]
    if isinstance(value, dict):
        texts = [json.dumps(value)]
    target = cond["value"].strip().lower()
    op = cond["op"]
    if op == "filled":
        return bool(texts)
    if op == "empty":
        return not texts
    if op == "eq":
        return target in texts
    if op == "ne":
        return target not in texts
    if op == "contains":
        return any(target in t for t in texts)
    if op in ("gt", "lt"):
        a, b = _num(values[0] if values else None), _num(cond["value"])
        if a is None or b is None:
            return False
        return a > b if op == "gt" else a < b
    return True


# --- Zuständigkeit und Zugriff ----------------------------------------------------------------

def _group_ids(db, user: User) -> set[int]:
    return set(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user.id)))


def can_work(db, user: User, task: ApplicationTask) -> bool:
    if task.state not in ("open", "waiting"):
        return False
    if user.is_admin or task.assignee_id == user.id or (task.group_id and task.group_id in _group_ids(db, user)):
        return True
    if task.kind != "approval" and not task.assignee_id and not task.group_id:
        return apps.access(db, user, task.response) >= 2
    return False


def four_eyes_block(task: ApplicationTask, user: User) -> str:
    """Vier-Augen-Prinzip: wer den vorigen Schritt erledigt hat, darf nicht selbst freigeben."""
    step = step_of(task)
    if not step or not step.get("four_eyes"):
        return ""
    prior = [t for t in task.response.tasks if t.id < task.id and t.state == "done" and t.kind in ("task", "approval")]
    if prior and prior[-1].completed_by_id == user.id:
        return "Vier-Augen-Prinzip: Sie haben den vorigen Schritt erledigt – die Freigabe muss eine andere Person erteilen."
    return ""


def _resolve(db, resp: FormResponse, step: dict) -> tuple[int | None, int | None]:
    assign = step.get("assign") or {}
    mode = assign.get("mode", "case")
    if mode == "user" and assign.get("user_id") and db.get(User, assign["user_id"]):
        return assign["user_id"], None
    if mode == "group" and assign.get("group_id") and db.get(Group, assign["group_id"]):
        return None, assign["group_id"]
    if mode == "previous":
        done = [t for t in resp.tasks if t.state == "done" and t.completed_by_id]
        if done:
            return done[-1].completed_by_id, None
    if resp.assignee_id or resp.group_id:
        return resp.assignee_id, resp.group_id
    return resp.form.app_assignee_id or resp.form.owner_id, resp.form.app_group_id


def _addresses(db, user_id: int | None, group_id: int | None) -> list[str]:
    out = []
    if user_id:
        u = db.get(User, user_id)
        if u and u.active:
            out.append(u.email)
    if group_id:
        g = db.get(Group, group_id)
        for m in g.members if g else []:
            if m.active and m.email not in out:
                out.append(m.email)
    return out


def who(task: ApplicationTask) -> str:
    parts = [task.assignee.name if task.assignee else "", f"Gruppe {task.group.name}" if task.group else ""]
    return ", ".join(p for p in parts if p) or ("Antragsteller:in" if task.kind == "request" else "Zuständige des Vorgangs")


# --- Ablauf --------------------------------------------------------------------------------

def steps_of(resp: FormResponse) -> list[dict]:
    return version_definition(resp.process_version).get("steps", [])


def step_of(task: ApplicationTask) -> dict | None:
    return next((s for s in steps_of(task.response) if s["id"] == task.step_id), None)


def open_task(resp: FormResponse) -> ApplicationTask | None:
    return next((t for t in resp.tasks if t.state in ("open", "waiting")), None)


def _event(resp, kind, text="", actor=None, status="", public=False, actor_name=""):
    return apps._event(resp, kind, text, actor, status=status, public=public, actor_name=actor_name or "Prozess")


def start(db, resp: FormResponse) -> bool:
    """Startet den Prozess des Antragsformulars (aktuelle veröffentlichte Version)."""
    process = resp.form.process
    if process is None or process.current is None or resp.process_version_id:
        return False
    resp.process_version = process.current
    _event(resp, "process", f"Prozess „{process.name}“ (Version {process.current.version}) gestartet")
    db.flush()
    _advance(db, resp, 0, actor_name="")
    return True


def _set_status(db, resp: FormResponse, status: str, text: str = "", inform: bool = False, actor_name="Prozess"):
    if not status or status == resp.status:
        return
    resp.status, resp.status_at = status, utcnow()
    resp.closed_at = utcnow() if status in CLOSED else None
    _event(resp, "status", text, status=status, public=True, actor_name=actor_name)
    from . import dms
    dms.sync(db, resp)
    if inform:
        apps.notify_applicant(db, resp.form, resp, "app_status", {"nachricht": text})


def _advance(db, resp: FormResponse, index: int, actor_name: str) -> None:
    """Führt den Prozess ab Schritt `index` aus, bis ein Schritt auf Menschen wartet oder das Ende erreicht ist."""
    steps = steps_of(resp)
    guard = 0
    while index < len(steps):
        guard += 1
        if guard > 200:   # Schutz vor Endlosschleifen durch Rücksprünge in Automatiken
            _event(resp, "process", "Prozess angehalten: zu viele Schritte hintereinander (Schleife?)")
            return
        step = steps[index]
        if not evaluate(step.get("condition"), resp):
            resp.tasks.append(ApplicationTask(step_id=step["id"], name=step["name"], kind=step["type"], state="skipped",
                                              completed_at=utcnow(), comment="Bedingung nicht erfüllt"))
            index += 1
            continue
        if step.get("status") and resp.status not in CLOSED:
            _set_status(db, resp, step["status"])
        if step["type"] == "auto":
            task = ApplicationTask(step_id=step["id"], name=step["name"], kind="auto", state="done", outcome="done",
                                   completed_at=utcnow(), completed_by="Automatik")
            resp.tasks.append(task)
            db.flush()
            notes = _run_actions(db, resp, step, actor_name)
            task.comment = "\n".join(notes)
            index += 1
            continue
        if step["type"] == "payment" and step_amount(resp, step) <= 0:
            resp.tasks.append(ApplicationTask(step_id=step["id"], name=step["name"], kind="payment", state="done",
                                              outcome="done", completed_at=utcnow(), completed_by="Prozess",
                                              comment="Keine Gebühr fällig (Betrag 0)"))
            index += 1
            continue
        _create_task(db, resp, step)
        return
    _finish(db, resp)


def step_amount(resp: FormResponse, step: dict) -> int:
    from . import payments as pay
    if step.get("field"):
        cents = pay.parse_amount(str(resp.fields.get(step["field"], "")).replace("€", "").strip())
        if cents is not None:
            return cents
    return int(step.get("amount") or 0)


def _finish(db, resp: FormResponse) -> None:
    definition = version_definition(resp.process_version)
    _event(resp, "process", "Prozess abgeschlossen")
    if resp.status not in CLOSED:
        text = fill(definition.get("end_message", ""), resp)
        _set_status(db, resp, definition.get("end_status", "done"), text, inform=definition.get("end_inform", True))


def _create_task(db, resp: FormResponse, step: dict) -> ApplicationTask:
    now = utcnow()
    task = ApplicationTask(step_id=step["id"], name=step["name"], kind=step["type"], state="open")
    if step["type"] == "confirm":
        task.state = "waiting"
        task.assignee_id, task.group_id = resp.assignee_id, resp.group_id
        task.due_at = now + timedelta(days=step.get("due_days") or 7)
        task.data_json = json.dumps({"code": secrets.token_urlsafe(18)})
        resp.tasks.append(task)
        db.flush()
        sent = send_confirm(db, resp, task, step)
        _event(resp, "task", f"{step['name']}: Bestätigungslink " + ("per E-Mail verschickt" if sent else "konnte nicht verschickt werden (keine Adresse)"))
        return task
    if step["type"] == "payment":
        from . import payments as pay
        task.state = "waiting"
        task.assignee_id, task.group_id = resp.assignee_id, resp.group_id
        cents = step_amount(resp, step)
        p = pay.create(db, kind="step", subject_id=None, purpose=f"{step.get('label') or 'Gebühr'}: {resp.form.title} ({resp.ref_no})",
                       lines=[{"label": step.get("label") or "Gebühr", "qty": 1, "unit_cents": cents}],
                       payer_name=resp.name or "", payer_email=apps.applicant_email(resp.form, resp) or "",
                       methods=",".join(step.get("methods") or ["transfer"]), cost_center=step.get("cost_center", ""),
                       due_days=step.get("due_days") or 14, back_url=f"/a/{resp.track_token}")
        task.due_at = p.due_at
        resp.tasks.append(task)
        db.flush()
        p.subject_id = task.id
        task.data_json = json.dumps({"payment_id": p.id})
        sent = pay.request_payment(db, p)
        _event(resp, "task", f"{step['name']}: {pay.money(cents)} angefordert" + (" – Zahlungsaufforderung per E-Mail" if sent else ""),
               public=True)
        if step.get("message"):
            _event(resp, "message", fill(step["message"], resp), public=True)
        return task
    if step["type"] == "request" and step.get("compose") == "clerk":
        # Die Sachbearbeitung stellt die Nachforderung zusammen (Vorschlag aus dem Prozess), erst dann wartet der Prozess
        task.assignee_id, task.group_id = _resolve(db, resp, step)
        task.due_at = now + timedelta(days=step["compose_days"]) if step.get("compose_days") else None
        task.data_json = json.dumps({"compose": True})
        resp.tasks.append(task)
        db.flush()
        _event(resp, "task", f"{step['name']}: Nachforderung zusammenstellen – zuständig: {who(task)}")
        _notify_task(db, resp, task, step, "app_task")
        return task
    if step["type"] == "request":
        task.state = "waiting"
        task.assignee_id, task.group_id = resp.assignee_id, resp.group_id
        task.due_at = now + timedelta(days=step.get("due_days") or 14)
        resp.tasks.append(task)
        db.flush()
        qids = []
        for title in step.get("reopen", []):
            q = _question_by_title(resp.form, title)
            if q:
                qids.append(q["id"])
        create_request(db, resp, step.get("public_name") or step["name"], fill(step.get("message", ""), resp),
                       step.get("items", []), qids, task.due_at, "Prozess", task=task)
        return task
    task.assignee_id, task.group_id = _resolve(db, resp, step)
    task.due_at = now + timedelta(days=step["due_days"]) if step.get("due_days") else None
    resp.tasks.append(task)
    db.flush()
    _event(resp, "task", f"Neuer Arbeitsschritt: {step['name']} – zuständig: {who(task)}")
    _notify_task(db, resp, task, step, "app_task")
    return task


def _task_values(resp: FormResponse, task: ApplicationTask, step: dict | None) -> dict:
    return {**apps._common(resp.form, resp), "schritt": task.name,
            "anleitung": (step or {}).get("description", ""),
            "schritt_frist": to_local(task.due_at).strftime("%d.%m.%Y") if task.due_at else "keine",
            "aufgaben_link": f"{settings.portal_base_url}/tasks", "bearbeiter": who(task), "eskalation": ""}


def _notify_task(db, resp, task, step, key: str, extra: dict | None = None, targets: list[str] | None = None) -> int:
    count = 0
    for addr in targets if targets is not None else _addresses(db, task.assignee_id, task.group_id):
        subject, body = mailtpl.render(db, key, {**_task_values(resp, task, step), **(extra or {})})
        if notify.enqueue(db, addr, subject, body, key):
            count += 1
    return count


def complete(db, task: ApplicationTask, user: User, outcome: str, comment: str, checks: list[str],
             values: dict) -> str:
    """Erledigt eine Aufgabe oder Freigabe. Gibt eine Fehlermeldung zurück oder "" bei Erfolg."""
    resp = task.response
    step = step_of(task) or {}
    if task.state != "open":
        return "Dieser Schritt ist nicht mehr offen."
    if task.kind == "task":
        missing = [c for c in step.get("checklist", []) if c not in checks]
        if missing:
            return "Bitte zuerst alle Prüfpunkte abhaken: " + "; ".join(missing)
        fields, errors = {}, []
        for f in step.get("fields", []):
            raw = _s(values.get(f["key"]), 5000)
            if f["required"] and not raw:
                errors.append(f"„{f['label']}“ fehlt")
                continue
            if raw and f["type"] in ("number", "money"):
                num = _num(raw)
                if num is None:
                    errors.append(f"„{f['label']}“ ist keine Zahl")
                    continue
                fields[f["key"]] = round(num, 2) if f["type"] == "money" else (int(num) if num.is_integer() else num)
            elif raw and f["type"] == "select" and raw not in f["options"]:
                errors.append(f"„{f['label']}“: ungültige Auswahl")
            elif raw and f["type"] == "yesno" and raw not in ("Ja", "Nein"):
                errors.append(f"„{f['label']}“: bitte Ja oder Nein")
            else:
                fields[f["key"]] = raw
        if errors:
            return "Bitte prüfen: " + ", ".join(errors) + "."
        data = resp.fields
        data.update(fields)
        resp.fields_json = json.dumps(data, ensure_ascii=False)
        task.data_json = json.dumps({"checks": checks, "fields": fields}, ensure_ascii=False)
        outcome = "done"
    elif task.kind == "approval":
        if outcome not in ("approved", "rejected"):
            return "Bitte genehmigen oder ablehnen."
        if outcome == "rejected" and not comment:
            return "Bitte begründen Sie die Ablehnung."
        block = four_eyes_block(task, user)
        if block:
            return block
    else:
        return "Dieser Schritt wird nicht von der Sachbearbeitung erledigt."
    task.state, task.outcome, task.comment = "done", outcome, comment[:10000]
    task.completed_at, task.completed_by_id, task.completed_by = utcnow(), user.id, user.name
    label = {"done": "erledigt", "approved": "genehmigt", "rejected": "abgelehnt"}[outcome]
    _event(resp, "task", f"{task.name}: {label}" + (f"\n{comment}" if comment else ""), user)
    steps = steps_of(resp)
    index = next((n for n, s in enumerate(steps) if s["id"] == task.step_id), len(steps) - 1)
    if outcome == "rejected":
        target = step.get("on_reject", "end")
        if target == "end":
            _set_status(db, resp, step.get("reject_status", "rejected"), comment, inform=True, actor_name=user.name)
            _event(resp, "process", "Prozess nach Ablehnung beendet")
            return ""
        nxt = next((n for n, s in enumerate(steps) if s["id"] == target), index + 1)
    elif step.get("goto"):
        nxt = next((n for n, s in enumerate(steps) if s["id"] == step["goto"]), index + 1)
    else:
        nxt = index + 1
    _advance(db, resp, nxt, user.name)
    return ""


def claim(db, task: ApplicationTask, user: User) -> None:
    task.assignee_id = user.id
    _event(task.response, "task", f"{task.name}: übernommen von {user.name}", user)


def reassign(db, task: ApplicationTask, user_id: int | None, group_id: int | None, actor: User) -> None:
    task.assignee_id, task.group_id = user_id, group_id
    task.reminded_at = task.escalated_at = None
    db.flush()
    db.refresh(task)
    _event(task.response, "task", f"{task.name}: zuständig jetzt {who(task)}", actor)
    _notify_task(db, task.response, task, step_of(task), "app_task",
                 targets=[a for a in _addresses(db, user_id, group_id) if a != actor.email])


def set_task_due(task: ApplicationTask, due, actor: User) -> None:
    task.due_at, task.reminded_at, task.escalated_at = due, None, None
    _event(task.response, "task", f"{task.name}: Frist " + (to_local(due).strftime("%d.%m.%Y") if due else "keine"), actor)


def skip(db, task: ApplicationTask, actor: User, reason: str) -> None:
    """Schritt überspringen (z. B. Nachforderung hat sich erledigt) und den Prozess fortsetzen."""
    resp = task.response
    for req in resp.requests:
        if req.task_id == task.id and req.state == "open":
            req.state = "cancelled"
    task.state, task.completed_at, task.completed_by_id, task.completed_by = "skipped", utcnow(), actor.id, actor.name
    task.comment = reason[:5000]
    _event(resp, "task", f"{task.name}: übersprungen" + (f" – {reason}" if reason else ""), actor)
    steps = steps_of(resp)
    index = next((n for n, s in enumerate(steps) if s["id"] == task.step_id), len(steps) - 1)
    if resp.status == "query":
        _set_status(db, resp, "in_progress", actor_name=actor.name)
    _advance(db, resp, index + 1, actor.name)


def cancel_open(resp: FormResponse, reason: str) -> None:
    """Vorgang geschlossen: offene Schritte und Nachforderungen beenden."""
    for task in resp.tasks:
        if task.state in ("open", "waiting"):
            task.state, task.completed_at, task.comment = "cancelled", utcnow(), reason
    for req in resp.requests:
        if req.state == "open":
            req.state = "cancelled"


# --- Automatik -----------------------------------------------------------------------------

def _run_actions(db, resp: FormResponse, step: dict, actor_name: str) -> list[str]:
    notes = []
    for action in step.get("actions", []):
        kind = action["type"]
        if kind == "status":
            _set_status(db, resp, action["status"], fill(action.get("message", ""), resp, actor_name),
                        inform=action.get("inform", False))
            notes.append(f"Status: {apps.status_label(action['status'])}")
        elif kind == "assign":
            resp.assignee_id, resp.group_id = action.get("user_id"), action.get("group_id")
            db.flush()
            db.refresh(resp)
            _event(resp, "assign", f"Zuständig: {apps._common(resp.form, resp)['zustaendig']}")
            notes.append("Zuständigkeit geändert")
        elif kind == "pdf":
            doc = create_document(db, resp, action["title"], fill(action.get("body", ""), resp, actor_name),
                                  public=action.get("public", False))
            notes.append(f"Dokument „{doc.name}“ erzeugt")
            if action.get("send"):
                to = apps.applicant_email(resp.form, resp)
                if to:
                    subject = f"{doc.name} zu Ihrem Antrag {resp.ref_no}"
                    body = fill("Guten Tag {name},\n\nanbei erhalten Sie das Dokument „" + doc.name + "“ zu Ihrem Antrag "
                                "„{titel}“ ({aktenzeichen}).\n\nDen Stand Ihres Antrags sehen Sie hier:\n{statuslink}\n",
                                resp) + "\n" + mailtpl.common_vars()["fusszeile"]
                    notify.enqueue(db, to, subject, body, "app_document", attachments=[_doc_attachment(resp, doc)])
                    notes.append("an Antragsteller:in gesendet")
        elif kind == "mail":
            targets = []
            if action["to"] == "applicant":
                targets = [apps.applicant_email(resp.form, resp)]
            elif action["to"] == "case":
                targets = apps._staff_addresses(db, resp.form, resp)
            elif action.get("email"):
                targets = [action["email"]]
            subject = " ".join(fill(action.get("subject") or "{titel} – {aktenzeichen}", resp, actor_name).split())
            body = fill(action.get("body", ""), resp, actor_name) + "\n\n" + mailtpl.common_vars()["fusszeile"]
            attachments = None
            if action.get("attach") == "application":
                attachments = [{"filename": f"{resp.ref_no}.pdf", "mime": "application/pdf",
                                "content_b64": base64.b64encode(apps.pdf(resp.form, resp)).decode("ascii")}]
            elif action.get("attach") == "documents" and resp.documents:
                attachments = [_doc_attachment(resp, d) for d in resp.documents]
            sent = sum(1 for t in targets if t and notify.enqueue(db, t, subject, body, "app_auto", attachments=attachments))
            if sent:
                _event(resp, "message" if action["to"] == "applicant" else "note", f"{subject}\n\n{body.strip()}",
                       public=action["to"] == "applicant")
            notes.append(f"Mail an {MAIL_TARGETS[action['to']]}" + ("" if sent else " (nicht gesendet: keine Adresse)"))
    return notes


def documents_dir(resp: FormResponse):
    return fm.files_dir(resp.form_id, resp.id) / "docs"


def _doc_attachment(resp: FormResponse, doc: ApplicationDocument) -> dict:
    data = (documents_dir(resp) / doc.file).read_bytes()
    return {"filename": re.sub(r"[^\w.-]+", "_", f"{resp.ref_no}-{doc.name}")[:120] + ".pdf", "mime": "application/pdf",
            "content_b64": base64.b64encode(data).decode("ascii")}


def create_document(db, resp: FormResponse, title: str, body: str, public: bool) -> ApplicationDocument:
    data = document_pdf(resp, title, body)
    target = documents_dir(resp)
    target.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(8) + ".pdf"
    (target / name).write_bytes(data)
    doc = ApplicationDocument(name=title[:200], file=name, size=len(data), public=public)
    resp.documents.append(doc)
    _event(resp, "document", f"Dokument erzeugt: {title}" + (" (für Antragsteller:in abrufbar)" if public else ""),
           public=public)
    db.flush()
    return doc


def document_pdf(resp: FormResponse, title: str, body: str) -> bytes:
    """Schlichter Bescheid im Briefformat: Absender, Anschrift, Datum/Aktenzeichen, Betreff, Text."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import branding

    brand = branding.load()
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica", fontSize=10.5, leading=14.5, spaceAfter=7)
    small = ParagraphStyle("s", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"), spaceAfter=0)
    head = ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=17, spaceAfter=10)
    latin = apps._latin

    def para(text, st=base):
        return Paragraph(escape(latin(text)).replace("\n", "<br/>"), st)

    story = [para(brand["name"], ParagraphStyle("org", parent=base, fontName="Helvetica-Bold", fontSize=12)),
             Spacer(1, 10 * mm)]
    address = "\n".join(x for x in (resp.name, apps.applicant_email(resp.form, resp)) if x) or "–"
    meta = Table([[para(address), para(f"Datum: {to_local(utcnow()).strftime('%d.%m.%Y')}\n"
                                       f"Aktenzeichen: {resp.ref_no}\nAntrag vom: {to_local(resp.created_at).strftime('%d.%m.%Y')}", small)]],
                 colWidths=[105 * mm, 60 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [meta, Spacer(1, 12 * mm), para(f"{title}: {resp.form.title}", head)]
    for block in re.split(r"\n\s*\n", body.strip()):
        if block.strip():
            story.append(para(block.strip()))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(20 * mm, 12 * mm, latin(f"{resp.ref_no} · {title}")[:110])
        canvas.drawRightString(190 * mm, 12 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22 * mm, rightMargin=20 * mm, topMargin=20 * mm,
                            bottomMargin=22 * mm, title=latin(f"{title} {resp.ref_no}"), author=latin(brand["name"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# --- Double-Opt-in ------------------------------------------------------------------------

def confirm_link(resp: FormResponse, task: ApplicationTask) -> str:
    return f"{apps.track_link(resp)}/confirm/{task.data.get('code', '')}"


def send_confirm(db, resp: FormResponse, task: ApplicationTask, step: dict | None = None) -> bool:
    to = apps.applicant_email(resp.form, resp)
    if not to:
        return False
    step = step or step_of(task) or {}
    values = {**apps._common(resp.form, resp), "name": resp.name or to, "bestaetigen_link": confirm_link(resp, task),
              "nachricht": fill(step.get("message", ""), resp),
              "bestaetigen_bis": to_local(task.due_at).strftime("%d.%m.%Y") if task.due_at else ""}
    subject, body = mailtpl.render(db, "app_confirm", values)
    return notify.enqueue(db, to, subject, body, "app_confirm")


def open_confirm(resp: FormResponse) -> ApplicationTask | None:
    return next((t for t in resp.tasks if t.kind == "confirm" and t.state == "waiting"), None)


def confirm(db, resp: FormResponse, code: str) -> str:
    """Link aus der Mail angeklickt: „ok“, „done“ (schon bestätigt) oder „invalid“."""
    for task in resp.tasks:
        if task.kind != "confirm" or not code or not secrets.compare_digest(str(task.data.get("code", "")), code):
            continue
        if task.state != "waiting":
            return "done" if task.state == "done" else "invalid"
        task.state, task.outcome, task.completed_at = "done", "done", utcnow()
        task.completed_by = resp.name or resp.email or "Antragsteller:in"
        _event(resp, "task", "E-Mail-Adresse bestätigt", public=True, actor_name=task.completed_by)
        steps = steps_of(resp)
        index = next((n for n, s in enumerate(steps) if s["id"] == task.step_id), len(steps) - 1)
        _advance(db, resp, index + 1, "")
        return "ok"
    return "invalid"


# --- Nachforderungen -----------------------------------------------------------------------

def requested_text(resp: FormResponse, req: ApplicationRequest) -> str:
    lines = []
    for item in req.items:
        if fm.TYPES.get(item["type"], ("", "", False))[2]:
            lines.append(f"– {item.get('title') or fm.TYPES[item['type']][0]}" + (" (Datei)" if item["type"] == "file" else ""))
    for qid in req.reopen:
        q = next((x for x in fm.questions(fm.schema(resp.form)) if x["id"] == qid), None)
        if q:
            lines.append(f"– {q.get('title') or 'Angabe'} (bitte prüfen/korrigieren)")
    return "\n".join(lines) or "– siehe Nachricht"


def _request_values(resp, req) -> dict:
    return {**apps._common(resp.form, resp), "name": resp.name or apps.applicant_email(resp.form, resp),
            "nachricht": req.message, "angefordert": requested_text(resp, req),
            "nachreichen_bis": f"bis zum {to_local(req.due_at).strftime('%d.%m.%Y')}" if req.due_at else "möglichst bald"}


def create_request(db, resp: FormResponse, title: str, message: str, items: list, reopen: list[str], due_at,
                   actor_name: str, task: ApplicationTask | None = None, set_query: bool = True) -> ApplicationRequest:
    if task is not None and task.state == "open":   # zusammengestellte Nachforderung: jetzt auf die Antwort warten
        task.state = "waiting"
    req = ApplicationRequest(title=title[:200] or "Nachforderung", message=message[:10000],
                             schema_json=json.dumps(clean_request_items(items), ensure_ascii=False),
                             reopen_json=json.dumps(reopen[:40]), due_at=due_at, created_by=actor_name,
                             task_id=task.id if task else None)
    resp.requests.append(req)
    db.flush()
    _event(resp, "request", f"Nachforderung: {req.title}\n{requested_text(resp, req)}" + (f"\n\n{message}" if message else ""),
           public=True, actor_name=actor_name)
    if set_query and resp.status not in CLOSED:
        _set_status(db, resp, "query", actor_name=actor_name)
    to = apps.applicant_email(resp.form, resp)
    if to:
        subject, body = mailtpl.render(db, "app_request", _request_values(resp, req))
        notify.enqueue(db, to, subject, body, "app_request", reply_to=resp.route_email or None)
    return req


def open_requests(resp: FormResponse) -> list[ApplicationRequest]:
    return [r for r in resp.requests if r.state == "open"]


def reopen_items(resp: FormResponse, req: ApplicationRequest) -> list[dict]:
    """Die zur Korrektur geöffneten Antragsfragen (mit ihrer ursprünglichen Konfiguration)."""
    by_id = {q["id"]: q for q in fm.questions(fm.schema(resp.form))}
    return [by_id[qid] for qid in req.reopen if qid in by_id]


async def answer_request(db, resp: FormResponse, req: ApplicationRequest, data, files) -> dict:
    """Prüft und speichert die Antwort der antragstellenden Person. Gibt Fehler je Feld zurück."""
    items = req.items + reopen_items(resp, req)
    answers, errors, uploads = fm.validate(items, data, files)
    if errors:
        return errors
    stored = {}
    if uploads:
        target = fm.files_dir(resp.form_id, resp.id) / f"req{req.id}"
        stored = await _store(target, uploads)
    answers.update(stored)   # Dateien liegen unter forms/<id>/<antrag>/req<nr>/
    req.answers_json = json.dumps(answers, ensure_ascii=False)
    req.state, req.answered_at = "answered", utcnow()
    from . import dms
    dms.store_request(db, resp, req)
    who_name = resp.name or resp.email or "Antragsteller:in"
    _event(resp, "reply", f"Nachgereicht: {req.title}", public=True, actor_name=who_name)
    lines = []
    for item in items:
        if fm.TYPES.get(item["type"], ("", "", False))[2]:
            lines.append(f"{item.get('title') or 'Angabe'}:\n  {fm.display(item, answers.get(item['id'])) or '–'}")
    task = db.get(ApplicationTask, req.task_id) if req.task_id else None
    targets = apps._staff_addresses(db, resp.form, resp) + (_addresses(db, task.assignee_id, task.group_id) if task else [])
    last = [t for t in resp.tasks if t.state == "done" and t.completed_by_id]
    if last:   # wer zuletzt am Vorgang gearbeitet hat, erfährt es auch
        targets += _addresses(db, last[-1].completed_by_id, None)
    for addr in dict.fromkeys(targets):
        subject, body = mailtpl.render(db, "app_request_answered", {**apps._common(resp.form, resp),
                                                                     "von": fm.respondent(resp), "antworten": "\n".join(lines)})
        notify.enqueue(db, addr, subject, body, "app_request_answered")
    if task and task.state == "waiting":
        task.state, task.outcome, task.completed_at, task.completed_by = "done", "done", utcnow(), who_name
        if resp.status == "query":
            _set_status(db, resp, "in_progress", "Angaben nachgereicht", actor_name=who_name)
        steps = steps_of(resp)
        index = next((n for n, s in enumerate(steps) if s["id"] == task.step_id), len(steps) - 1)
        _advance(db, resp, index + 1, "")
    elif resp.status == "query" and not open_requests(resp):
        _set_status(db, resp, "in_progress", "Angaben nachgereicht", actor_name=who_name)
    return {}


async def _store(target, uploads: dict) -> dict:
    import pathlib
    stored = {}
    for qid, files in uploads.items():
        entries = []
        for f in files:
            target.mkdir(parents=True, exist_ok=True)
            ext = pathlib.Path(f.filename).suffix.lower()[:11]
            name = secrets.token_hex(8) + (ext if re.match(r"^\.[a-z0-9]{1,10}$", ext) else "")
            size = 0
            with open(target / name, "wb") as out:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    out.write(chunk)
            entries.append({"file": name, "name": pathlib.Path(f.filename).name[:200], "size": size,
                            "type": (f.content_type or "")[:100]})
        stored[qid] = entries
    return stored


def remind_request(db, resp: FormResponse, req: ApplicationRequest) -> bool:
    to = apps.applicant_email(resp.form, resp)
    if not to:
        return False
    subject, body = mailtpl.render(db, "app_request_reminder", _request_values(resp, req))
    req.reminded_at = utcnow()
    return notify.enqueue(db, to, subject, body, "app_request_reminder")


# --- Aufgabenlisten -------------------------------------------------------------------------

def my_tasks(db, user: User) -> list[ApplicationTask]:
    """Offene Schritte für die Person: direkt zugewiesen oder über eine Gruppe (noch nicht übernommen)."""
    groups = _group_ids(db, user)
    q = select(ApplicationTask).join(FormResponse).where(ApplicationTask.state == "open", FormResponse.closed_at.is_(None))
    q = q.where(or_(ApplicationTask.assignee_id == user.id,
                    (ApplicationTask.group_id.in_(groups or [-1])) & ApplicationTask.assignee_id.is_(None)))
    tasks = db.scalars(q).all()
    return sorted(tasks, key=lambda t: (t.due_at is None, t.due_at or utcnow(), t.id))


def task_count(db, user: User) -> int:
    from sqlalchemy import func
    groups = _group_ids(db, user)
    q = select(func.count(ApplicationTask.id)).join(FormResponse).where(
        ApplicationTask.state == "open", FormResponse.closed_at.is_(None),
        or_(ApplicationTask.assignee_id == user.id,
            (ApplicationTask.group_id.in_(groups or [-1])) & ApplicationTask.assignee_id.is_(None)))
    return db.scalar(q) or 0


def waiting_requests(db, user: User) -> list[ApplicationRequest]:
    visible = {r.id for r in db.scalars(apps.inbox_query(db, user).where(FormResponse.closed_at.is_(None)))}
    if not visible:
        return []
    reqs = db.scalars(select(ApplicationRequest).where(ApplicationRequest.state == "open",
                                                       ApplicationRequest.response_id.in_(visible))).all()
    return sorted(reqs, key=lambda r: (r.due_at is None, r.due_at or utcnow()))


def progress(resp: FormResponse) -> list[dict]:
    """Fortschritt für die Statusseite: nur Schritte mit öffentlichem Namen."""
    out = []
    by_step: dict[str, ApplicationTask] = {}
    for t in resp.tasks:
        by_step[t.step_id] = t
    for step in steps_of(resp):
        if not step.get("public_name"):
            continue
        task = by_step.get(step["id"])
        if task is None:
            state = "todo"
        elif task.state in ("open", "waiting"):
            state = "current"
        elif task.state == "done":
            state = "done"
        else:
            continue  # übersprungen oder abgebrochen
        if state == "todo" and resp.closed_at:
            continue
        out.append({"name": step["public_name"], "state": state, "waiting": task is not None and task.state == "waiting"})
    if out and resp.closed_at:
        out.append({"name": apps.status_label(resp.status), "state": "done", "waiting": False})
    return out


def processes_for_select(db) -> list[Process]:
    return [p for p in db.scalars(select(Process).order_by(Process.name)).all() if p.current]


def usage(db, process: Process) -> dict:
    forms = db.scalars(select(Form).where(Form.process_id == process.id).order_by(Form.title)).all()
    version_ids = [v.id for v in process.versions]
    running = 0
    if version_ids:
        running = len(db.scalars(select(FormResponse.id).where(FormResponse.process_version_id.in_(version_ids),
                                                               FormResponse.closed_at.is_(None))).all())
    return {"forms": forms, "running": running}


def responses_of(db, process: Process) -> list[FormResponse]:
    """Alle Anträge, die nach diesem Prozess laufen oder liefen (bzw. deren Formular ihn nutzt)."""
    version_ids = [v.id for v in process.versions] or [-1]
    form_ids = [f.id for f in db.scalars(select(Form).where(Form.process_id == process.id))] or [-1]
    return db.scalars(select(FormResponse).where(FormResponse.ref_no.is_not(None), or_(
        FormResponse.process_version_id.in_(version_ids),
        (FormResponse.process_version_id.is_(None)) & FormResponse.form_id.in_(form_ids)))).all()


def question_titles(db, process: Process) -> list[str]:
    """Fragen aller Antragsformulare, die den Prozess nutzen (für Bedingungen und Platzhalter im Editor)."""
    titles: list[str] = []
    for form in db.scalars(select(Form).where(Form.process_id == process.id)):
        for q in fm.questions(fm.schema(form)):
            t = (q.get("title") or "").strip()
            if t and t not in titles:
                titles.append(t)
    return titles


def request_templates(db) -> list[RequestTemplate]:
    return db.scalars(select(RequestTemplate).order_by(RequestTemplate.name)).all()


def send_reminders() -> int:
    """Hintergrunddienst: überfällige Schritte erinnern bzw. eskalieren, an offene Nachforderungen erinnern."""
    count = 0
    now = utcnow()
    with SessionLocal() as db:
        tasks = db.scalars(select(ApplicationTask).where(ApplicationTask.state == "open", ApplicationTask.due_at.is_not(None),
                                                         ApplicationTask.due_at < now)).all()
        for task in tasks:
            resp, step = task.response, step_of(task) or {}
            if resp.closed_at:
                continue
            if task.reminded_at is None:
                count += _notify_task(db, resp, task, step, "app_task_overdue")
                task.reminded_at = now
            esc = step.get("escalate") or {}
            if task.escalated_at is None and (esc.get("user_id") or esc.get("group_id")) \
                    and now >= task.due_at + timedelta(days=esc.get("after_days") or 0):
                targets = _addresses(db, esc.get("user_id"), esc.get("group_id"))
                before = who(task)
                note = "Sie wurden als Vertretung bzw. Leitung informiert."
                if esc.get("reassign"):
                    task.assignee_id, task.group_id = esc.get("user_id"), esc.get("group_id")
                    note = "Die Aufgabe wurde Ihnen zur Erledigung übertragen."
                count += _notify_task(db, resp, task, step, "app_task_overdue",
                                      {"bearbeiter": before, "eskalation": note}, targets=targets)
                task.escalated_at = now
                _event(resp, "task", f"{task.name}: Frist überschritten – eskaliert" + (" und neu zugewiesen" if esc.get("reassign") else ""))
        for task in db.scalars(select(ApplicationTask).where(ApplicationTask.kind == "confirm",
                                                             ApplicationTask.state == "waiting")).all():
            resp, step = task.response, step_of(task) or {}
            if resp.closed_at:
                continue
            half = task.created_at + (task.due_at - task.created_at) / 2 if task.due_at else None
            if step.get("remind", True) and task.reminded_at is None and half and now >= half and task.due_at > now:
                if send_confirm(db, resp, task, step):
                    _event(resp, "task", "Erinnerung: Bestätigungslink erneut verschickt")
                    count += 1
                task.reminded_at = now
            if task.due_at and now >= task.due_at and task.escalated_at is None:
                task.escalated_at = now
                if step.get("on_expire") == "withdraw":
                    task.state, task.completed_at, task.comment = "cancelled", now, "nicht bestätigt"
                    _set_status(db, resp, "withdrawn", "Die E-Mail-Adresse wurde nicht rechtzeitig bestätigt; der Antrag wird nicht bearbeitet.",
                                inform=False)
                    cancel_open(resp, "nicht bestätigt")
                else:
                    count += _notify_task(db, resp, task, step, "app_task_overdue",
                                          {"eskalation": "Die antragstellende Person hat ihre E-Mail-Adresse nicht bestätigt."},
                                          targets=apps._staff_addresses(db, resp.form, resp))
                    _event(resp, "task", "E-Mail-Adresse nicht innerhalb der Frist bestätigt – Zuständige informiert")
        reqs = db.scalars(select(ApplicationRequest).where(ApplicationRequest.state == "open", ApplicationRequest.due_at.is_not(None),
                                                           ApplicationRequest.due_at < now, ApplicationRequest.reminded_at.is_(None))).all()
        for req in reqs:
            if not req.response.closed_at and remind_request(db, req.response, req):
                _event(req.response, "request", f"Erinnerung an die Nachforderung „{req.title}“ gesendet")
                count += 1
            req.reminded_at = now
        db.commit()
    return count



# --- Zahlungsschritt ---------------------------------------------------------------------------

def payment_of_task(db, task: ApplicationTask):
    from .db import Payment
    pid = task.data.get("payment_id") if task.data else None
    return db.get(Payment, pid) if pid else None


def _on_step_payment(db, p, event: str) -> None:
    task = db.get(ApplicationTask, p.subject_id) if p.subject_id else None
    if task is None or task.kind != "payment" or task.state != "waiting":
        return
    resp = task.response
    step = step_of(task) or {}
    if event == "paid":
        from . import payments as pay
        task.state, task.outcome, task.completed_at = "done", "done", utcnow()
        task.completed_by = f"Zahlung ({pay.METHODS.get(p.method, ('',))[0]})"
        _event(resp, "task", f"{task.name}: bezahlt ({pay.money(p.amount_cents)})", public=True, actor_name="Zahlung")
        steps = steps_of(resp)
        index = next((n for n, s in enumerate(steps) if s["id"] == task.step_id), len(steps) - 1)
        _advance(db, resp, index + 1, "")
    elif event == "overdue":
        if step.get("on_expire") == "withdraw":
            from . import payments as pay
            pay.cancel(db, p, "Prozess", "Zahlfrist abgelaufen", fire=False)
            task.state, task.completed_at, task.comment = "cancelled", utcnow(), "nicht bezahlt"
            _set_status(db, resp, "withdrawn", "Die Gebühr wurde nicht rechtzeitig bezahlt; der Antrag wird nicht weiter bearbeitet.",
                        inform=True)
            cancel_open(resp, "nicht bezahlt")
        else:
            _notify_task(db, resp, task, step, "app_task_overdue",
                         {"eskalation": "Die Gebühr ist nicht innerhalb der Frist eingegangen."},
                         targets=apps._staff_addresses(db, resp.form, resp))
            _event(resp, "task", f"{task.name}: Zahlfrist abgelaufen – Zuständige informiert")


def _can_manage_step_payment(db, user, p) -> bool:
    task = db.get(ApplicationTask, p.subject_id) if p.subject_id else None
    return task is not None and apps.access(db, user, task.response) >= 2


def _step_payment_link(p) -> str:
    with SessionLocal() as db:
        task = db.get(ApplicationTask, p.subject_id) if p.subject_id else None
        return f"/forms/{task.response.form_id}/applications/{task.response_id}#schritt" if task else ""


def _register_payments() -> None:
    from . import payments as pay
    pay.register("step", event=_on_step_payment, can_manage=_can_manage_step_payment, link=_step_payment_link)


_register_payments()
