"""Online-Anträge: Formulare mit Aktenzeichen, Status, Zuständigkeit, Fristen, PDF und Antragskatalog.

Ein Formular wird zum Antrag, wenn seine Art „application“ ist. Beim Absenden
  1. bekommt der Antrag ein Aktenzeichen (Präfix-Jahr-laufende Nummer, z. B. GEW-2026-00042),
  2. wird nach den Weiterleitungsregeln einer Person, Gruppe oder einem Funktionspostfach zugeordnet,
  3. erhält eine Bearbeitungsfrist und einen geheimen Link, unter dem die antragstellende Person den
     Stand verfolgt, auf Rückfragen antwortet oder den Antrag zurückzieht,
  4. gehen Eingangsbestätigung und Hinweis an die Zuständigen raus – auf Wunsch mit dem Antrag als PDF.
Jede Änderung (Status, Nachricht, Notiz, Zuweisung, Frist) landet im Verlauf.
"""

import base64
import hashlib
import io
import json
import re
import secrets
from datetime import timedelta

from sqlalchemy import or_, select

from . import forms as fm, mailtpl, notify
from .config import settings
from .db import (
    ApplicationEvent, ApplicationTask, Form, FormResponse, GroupMember, SessionLocal, User, get_settings, to_local, utcnow,
)
from .planning import EMAIL_RE

STATUSES = {
    "received": ("Eingegangen", "secondary", "fa-inbox"),
    "in_progress": ("In Bearbeitung", "primary", "fa-gears"),
    "query": ("Rückfrage", "warning", "fa-circle-question"),
    "approved": ("Genehmigt", "success", "fa-circle-check"),
    "rejected": ("Abgelehnt", "danger", "fa-circle-xmark"),
    "done": ("Erledigt", "success", "fa-flag-checkered"),
    "withdrawn": ("Zurückgezogen", "dark", "fa-rotate-left"),
}
CLOSED = {"approved", "rejected", "done", "withdrawn"}
PREFIX_RE = re.compile(r"^[A-Z0-9]{1,10}$")


def is_application(form: Form | None) -> bool:
    return bool(form and form.kind == "application")


def status_label(key: str) -> str:
    return STATUSES.get(key, (key or "–",))[0]


def track_link(resp: FormResponse) -> str:
    return f"{settings.portal_base_url}/a/{resp.track_token}"


def staff_link(resp: FormResponse) -> str:
    return f"{settings.portal_base_url}/forms/{resp.form_id}/applications/{resp.id}"


# --- Aktenzeichen, Weiterleitung, Prüfsumme -------------------------------------------

def next_ref(form: Form) -> str:
    """Nächstes Aktenzeichen; der Zähler beginnt jedes Jahr neu. (SQLite schreibt seriell – keine Doppelvergabe.)"""
    year = to_local(utcnow()).year
    if form.app_seq_year != year:
        form.app_seq_year, form.app_seq = year, 0
    form.app_seq += 1
    prefix = form.app_prefix or f"A{form.id}"
    return f"{prefix}-{year}-{form.app_seq:05d}"


def routing_rules(form: Form) -> list[dict]:
    try:
        data = json.loads(form.app_routing_json or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def clean_rules(raw: list, items: list[dict]) -> list[dict]:
    questions = {q["id"] for q in fm.questions(items)}
    rules = []
    for r in raw[:50] if isinstance(raw, list) else []:
        if not isinstance(r, dict) or r.get("question") not in questions:
            continue
        value = str(r.get("value") or "").strip()[:500]
        user_id = int(r["user_id"]) if str(r.get("user_id") or "").isdigit() else None
        group_id = int(r["group_id"]) if str(r.get("group_id") or "").isdigit() else None
        email = str(r.get("email") or "").strip().lower()[:255]
        if email and not EMAIL_RE.match(email):
            email = ""
        if value and (user_id or group_id or email):
            rules.append({"question": r["question"], "value": value, "user_id": user_id, "group_id": group_id,
                          "email": email})
    return rules


def route(form: Form, answers: dict) -> tuple[int | None, int | None, str]:
    """Zuständigkeit: erste passende Regel (Antwort enthält den Wert), sonst die Vorgabe des Antrags."""
    for rule in routing_rules(form):
        given = answers.get(rule["question"])
        values = given if isinstance(given, list) else [given]
        if any(str(v).strip().lower() == rule["value"].lower() for v in values if v is not None):
            return rule.get("user_id"), rule.get("group_id"), rule.get("email") or ""
    return form.app_assignee_id, form.app_group_id, form.app_mailbox or ""


def checksum(resp: FormResponse) -> str:
    """SHA-256 über Aktenzeichen, Eingang und Antworten – belegt später, dass nichts verändert wurde."""
    payload = json.dumps({"ref": resp.ref_no, "form": resp.form_id, "eingang": resp.created_at.isoformat(timespec="seconds"),
                          "antworten": resp.answers}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- Zugriff im Portal -------------------------------------------------------------------

def _group_ids(db, user: User) -> list[int]:
    return list(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user.id)))


