"""Zahlungen: PayPal Checkout (Orders API v2, serverseitig), Überweisung und Barzahlung.

Andere Module (Ressourcen, Anträge, Formulare, Prozessschritte) legen mit create() eine Zahlung an und melden
mit register() eine Rückruf-Funktion an, die bei „bezahlt“, „erstattet“, „storniert“ und „Frist abgelaufen“
aufgerufen wird. Die zahlende Person erreicht ihre Zahlseite über /pay/<token>; PayPal-Skripte werden nie im
Browser geladen (Weiterleitung zu PayPal und zurück, Abbuchung auf dem Server, Webhook als Absicherung).
"""

import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import timedelta
from typing import Callable

import httpx
from sqlalchemy import func, select, update

from . import mailtpl, notify
from .config import settings
from .db import Payment, PaymentReceipt, PaymentRefund, SessionLocal, get_settings, to_local, utcnow
from .security import decrypt

log = logging.getLogger("portal.payments")

STATUSES = {
    "open": ("offen", "warning", "fa-hourglass-half"),
    "pending": ("bei PayPal", "info", "fa-spinner"),
    "paid": ("bezahlt", "success", "fa-circle-check"),
    "partially_refunded": ("teilweise erstattet", "secondary", "fa-rotate-left"),
    "refunded": ("erstattet", "secondary", "fa-rotate-left"),
    "cancelled": ("storniert", "dark", "fa-ban"),
}
METHODS = {"paypal": ("PayPal", "fa-brands fa-paypal"), "transfer": ("Überweisung", "fa-solid fa-building-columns"),
           "cash": ("bar", "fa-solid fa-coins"), "free": ("kostenlos", "fa-solid fa-gift")}
KINDS = {"resource_deposit": "Kaution (Ressourcen)", "resource": "Ressourcenbuchung", "resource_club": "Sammelrechnung (Ressourcen)", "application": "Antrag", "form": "Formular", "step": "Prozessschritt",
         "other": "Sonstiges"}
API = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
MAX_CENTS = 10_000_000   # 100.000 € je Zahlung

# kind -> {"event": callable(db, payment, event), "can_manage": callable(db, user, payment) -> bool,
#          "link": callable(payment) -> str (interne Ansicht des Vorgangs)}
_HANDLERS: dict[str, dict[str, Callable]] = {}


def register(kind: str, *, event: Callable | None = None, can_manage: Callable | None = None,
             link: Callable | None = None) -> None:
    _HANDLERS[kind] = {"event": event, "can_manage": can_manage, "link": link}


def _fire(db, p: Payment, event: str) -> None:
    h = _HANDLERS.get(p.kind, {}).get("event")
    if h:
        try:
            h(db, p, event)
        except Exception:  # noqa: BLE001  (eine Zahlung darf nie an einem Folgefehler scheitern)
            log.exception("Rückruf %s für Zahlung %s fehlgeschlagen", event, p.ref)


def can_manage(db, user, p: Payment) -> bool:
    if user is None:
        return False
    if user.can("payments"):
        return True
    h = _HANDLERS.get(p.kind, {}).get("can_manage")
    return bool(h and h(db, user, p))


def subject_link(p: Payment) -> str:
    h = _HANDLERS.get(p.kind, {}).get("link")
    return h(p) if h else ""


# --- Beträge ------------------------------------------------------------------------------

def parse_amount(text) -> int | None:
    """„12,50“, „12.50 €“, „1.250,00“ → Cent. None bei ungültiger Eingabe."""
    s = re.sub(r"[€\s]|EUR", "", str(text or ""), flags=re.I)
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        return None
    cents = round(float(s) * 100)
    return cents if 0 <= cents <= MAX_CENTS else None


def money(cents: int | None) -> str:
    cents = int(cents or 0)
    sign = "−" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", ".") + f",{rest:02d} €"


