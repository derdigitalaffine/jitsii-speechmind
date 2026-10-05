"""Gebühren beim Absenden von Formularen und Online-Anträgen (siehe payments.py).

Einstellung je Formular (Form.fee_json): Grundbetrag und Regeln nach Antworten – „wenn Antwort = …, dann + Betrag“
oder „je eingegebener Zahl × Betrag“ (z. B. je Hund). Bei Anträgen auf Wunsch: Der Antrag gilt erst nach der
Zahlung als eingegangen (Status „Zahlung offen“; Zuständige und Prozess starten erst danach).
"""

import json

from . import applications as apps, forms as fm, payments as pay
from .db import Form, FormResponse, SessionLocal, utcnow

DEFAULT = {"enabled": False, "label": "Gebühr", "base": 0, "rules": [], "require": False,
           "methods": "paypal,transfer", "days": 14, "cost_center": ""}
OPS = {"eq": "ist gleich / enthält", "each": "je Anzahl (Zahl × Betrag)"}


def config(form: Form) -> dict:
    try:
        data = json.loads(form.fee_json or "{}")
    except ValueError:
        data = {}
    return {**DEFAULT, **(data if isinstance(data, dict) else {})}


def clean(raw: dict, form: Form) -> dict:
    qids = {q["id"]: q for q in fm.questions(fm.schema(form))}
    rules = []
    for r in (raw.get("rules") or [])[:30]:
        if not isinstance(r, dict) or r.get("q") not in qids:
            continue
        cents = pay.parse_amount(r["amount"]) if "amount" in r else (r.get("cents") if isinstance(r.get("cents"), int) else 0)
        if not cents:
            continue
        rules.append({"q": r["q"], "op": r.get("op") if r.get("op") in OPS else "eq",
                      "value": " ".join(str(r.get("value", "")).split())[:200],
                      "cents": cents, "label": " ".join(str(r.get("label", "")).split())[:120]})
    methods = ",".join(m for m in ("paypal", "transfer", "cash") if m in (raw.get("methods") or [])) or "transfer"
    try:
        days = max(1, min(90, int(raw.get("days") or 14)))
    except (TypeError, ValueError):
        days = 14
    return {"enabled": bool(raw.get("enabled")), "label": " ".join(str(raw.get("label") or "Gebühr").split())[:120],
            "base": pay.parse_amount(raw.get("base", "")) or 0, "rules": rules, "require": bool(raw.get("require")),
            "methods": methods, "days": days, "cost_center": " ".join(str(raw.get("cost_center", "")).split())[:120]}


def lines(form: Form, answers: dict) -> list[dict]:
    cfg = config(form)
    if not cfg["enabled"]:
        return []
    out = []
    if cfg["base"]:
        out.append({"label": cfg["label"], "qty": 1, "unit_cents": cfg["base"]})
    titles = {q["id"]: q.get("title") or "Angabe" for q in fm.questions(fm.schema(form))}
    for r in cfg["rules"]:
        v = answers.get(r["q"])
        if r["op"] == "each":
            try:
                n = int(float(str(v).replace(",", ".")))
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                out.append({"label": r["label"] or titles.get(r["q"], ""), "qty": n, "unit_cents": r["cents"]})
        else:
            hit = (r["value"] in v) if isinstance(v, list) else (str(v or "").strip().lower() == r["value"].lower())
            if hit:
                out.append({"label": r["label"] or f"{titles.get(r['q'], '')}: {r['value']}", "qty": 1, "unit_cents": r["cents"]})
    return out


def on_submit(db, form: Form, resp: FormResponse, back_url: str = ""):
    """Zahlung zur Einsendung anlegen (oder None, wenn nichts zu zahlen ist)."""
    items = lines(form, resp.answers)
    if not items or sum(i["qty"] * i["unit_cents"] for i in items) <= 0:
        return None
    cfg = config(form)
    kind = "application" if apps.is_application(form) else "form"
    p = pay.create(db, kind=kind, subject_id=resp.id, purpose=f"{cfg['label']}: {form.title}" + (f" ({resp.ref_no})" if resp.ref_no else ""),
                   lines=items, payer_name=resp.name or "", payer_email=resp.email or fm.respondent_email(form, resp.answers) or "",
                   methods=cfg["methods"], cost_center=cfg["cost_center"], due_days=cfg["days"], back_url=back_url,
                   ref=f"{resp.ref_no}-G" if resp.ref_no else "")
    return p


def payment_of(db, resp: FormResponse):
    from sqlalchemy import select

    from .db import Payment
    return db.scalar(select(Payment).where(Payment.kind.in_(("application", "form")), Payment.subject_id == resp.id)
                     .order_by(Payment.id.desc()))


# --- Rückmeldungen der Zahlung ----------------------------------------------------------------

def _on_payment(db, p, event: str) -> None:
    resp = db.get(FormResponse, p.subject_id) if p.subject_id else None
    if resp is None:
        return
    if p.kind == "form":
        return
    if event == "paid":
        apps._event(resp, "payment", f"Gebühr bezahlt ({pay.money(p.amount_cents)}, {pay.METHODS.get(p.method, ('',))[0]})",
                    public=True, actor_name="Zahlung")
        if resp.status == "payment":
            release(db, resp)
        else:
            from . import dms
            dms.sync(db, resp)
    elif event == "overdue" and resp.status == "payment":
        pay.cancel(db, p, "Portal", "Zahlfrist abgelaufen", fire=False)
        resp.status, resp.status_at, resp.closed_at = "withdrawn", utcnow(), utcnow()
        apps._event(resp, "status", "Die Gebühr wurde nicht rechtzeitig bezahlt; der Antrag wird nicht bearbeitet.",
                    status="withdrawn", public=True)
        apps.notify_applicant(db, resp.form, resp, "app_status",
                              {"nachricht": "Die Gebühr ist nicht rechtzeitig eingegangen. Ihr Antrag wird deshalb nicht bearbeitet."})
        from . import dms
        dms.sync(db, resp)


def release(db, resp: FormResponse) -> None:
    """Bezahlt: Antrag gilt jetzt als eingegangen – Zuständige informieren, Prozess starten."""
    from . import dms, workflow
    form = resp.form
    resp.status, resp.status_at = "received", utcnow()
    apps._event(resp, "status", "Antrag eingegangen (Gebühr bezahlt)", status="received", public=True)
    apps.notify_staff(db, form, resp, "app_new", {"antworten": fm.answers_text(form, resp) if form.notify_answers else ""},
                      attach_pdf=True)
    workflow.start(db, resp)
    dms.sync(db, resp)


def _can_manage(db, user, p) -> bool:
    resp = db.get(FormResponse, p.subject_id) if p.subject_id else None
    if resp is None:
        return False
    if p.kind == "form":
        return fm.access_level(db, resp.form, user) >= fm.EDIT
    return apps.access(db, user, resp) >= 2


def _link(p) -> str:
    with SessionLocal() as db:
        resp = db.get(FormResponse, p.subject_id) if p.subject_id else None
        if resp is None:
            return ""
        if p.kind == "form":
            return f"/forms/{resp.form_id}/responses/{resp.id}"
        return f"/forms/{resp.form_id}/applications/{resp.id}"


pay.register("application", event=_on_payment, can_manage=_can_manage, link=_link)
pay.register("form", event=_on_payment, can_manage=_can_manage, link=_link)