def access(db, user: User, resp: FormResponse) -> int:
    """0 = kein Zugriff, 1 = ansehen, 2 = bearbeiten (Status, Nachrichten, Notizen, Zuweisung)."""
    level = fm.access_level(db, resp.form, user)
    groups = _group_ids(db, user)
    if level >= fm.INVITE or resp.assignee_id == user.id or (resp.group_id and resp.group_id in groups):
        return 2
    # Wer einen Arbeitsschritt im Vorgang hat (offen oder erledigt), arbeitet mit
    if any(t.assignee_id == user.id or (t.group_id and t.group_id in groups) for t in resp.tasks):
        return 2
    return 1 if level >= fm.VIEW else 0


def inbox_query(db, user: User):
    """Alle Anträge, die die Person sehen darf: eigene Formulare, Freigaben, zugewiesen (direkt oder Gruppe)."""
    q = select(FormResponse).join(Form).where(Form.kind == "application", FormResponse.ref_no.is_not(None))
    if user.is_admin:
        return q
    groups = _group_ids(db, user)
    shared_forms = [f.id for f, _lvl in fm.shared_with(db, user)]
    task_cases = select(ApplicationTask.response_id).where(
        or_(ApplicationTask.assignee_id == user.id, ApplicationTask.group_id.in_(groups or [-1])))
    return q.where(or_(Form.owner_id == user.id, FormResponse.assignee_id == user.id,
                       FormResponse.group_id.in_(groups or [-1]), Form.id.in_(shared_forms or [-1]),
                       FormResponse.id.in_(task_cases)))


# --- Mails ------------------------------------------------------------------------------

def _staff_addresses(db, form: Form, resp: FormResponse) -> list[str]:
    out: list[str] = []

    def add(addr):
        addr = (addr or "").strip().lower()
        if addr and EMAIL_RE.match(addr) and addr not in out:
            out.append(addr)
    if resp.assignee and resp.assignee.active:
        add(resp.assignee.email)
    if resp.group:
        for member in resp.group.members:
            if member.active:
                add(member.email)
    add(resp.route_email)
    if not out and form.owner and form.owner.active:   # niemand zugeordnet: an die Besitzer:in
        add(form.owner.email)
    if form.notify:
        for addr in re.split(r"[,;\s]+", form.notify_to or ""):
            add(addr)
    return out


def applicant_email(form: Form, resp: FormResponse) -> str:
    return resp.email or fm.respondent_email(form, resp.answers)


def _pdf_attachment(form: Form, resp: FormResponse) -> list[dict] | None:
    if not form.app_pdf:
        return None
    return [{"filename": f"{resp.ref_no}.pdf", "mime": "application/pdf",
             "content_b64": base64.b64encode(pdf(form, resp)).decode("ascii")}]


def _common(form: Form, resp: FormResponse) -> dict:
    return {"titel": form.title, "aktenzeichen": resp.ref_no, "status": status_label(resp.status),
            "status_link": track_link(resp), "link": staff_link(resp),
            "zeitpunkt": to_local(resp.created_at).strftime("%d.%m.%Y, %H:%M Uhr"),
            "frist": to_local(resp.due_at).strftime("%d.%m.%Y") if resp.due_at else "",
            "zustaendig": ", ".join(x for x in (resp.assignee.name if resp.assignee else "",
                                                 f"Gruppe {resp.group.name}" if resp.group else "",
                                                 resp.route_email) if x) or "nicht zugeordnet"}


def notify_applicant(db, form: Form, resp: FormResponse, key: str, extra: dict | None = None,
                     attach_pdf: bool = False) -> bool:
    to = applicant_email(form, resp)
    if not to:
        return False
    values = {**_common(form, resp), "name": resp.name or to, **(extra or {})}
    subject, body = mailtpl.render(db, key, values)
    staff = _staff_addresses(db, form, resp)
    return notify.enqueue(db, to, subject, body, key, attachments=_pdf_attachment(form, resp) if attach_pdf else None,
                          reply_to=resp.route_email or (staff[0] if staff else None))