def _value(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def items(p: Payment) -> list[dict]:
    try:
        data = json.loads(p.items_json or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _log(p: Payment, text: str, who: str = "") -> None:
    try:
        entries = json.loads(p.log_json or "[]")
    except ValueError:
        entries = []
    entries.append({"at": utcnow().isoformat(timespec="seconds"), "who": who, "text": text[:500]})
    p.log_json = json.dumps(entries[-100:], ensure_ascii=False)


def log_entries(p: Payment) -> list[dict]:
    try:
        return json.loads(p.log_json or "[]")
    except ValueError:
        return []


def open_cents(p: Payment) -> int:
    return p.amount_cents - p.refunded_cents if p.status in ("paid", "partially_refunded") else p.amount_cents


# --- Anlegen und Zahlarten --------------------------------------------------------------------

def paypal_ready(cfg: dict) -> bool:
    return cfg.get("paypal_enabled") == "1" and bool(cfg.get("paypal_client_id")) and bool(cfg.get("paypal_secret_enc"))


def transfer_ready(cfg: dict) -> bool:
    return cfg.get("pay_transfer") == "1" and bool(cfg.get("pay_iban"))


def available(cfg: dict, p: Payment) -> list[str]:
    """Zahlarten, die die zahlende Person selbst wählen kann (bar wird nur von der Verwaltung erfasst)."""
    allowed = set((p.methods or "").split(","))
    out = []
    if "paypal" in allowed and paypal_ready(cfg):
        out.append("paypal")
    if "transfer" in allowed and transfer_ready(cfg):
        out.append("transfer")
    if "cash" in allowed:
        out.append("cash")
    return out


def _next_ref(db, prefix: str) -> str:
    year = to_local(utcnow()).year
    head = f"{prefix}-{year}-"
    n = db.scalar(select(func.count(Payment.id)).where(Payment.ref.like(head + "%"))) or 0
    while True:
        n += 1
        ref = f"{head}{n:05d}"
        if db.scalar(select(Payment.id).where(Payment.ref == ref)) is None:
            return ref


def create(db, *, kind: str, purpose: str, lines: list[dict], subject_id: int | None = None,
           payer_name: str = "", payer_email: str = "", methods: str = "paypal,transfer",
           cost_center: str = "", due_days: int | None = None, back_url: str = "", deposit_cents: int = 0,
           ref: str = "") -> Payment:
    """Zahlung anlegen. lines: [{"label", "qty", "unit_cents"}] – der Betrag ist die Summe."""
    cfg = get_settings(db)
    clean, total = [], 0
    for line in lines:
        qty = max(0, int(line.get("qty", 1) or 0))
        unit = int(line.get("unit_cents", 0) or 0)
        cents = int(line.get("cents", qty * unit))
        clean.append({"label": str(line.get("label", ""))[:200], "qty": qty, "unit_cents": unit, "cents": cents})
        total += cents
    total = max(0, min(total, MAX_CENTS))
    prefix = re.sub(r"[^A-Z0-9]", "", (cfg.get("pay_prefix") or "Z").upper())[:6] or "Z"
    days = due_days if due_days is not None else int(cfg.get("pay_days") or 14)
    p = Payment(ref=ref or _next_ref(db, prefix), token=secrets.token_urlsafe(24), kind=kind if kind in KINDS else "other",
                subject_id=subject_id, purpose=purpose[:255], items_json=json.dumps(clean, ensure_ascii=False),
                amount_cents=total, deposit_cents=min(max(0, deposit_cents), total), methods=methods,
                cost_center=cost_center[:120], payer_name=payer_name[:255], payer_email=payer_email[:255],
                back_url=back_url[:500], due_at=utcnow() + timedelta(days=days) if days else None)
    if total == 0:
        p.status, p.method, p.paid_at = "paid", "free", utcnow()
        _log(p, "Kostenlos – keine Zahlung nötig.")
    else:
        _log(p, f"Angelegt über {money(total)}.")
    db.add(p)
    db.flush()
    return p


def link(p: Payment) -> str:
    return f"{settings.portal_base_url}/pay/{p.token}"


def _mail_values(db, p: Payment) -> dict:
    cfg = get_settings(db)
    lines = "\n".join(f"– {i['label']}{' × ' + str(i['qty']) if i['qty'] != 1 else ''}: {money(i['cents'])}"
                      for i in items(p))
    transfer = ""
    if "transfer" in available(cfg, p):
        transfer = (f"Per Überweisung: {cfg.get('pay_recipient') or ''}, IBAN {cfg.get('pay_iban')}"
                    f"{', BIC ' + cfg['pay_bic'] if cfg.get('pay_bic') else ''}, Verwendungszweck {p.ref}")
    return {"name": p.payer_name or p.payer_email, "zweck": p.purpose, "betrag": money(p.amount_cents),
            "positionen": lines, "verwendungszweck": p.ref, "zahl_link": link(p),
            "zahlbar_bis": to_local(p.due_at).strftime("%d.%m.%Y") if p.due_at else "–",
            "ueberweisung": transfer, "zahlart": METHODS.get(p.method, ("", ""))[0],
            "erstattet": money(p.refunded_cents)}


def send_mail(db, p: Payment, key: str, extra: dict | None = None) -> bool:
    if not p.payer_email:
        return False
    subject, body = mailtpl.render(db, key, {**_mail_values(db, p), **(extra or {})})
    attachments = []
    if key in ("pay_receipt", "pay_refund"):
        import base64
        kind = "received" if key == "pay_receipt" else "refunded"
        receipt = db.scalar(select(PaymentReceipt).where(PaymentReceipt.payment_id == p.id, PaymentReceipt.kind == kind).order_by(PaymentReceipt.id.desc()))
        if receipt:
            attachments.append({"filename": f"{receipt.ref}.pdf", "mime": "application/pdf", "content_b64": base64.b64encode(receipt_pdf(receipt)).decode("ascii")})
    return notify.enqueue(db, p.payer_email, subject, body, key, attachments=attachments)


def request_payment(db, p: Payment) -> bool:
    """Zahlungsaufforderung mit Link verschicken (bei kostenlosen Zahlungen nichts)."""
    if p.status != "open":
        return False
    return send_mail(db, p, "pay_request")


# --- Statuswechsel ---------------------------------------------------------------------------

def mark_paid(db, p: Payment, method: str, who: str = "", note: str = "", capture_id: str = "", occurred_at=None) -> bool:
    if p.status in ("paid", "partially_refunded", "refunded"):
        return False
    p.status, p.method, p.paid_at = "paid", method, occurred_at or utcnow()
    if capture_id:
        p.paypal_capture_id = capture_id
    _log(p, f"Bezahlt ({METHODS.get(method, (method,))[0]}){': ' + note if note else ''}.", who)
    if occurred_at:
        _log(p, f"Tatsächlich erhalten am {to_local(occurred_at).strftime('%d.%m.%Y %H:%M')}; nachträglich erfasst.", who)
    make_receipt(db, p, "received", p.amount_cents, method, who, note, occurred_at, "received")
    send_mail(db, p, "pay_receipt")
    _fire(db, p, "paid")
    return True


def cancel(db, p: Payment, who: str = "", note: str = "", fire: bool = True) -> bool:
    if p.status not in ("open", "pending"):
        return False
    p.status = "cancelled"
    _log(p, f"Storniert{': ' + note if note else ''}.", who)
    if fire:
        _fire(db, p, "cancelled")
    return True


def _complete_refund(db, p, intent):
    """Exactly once, including when a webhook races with a status check."""
    applied = db.execute(update(PaymentRefund).where(PaymentRefund.id == intent.id,
                        PaymentRefund.completed_at.is_(None)).values(status="completed", completed_at=utcnow()))
    if not applied.rowcount:
        db.refresh(p)
        return
    db.execute(update(Payment).where(Payment.id == p.id).values(
        refunded_cents=Payment.refunded_cents + intent.cents, active_refund=""))
    db.refresh(p)
    p.status = "refunded" if p.refunded_cents >= p.amount_cents else "partially_refunded"
    _log(p, f"{money(intent.cents)} erstattet ({METHODS.get(intent.method, (intent.method,))[0]}), Auftrag {intent.request_id}. {intent.note}", intent.actor)
    if intent.occurred_at:
        _log(p, f"Tatsächliche Auszahlung: {to_local(intent.occurred_at).strftime('%d.%m.%Y %H:%M')}; nachträglich erfasst.", intent.actor)
    make_receipt(db, p, "refunded", intent.cents, intent.method, intent.actor, intent.note, intent.occurred_at, intent.request_id)
    send_mail(db, p, "pay_refund", {"erstattet": money(intent.cents), "grund": intent.note})
    if intent.fire_event or p.kind == "resource_deposit":
        _fire(db, p, "refunded")


def _refund_result(db, p, intent, result):
    intent.provider_id = str(result.get("id") or intent.provider_id)[:64]
    amount = result.get("amount") or {}
    if amount and (amount.get("currency_code") != p.currency or parse_amount(amount.get("value")) != intent.cents):
        intent.status, intent.error = "unknown", "Abweichender Betrag oder Währung beim Anbieter."
        return intent.error
    status = result.get("status")
    if status == "COMPLETED" and intent.provider_id:
        _complete_refund(db, p, intent)
        return ""
    if status in ("FAILED", "CANCELLED"):
        intent.status, p.active_refund = "failed", ""
        intent.error = f"PayPal-Status: {status}"
        return "PayPal hat die Erstattung nicht ausgeführt."
    intent.status = "pending" if status == "PENDING" else "unknown"
    return "Erstattung noch nicht bestätigt. Bitte den gespeicherten Auftrag abgleichen; keine weitere Auszahlung veranlassen."


def reconcile_refund(db, p: Payment) -> str:
    intent = db.scalar(select(PaymentRefund).where(PaymentRefund.request_id == p.active_refund)) if p.active_refund else None
    if intent is None:
        return "Kein offener Erstattungsauftrag."
    try:
        if intent.provider_id:
            result = _api(db, "GET", f"/v2/payments/refunds/{intent.provider_id}")
        elif utcnow() - intent.created_at < timedelta(hours=24):
            # Repeat exactly the persisted payload, never a newly generated ID.
            result = _api(db, "POST", f"/v2/payments/captures/{p.paypal_capture_id}/refund",
                          {"amount": {"value": _value(intent.cents), "currency_code": p.currency},
                           "note_to_payer": (intent.note or f"Erstattung {p.ref}")[:255]}, request_id=intent.request_id)
        else:
            return "Unklarer Auftrag ohne PayPal-ID älter als 24 Stunden: in PayPal prüfen; keine automatische Wiederholung."
    except PayPalError as exc:
        intent.error = str(exc)[:500]
        return f"Abgleich nicht möglich: {exc}"
    return _refund_result(db, p, intent, result)


def refund(db, p: Payment, cents: int, who: str = "", note: str = "", fire: bool = True,
           method: str = "", occurred_at=None) -> str:
    """Persist intent before contacting provider; uncertain results stay reserved."""
    db.refresh(p)
    if p.active_refund:
        return "Ein Erstattungsauftrag ist noch offen. Bitte zuerst dessen Status abgleichen."
    if p.status not in ("paid", "partially_refunded"):
        return "Nur bezahlte Zahlungen lassen sich erstatten."
    left = p.amount_cents - p.refunded_cents
    if cents <= 0 or cents > left:
        return f"Erstattbar sind höchstens {money(left)}."
    actual_method = method or p.method
    if actual_method not in ("paypal", "cash", "transfer"):
        return "Ungültiger Erstattungsweg."
    if method and method != p.method and not note.strip():
        return "Ein abweichender Erstattungsweg benötigt eine Begründung."
    if actual_method == "paypal" and not p.paypal_capture_id:
        return "Keine PayPal-Transaktion für diese Zahlung vorhanden."
    request_id = str(uuid.uuid4())
    locked = db.execute(update(Payment).where(Payment.id == p.id, Payment.active_refund == "",
                        Payment.refunded_cents == p.refunded_cents).values(active_refund=request_id))
    if not locked.rowcount:
        db.rollback()
        return "Zahlung wurde gleichzeitig geändert. Bitte neu laden."
    intent = PaymentRefund(payment_id=p.id, request_id=request_id, cents=cents, method=actual_method,
                           note=note[:300], actor=who[:255], fire_event=fire, occurred_at=occurred_at)
    db.add(intent)
    db.commit()  # durable idempotency key before a potentially successful external side effect
    if actual_method == "paypal":
        try:
            result = _api(db, "POST", f"/v2/payments/captures/{p.paypal_capture_id}/refund",
                          {"amount": {"value": _value(cents), "currency_code": p.currency},
                           "note_to_payer": (intent.note or f"Erstattung {p.ref}")[:255]}, request_id=request_id)
        except PayPalError as exc:
            intent.status, intent.error = ("failed" if exc.definite else "unknown"), str(exc)[:500]
            if exc.definite:
                p.active_refund = ""
            db.commit()
            return f"PayPal-Erstattung nicht bestätigt: {exc}. Auftrag gespeichert; bitte abgleichen."
        message = _refund_result(db, p, intent, result)
        db.commit()
        return message
    _complete_refund(db, p, intent)
    return ""


def make_receipt(db, p, kind, cents, method, actor="", note="", occurred_at=None, event=""):
    key = f"{p.id}:{event or kind}"
    found = db.scalar(select(PaymentReceipt).where(PaymentReceipt.event_key == key))
    if found:
        return found
    count = db.scalar(select(func.count(PaymentReceipt.id)).where(PaymentReceipt.payment_id == p.id)) or 0
    receipt = PaymentReceipt(payment_id=p.id, event_key=key, ref=f"{p.ref}-B{count+1:03d}", kind=kind,
                             cents=cents, method=method, occurred_at=occurred_at or utcnow(),
                             snapshot_json=json.dumps({"payer": p.payer_name, "purpose": p.purpose,
                                                       "actor": actor, "note": note}, ensure_ascii=False))
    db.add(receipt)
    db.flush()
    return receipt


def receipts(db, p):
    return list(db.scalars(select(PaymentReceipt).where(PaymentReceipt.payment_id == p.id).order_by(PaymentReceipt.id)))


def receipt_pdf(receipt):
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    import io
    data = json.loads(receipt.snapshot_json)
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    title = {"received": "Zahlungseingangsquittung", "refunded": "Rückzahlungsquittung", "retained": "Kautionseinbehalt"}.get(receipt.kind, "Zahlungsbeleg")
    rows = [Paragraph(escape(title), styles["Title"]), Spacer(1, 8*mm)]
    for label, value in [("Belegnummer", receipt.ref), ("Vorgang", data.get("purpose", "")),
                         ("Zahlende Person", data.get("payer", "")), ("Betrag", money(receipt.cents)),
                         ("Zahlweg", METHODS.get(receipt.method, (receipt.method,))[0]),
                         ("Tatsächlicher Zeitpunkt", to_local(receipt.occurred_at).strftime("%d.%m.%Y %H:%M")),
                         ("Erfasst am", to_local(receipt.created_at).strftime("%d.%m.%Y %H:%M")),
                         ("Erfasst durch", data.get("actor", "")), ("Bemerkung", data.get("note", ""))]:
        rows.extend([Paragraph(f"<b>{escape(label)}:</b> {escape(str(value))}", styles["BodyText"]), Spacer(1, 3*mm)])
    SimpleDocTemplate(buf, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm).build(rows)
    return buf.getvalue()


# --- PayPal ----------------------------------------------------------------------------------

class PayPalError(Exception):
    def __init__(self, message, definite=False):
        super().__init__(message)
        self.definite = definite


_token: dict = {"key": "", "value": "", "until": 0.0}
_token_lock = threading.Lock()


def _base(cfg: dict) -> str:
    return (os.environ.get("PAYPAL_API_BASE") or API.get(cfg.get("paypal_mode"), API["sandbox"])).rstrip("/")


def _access_token(cfg: dict) -> str:
    key = f"{cfg.get('paypal_mode')}:{cfg.get('paypal_client_id')}:{cfg.get('paypal_secret_enc')}"
    with _token_lock:
        if _token["key"] == key and _token["until"] > time.monotonic() + 60:
            return _token["value"]
        try:
            r = httpx.post(f"{_base(cfg)}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                           auth=(cfg.get("paypal_client_id", ""), decrypt(cfg.get("paypal_secret_enc"))), timeout=20)
        except httpx.HTTPError as exc:
            raise PayPalError(f"PayPal nicht erreichbar ({exc.__class__.__name__}).") from exc
        if r.status_code != 200:
            raise PayPalError("Anmeldung bei PayPal fehlgeschlagen – Client-ID, Secret und Modus (Sandbox/Live) prüfen.")
        data = r.json()
        _token.update(key=key, value=data.get("access_token", ""), until=time.monotonic() + int(data.get("expires_in", 300)))
        return _token["value"]


def _api(db, method: str, path: str, payload: dict | None = None, request_id: str = "") -> dict:
    cfg = get_settings(db)
    if not paypal_ready(cfg):
        raise PayPalError("PayPal ist nicht eingerichtet.")
    headers = {"Authorization": f"Bearer {_access_token(cfg)}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    try:
        r = httpx.request(method, f"{_base(cfg)}{path}", json=payload, headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        raise PayPalError(f"PayPal nicht erreichbar ({exc.__class__.__name__}).") from exc
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    if r.status_code >= 400:
        detail = (data.get("details") or [{}])[0].get("issue") or data.get("name") or data.get("message") or r.status_code
        debug = str(data.get("debug_id") or "")[:100]
        raise PayPalError(str(detail) + (f" (Referenz {debug})" if debug else ""), definite=400 <= r.status_code < 500 and r.status_code != 409 and str(detail) not in ("DUPLICATE_REQUEST_ID", "DUPLICATE_REQUEST"))
    return data


def test_connection(db) -> str:
    _token["until"] = 0
    _access_token(get_settings(db))
    return "Verbindung zu PayPal steht."


def start_paypal(db, p: Payment) -> str:
    """PayPal-Bestellung anlegen und die Adresse zurückgeben, zu der die Person weitergeleitet wird."""
    from . import branding
    if p.status not in ("open", "pending"):
        raise PayPalError("Diese Zahlung ist nicht mehr offen.")
    back = f"{settings.portal_base_url}/pay/{p.token}"
    order = _api(db, "POST", "/v2/checkout/orders", {
        "intent": "CAPTURE",
        "purchase_units": [{"reference_id": p.ref, "custom_id": str(p.id), "invoice_id": f"{p.ref}-{secrets.token_hex(3)}",
                            "description": (p.purpose or p.ref)[:127],
                            "amount": {"currency_code": p.currency, "value": _value(p.amount_cents)}}],
        "payment_source": {"paypal": {"experience_context": {
            "return_url": back + "/return", "cancel_url": back + "/cancel", "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING", "locale": "de-DE", "brand_name": branding.load()["name"][:127]}}},
    }, request_id=f"order-{p.token}-{int(time.time() // 600)}")
    approve = next((lnk["href"] for lnk in order.get("links", []) if lnk.get("rel") in ("payer-action", "approve")), "")
    if not order.get("id") or not approve.startswith("https://") and not os.environ.get("PAYPAL_API_BASE"):
        raise PayPalError("PayPal hat keine Bestellung angelegt.")
    p.paypal_order_id, p.status, p.method = order["id"], "pending", "paypal"
    _log(p, f"Weiterleitung zu PayPal (Bestellung {order['id']}).")
    return approve


def _capture_from(order: dict) -> tuple[str, str, int]:
    """(Capture-ID, Status, Betrag in Cent) aus einer Bestellung."""
    for unit in order.get("purchase_units", []):
        for cap in (unit.get("payments") or {}).get("captures", []):
            amount = parse_amount((cap.get("amount") or {}).get("value", "")) or 0
            return cap.get("id", ""), cap.get("status", ""), amount
    return "", "", 0


def finish_paypal(db, p: Payment, order_id: str) -> str:
    """Nach der Rückkehr von PayPal abbuchen. Gibt den neuen Status-Text zurück ("" = bezahlt)."""
    if p.status in ("paid", "partially_refunded", "refunded"):
        return ""
    if not order_id or order_id != p.paypal_order_id:
        return "Die Rückmeldung von PayPal passt nicht zu dieser Zahlung."
    try:
        order = _api(db, "POST", f"/v2/checkout/orders/{order_id}/capture", {}, request_id=f"capture-{order_id}")
    except PayPalError as exc:
        if "ORDER_ALREADY_CAPTURED" not in str(exc):
            _log(p, f"Abbuchung fehlgeschlagen: {exc}")
            p.status = "open"
            return f"Die Zahlung wurde nicht abgeschlossen ({exc}). Bitte erneut versuchen oder eine andere Zahlart wählen."
        order = _api(db, "GET", f"/v2/checkout/orders/{order_id}")
    cap_id, cap_status, cents = _capture_from(order)
    if cents != p.amount_cents:
        _log(p, f"Betrag von PayPal ({money(cents)}) weicht ab – bitte prüfen.")
        return "Der Betrag stimmt nicht – die Verwaltung prüft die Zahlung."
    if cap_status == "COMPLETED":
        mark_paid(db, p, "paypal", "PayPal", capture_id=cap_id)
        return ""
    p.paypal_capture_id = cap_id
    _log(p, f"PayPal meldet Status {cap_status or order.get('status')}.")
    return "PayPal prüft die Zahlung noch. Sie bekommen eine Bestätigung, sobald sie eingegangen ist."


def handle_webhook(db, headers: dict, raw: bytes) -> str:
    """PayPal-Webhook: Signatur bei PayPal prüfen lassen, dann Zahlungseingang/Erstattung übernehmen."""
    cfg = get_settings(db)
    if not paypal_ready(cfg) or not cfg.get("paypal_webhook_id"):
        return "ignoriert"
    try:
        event = json.loads(raw)
    except ValueError:
        return "ungültig"
    h = {k.lower(): v for k, v in headers.items()}
    check = _api(db, "POST", "/v1/notifications/verify-webhook-signature", {
        "auth_algo": h.get("paypal-auth-algo", ""), "cert_url": h.get("paypal-cert-url", ""),
        "transmission_id": h.get("paypal-transmission-id", ""), "transmission_sig": h.get("paypal-transmission-sig", ""),
        "transmission_time": h.get("paypal-transmission-time", ""), "webhook_id": cfg["paypal_webhook_id"],
        "webhook_event": event})
    if check.get("verification_status") != "SUCCESS":
        log.warning("PayPal-Webhook mit ungültiger Signatur verworfen")
        return "ungültig"
    kind, res = event.get("event_type", ""), event.get("resource") or {}
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        pid = str(res.get("custom_id") or "")
        p = db.get(Payment, int(pid)) if pid.isdigit() else None
        cents = parse_amount((res.get("amount") or {}).get("value", "")) or 0
        if p is not None and cents == p.amount_cents:
            mark_paid(db, p, "paypal", "PayPal (Webhook)", capture_id=res.get("id", ""))
    elif kind == "CHECKOUT.ORDER.APPROVED":
        p = db.scalar(select(Payment).where(Payment.paypal_order_id == res.get("id", "")))
        if p is not None and p.status in ("open", "pending"):
            finish_paypal(db, p, p.paypal_order_id)
    elif kind in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        intent = db.scalar(select(PaymentRefund).where(PaymentRefund.provider_id == res.get("id", ""))) if res.get("id") else None
        if intent is not None:
            payment = db.get(Payment, intent.payment_id)
            _refund_result(db, payment, intent, {**res, "status": "COMPLETED"} if kind == "PAYMENT.CAPTURE.REFUNDED" else res)
        cap = ""
        for lnk in res.get("links", []):
            if lnk.get("rel") == "up":
                cap = lnk.get("href", "").rstrip("/").rsplit("/", 1)[-1]
        p = db.scalar(select(Payment).where(Payment.paypal_capture_id == (cap or res.get("id", "")))) if (cap or res.get("id")) else None
        if p is not None:
            _log(p, f"PayPal meldet {kind} ({(res.get('amount') or {}).get('value', '?')} €).", "PayPal (Webhook)")
    elif kind == "PAYMENT.CAPTURE.DENIED":
        p = db.scalar(select(Payment).where(Payment.paypal_capture_id == res.get("id", "")))
        if p is not None and p.status == "pending":
            p.status = "open"
            _log(p, "PayPal hat die Zahlung abgelehnt.", "PayPal (Webhook)")
    return "ok"


# --- Fristen ---------------------------------------------------------------------------------

def send_reminders() -> int:
    """Einmal erinnern 2 Tage vor Ablauf; nach Ablauf den Vorgang informieren (z. B. Reservierung verfällt)."""
    n = 0
    now = utcnow()
    with SessionLocal() as db:
        rows = db.scalars(select(Payment).where(Payment.status.in_(("open", "pending")), Payment.due_at.is_not(None),
                                                Payment.due_at < now + timedelta(days=2))).all()
        for p in rows:
            if p.due_at < now:
                if p.overdue_at is None:
                    p.overdue_at = now
                    _log(p, "Zahlfrist abgelaufen.")
                    _fire(db, p, "overdue")
                    n += 1
            elif p.reminded_at is None and p.created_at < now - timedelta(days=1):
                p.reminded_at = now
                if send_mail(db, p, "pay_reminder"):
                    n += 1
        db.commit()
    return n


def stats(db) -> dict:
    rows = db.execute(select(Payment.status, func.count(Payment.id), func.sum(Payment.amount_cents),
                             func.sum(Payment.refunded_cents)).group_by(Payment.status)).all()
    return {s: {"count": c, "cents": a or 0, "refunded": r or 0} for s, c, a, r in rows}


def box(db, user, p: Payment | None, back: str) -> dict:
    """Kontext für templates/_payment_box.html."""
    return {"pay_p": p, "pay_money": money, "pay_statuses": STATUSES, "pay_methods": METHODS,
            "pay_manage": bool(p is not None and can_manage(db, user, p)), "pay_next": back}