def notify_staff(db, form: Form, resp: FormResponse, key: str, extra: dict | None = None, attach_pdf: bool = False,
                 skip: str = "") -> int:
    count = 0
    attachments = _pdf_attachment(form, resp) if attach_pdf else None
    for addr in _staff_addresses(db, form, resp):
        if addr == skip:
            continue
        subject, body = mailtpl.render(db, key, {**_common(form, resp), "von": fm.respondent(resp), **(extra or {})})
        if notify.enqueue(db, addr, subject, body, key, attachments=attachments):
            count += 1
    return count


# --- Ablauf ------------------------------------------------------------------------------

def _event(resp: FormResponse, kind: str, text: str = "", actor: User | None = None, status: str = "",
           public: bool = False, actor_name: str = "") -> ApplicationEvent:
    ev = ApplicationEvent(kind=kind, text=text[:20000], status=status, public=public,
                          actor_id=actor.id if actor else None, actor_name=actor_name or (actor.name if actor else ""))
    resp.events.append(ev)
    return ev


def on_submit(db, form: Form, resp: FormResponse) -> None:
    """Neuer Antrag: Aktenzeichen, Zuständigkeit, Frist, Verfolgungslink, Prüfsumme, Mails."""
    resp.ref_no = next_ref(form)
    resp.status, resp.status_at = "received", utcnow()
    resp.assignee_id, resp.group_id, resp.route_email = route(form, resp.answers)
    resp.due_at = utcnow() + timedelta(days=max(form.app_deadline_days or 0, 0)) if form.app_deadline_days else None
    resp.track_token = secrets.token_urlsafe(24)
    resp.checksum = checksum(resp)
    if not resp.email:
        resp.email = applicant_email(form, resp)
    _event(resp, "created", "Antrag eingegangen", status="received", public=True,
           actor_name=resp.name or resp.email or "Antragsteller:in")
    db.flush()
    db.refresh(resp)
    info = "\n".join(x for x in (form.app_info, f"Gebühr: {form.app_fee}" if form.app_fee else "",
                                 f"Übliche Bearbeitungsdauer: {form.app_duration}" if form.app_duration else "") if x)
    notify_applicant(db, form, resp, "app_received", {"antworten": fm.answers_text(form, resp), "hinweise": info},
                     attach_pdf=True)
    notify_staff(db, form, resp, "app_new", {"antworten": fm.answers_text(form, resp) if form.notify_answers else ""},
                 attach_pdf=True)
    from . import workflow
    workflow.start(db, resp)


def set_status(db, resp: FormResponse, status: str, message: str, actor: User, inform: bool) -> None:
    if status not in STATUSES:
        return
    resp.status, resp.status_at = status, utcnow()
    resp.closed_at = utcnow() if status in CLOSED else None
    _event(resp, "status", message, actor, status=status, public=True)
    if status in CLOSED:
        from . import workflow
        workflow.cancel_open(resp, f"Vorgang abgeschlossen ({status_label(status)})")
    if inform:
        notify_applicant(db, resp.form, resp, "app_status", {"nachricht": message},
                         attach_pdf=False)


def message(db, resp: FormResponse, text: str, actor: User) -> None:
    _event(resp, "message", text, actor, public=True)
    notify_applicant(db, resp.form, resp, "app_status", {"nachricht": text})


def note(resp: FormResponse, text: str, actor: User) -> None:
    _event(resp, "note", text, actor)


def assign(db, resp: FormResponse, user_id: int | None, group_id: int | None, actor: User) -> None:
    resp.assignee_id, resp.group_id = user_id, group_id
    db.flush()
    db.refresh(resp)
    who = _common(resp.form, resp)["zustaendig"]
    _event(resp, "assign", f"Zuständig: {who}", actor)
    resp.overdue_notified_at = None
    notify_staff(db, resp.form, resp, "app_assigned", {"absender": actor.name}, skip=actor.email)


def set_due(resp: FormResponse, due, actor: User) -> None:
    resp.due_at = due
    resp.overdue_notified_at = None
    _event(resp, "due", "Frist: " + (to_local(due).strftime("%d.%m.%Y") if due else "keine"), actor)


def applicant_reply(db, resp: FormResponse, text: str) -> None:
    _event(resp, "reply", text, public=True, actor_name=resp.name or resp.email or "Antragsteller:in")
    if resp.status == "query":
        resp.status, resp.status_at = "in_progress", utcnow()
        _event(resp, "status", "Antwort auf Rückfrage eingegangen", status="in_progress", public=True,
               actor_name="System")
    notify_staff(db, resp.form, resp, "app_reply", {"nachricht": text})


def withdraw(db, resp: FormResponse) -> None:
    resp.status, resp.status_at, resp.closed_at = "withdrawn", utcnow(), utcnow()
    _event(resp, "status", "Antrag von der antragstellenden Person zurückgezogen", status="withdrawn", public=True,
           actor_name=resp.name or resp.email or "Antragsteller:in")
    from . import workflow
    workflow.cancel_open(resp, "Antrag zurückgezogen")
    notify_staff(db, resp.form, resp, "app_reply", {"nachricht": "Der Antrag wurde zurückgezogen."})


def send_overdue_reminders() -> int:
    """Hintergrunddienst: einmal je Frist an die Zuständigen erinnern, wenn ein offener Antrag überfällig ist."""
    count = 0
    with SessionLocal() as db:
        due = db.scalars(select(FormResponse).where(
            FormResponse.ref_no.is_not(None), FormResponse.due_at.is_not(None), FormResponse.due_at < utcnow(),
            FormResponse.closed_at.is_(None), FormResponse.overdue_notified_at.is_(None))).all()
        for resp in due:
            count += notify_staff(db, resp.form, resp, "app_overdue")
            resp.overdue_notified_at = utcnow()
        db.commit()
    return count


# --- PDF ---------------------------------------------------------------------------------

def _latin(text: str) -> str:
    """Standardschriften im PDF kennen nur Windows-1252 – unbekannte Zeichen ersetzen."""
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def pdf(form: Form, resp: FormResponse) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import branding

    brand = branding.load()
    styles = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=13)
    small = ParagraphStyle("s", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=4)
    p = lambda text, st=base: Paragraph(escape(_latin(str(text))).replace("\n", "<br/>"), st)  # noqa: E731

    created = to_local(resp.created_at)
    story = [p(f"{brand['name']} · Online-Antrag", small), Spacer(1, 4 * mm), p(form.title, title)]
    meta = [["Aktenzeichen", resp.ref_no or "–"], ["Eingang", created.strftime("%d.%m.%Y, %H:%M:%S Uhr")],
            ["Antragsteller:in", fm.respondent(resp)], ["Status bei Ausstellung", status_label(resp.status)]]
    meta_table = Table([[p(a, bold), p(b)] for a, b in meta], colWidths=[45 * mm, 120 * mm])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f4f7"))]))
    story += [meta_table, Spacer(1, 6 * mm)]
    rows = []
    answers = resp.answers
    for item in fm.schema(form):
        if item.get("type") in ("heading", "subheading", "pagebreak"):
            if item.get("title"):
                rows.append([p(item["title"], bold), ""])
            continue
        if not fm.TYPES.get(item.get("type"), ("", "", False))[2]:
            continue
        value = answers.get(item["id"])
        if item["type"] == "file" and isinstance(value, list):
            shown = "\n".join(f"{f.get('name')} ({max(int(f.get('size', 0)) // 1024, 1)} kB)" for f in value if isinstance(f, dict))
        else:
            shown = fm.display(item, value)
        rows.append([p(item.get("title") or fm.TYPES[item["type"]][0], bold), p(shown or "–")])
    if rows:
        table = Table(rows, colWidths=[60 * mm, 105 * mm], repeatRows=0)
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
        story.append(table)
    story += [Spacer(1, 8 * mm),
              p(f"Prüfsumme (SHA-256 über Aktenzeichen, Eingang und Angaben): {resp.checksum or checksum(resp)}", small)]
    # Der geheime Statuslink steht bewusst nicht im PDF – es landet in der E-Akte und bei weiteren Stellen.

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(20 * mm, 12 * mm, _latin(f"{resp.ref_no} · {form.title}")[:110])
        canvas.drawRightString(190 * mm, 12 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=20 * mm, title=_latin(f"{resp.ref_no} {form.title}"),
                            author=_latin(brand["name"]), subject="Online-Antrag")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def catalog(db) -> list[Form]:
    forms = db.scalars(select(Form).where(Form.kind == "application", Form.app_catalog.is_(True),
                                          Form.public_token.is_not(None), Form.active.is_(True))
                       .order_by(Form.app_category, Form.title)).all()
    return [f for f in forms if fm.is_open(f)]


def mail_ready(db) -> bool:
    return notify.mail_configured(get_settings(db))
