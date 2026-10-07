"""Zahlungen: öffentliche Zahlseite, PayPal-Rückkehr und -Webhook, Übersicht für die Kasse, Einstellungen."""

import io
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import csvsafe, payments as pay
from .db import LOCAL_TZ, Payment, PaymentReceipt, utcnow, User, get_settings, set_setting, to_local
from .main import admin_user, app, check_csrf, current_user, flash, get_db, rate_limit, redirect, render, require, safe_next, session_user
from .security import encrypt

payments_user = require("payments")


def _payment(db, token: str) -> Payment:
    p = db.scalar(select(Payment).where(Payment.token == token)) if token else None
    if p is None:
        raise HTTPException(404, "Diese Zahlung gibt es nicht (mehr).")
    return p


def _ctx(db, p: Payment) -> dict:
    cfg = get_settings(db)
    return {"p": p, "items": pay.items(p), "money": pay.money, "statuses": pay.STATUSES, "methods": pay.METHODS,
            "available": pay.available(cfg, p), "cfg": cfg, "receipts": pay.receipts(db, p)}


# --- Öffentliche Zahlseite --------------------------------------------------------------------

@app.get("/pay/{token}")
def pay_page(request: Request, token: str, db: Session = Depends(get_db)):
    p = _payment(db, token)
    return render(request, "pay.html", session_user(request, db), **_ctx(db, p),
                  notice=request.session.pop("pay_notice", ""))


@app.post("/pay/{token}/paypal", dependencies=[Depends(check_csrf)])
def pay_paypal(request: Request, token: str, db: Session = Depends(get_db)):
    p = _payment(db, token)
    rate_limit(request, "paypal", limit=10, window=600)
    if "paypal" not in pay.available(get_settings(db), p):
        raise HTTPException(400, "PayPal steht für diese Zahlung nicht zur Verfügung.")
    try:
        url = pay.start_paypal(db, p)
    except pay.PayPalError as exc:
        db.rollback()
        request.session["pay_notice"] = f"PayPal ist gerade nicht erreichbar ({exc}). Bitte später erneut versuchen."
        return redirect(f"/pay/{token}")
    db.commit()
    return RedirectResponse(url, status_code=303)


@app.get("/pay/{token}/return")
def pay_return(request: Request, token: str, db: Session = Depends(get_db)):
    p = _payment(db, token)
    msg = pay.finish_paypal(db, p, request.query_params.get("token", ""))
    db.commit()
    if not msg and p.back_url:
        return redirect(safe_next(p.back_url) if p.back_url.startswith("/") else f"/pay/{token}")
    request.session["pay_notice"] = msg
    return redirect(f"/pay/{token}")


@app.get("/pay/{token}/cancel")
def pay_cancel(request: Request, token: str, db: Session = Depends(get_db)):
    p = _payment(db, token)
    if p.status == "pending":
        p.status = "open"
        pay._log(p, "Zahlung bei PayPal abgebrochen.")
        db.commit()
    request.session["pay_notice"] = "Die Zahlung wurde abgebrochen. Sie können es erneut versuchen oder eine andere Zahlart wählen."
    return redirect(f"/pay/{token}")


@app.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "paypal-webhook", limit=120, window=60)
    raw = await request.body()
    if len(raw) > 200_000:
        raise HTTPException(413, "zu groß")
    try:
        result = pay.handle_webhook(db, dict(request.headers), raw)
    except pay.PayPalError as exc:
        db.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)   # PayPal versucht es später erneut
    db.commit()
    return JSONResponse({"ok": result == "ok", "result": result}, status_code=200 if result != "ungültig" else 400)


# --- Übersicht für die Kasse -----------------------------------------------------------------

FILTERS = ("q", "status", "kind", "method", "from", "to")


def _query(params: dict):
    q = select(Payment)
    text = params.get("q", "").strip()
    if text:
        like = f"%{text}%"
        q = q.where(or_(Payment.ref.ilike(like), Payment.purpose.ilike(like), Payment.payer_name.ilike(like),
                        Payment.payer_email.ilike(like), Payment.cost_center.ilike(like)))
    if params.get("status") == "due":
        q = q.where(Payment.status.in_(("open", "pending")))
    elif params.get("status") in pay.STATUSES:
        q = q.where(Payment.status == params["status"])
    if params.get("kind") in pay.KINDS:
        q = q.where(Payment.kind == params["kind"])
    if params.get("method") in pay.METHODS:
        q = q.where(Payment.method == params["method"])
    for key, op in (("from", "ge"), ("to", "le")):
        try:
            d = datetime.strptime(params.get(key, ""), "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
        utc = d.astimezone(timezone.utc).replace(tzinfo=None)
        q = q.where(Payment.created_at >= utc) if op == "ge" else q.where(Payment.created_at < utc + timedelta(days=1))
    return q.order_by(Payment.created_at.desc())


@app.get("/payments")
def payments_list(request: Request, user: User = Depends(payments_user), db: Session = Depends(get_db)):
    f = {k: request.query_params.get(k, "") for k in FILTERS}
    rows = db.scalars(_query(f).limit(500)).all()
    total = sum(p.amount_cents for p in rows if p.status in ("paid", "partially_refunded", "refunded"))
    refunded = sum(p.refunded_cents for p in rows)
    due = sum(p.amount_cents for p in rows if p.status in ("open", "pending"))
    qs = "&".join(f"{k}={v}" for k, v in f.items() if v)
    return render(request, "payments.html", user, rows=rows, f=f, qs=qs, money=pay.money, statuses=pay.STATUSES,
                  methods=pay.METHODS, kinds=pay.KINDS, sums={"paid": total, "refunded": refunded, "due": due},
                  cfg=get_settings(db), paypal_ready=pay.paypal_ready(get_settings(db)))


@app.get("/payments/export.csv")
def payments_export(request: Request, user: User = Depends(payments_user), db: Session = Depends(get_db)):
    f = {k: request.query_params.get(k, "") for k in FILTERS}
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    w.writerow(["Zahlungsnummer", "Angelegt", "Bezahlt am", "Art", "Zweck", "Zahlende Person", "E-Mail", "Kostenstelle",
                "Betrag", "davon Kaution", "Erstattet", "Zahlart", "Status", "PayPal-Transaktion"])
    eur = lambda c: f"{c / 100:.2f}".replace(".", ",")  # noqa: E731
    for p in db.scalars(_query(f)):
        w.writerow([p.ref, to_local(p.created_at).strftime("%d.%m.%Y %H:%M"),
                    to_local(p.paid_at).strftime("%d.%m.%Y %H:%M") if p.paid_at else "", pay.KINDS.get(p.kind, p.kind),
                    p.purpose, p.payer_name, p.payer_email, p.cost_center, eur(p.amount_cents), eur(p.deposit_cents),
                    eur(p.refunded_cents), pay.METHODS.get(p.method, ("",))[0], pay.STATUSES.get(p.status, (p.status,))[0],
                    p.paypal_capture_id])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="zahlungen.csv"'})


def _managed(db, user: User | None, pid: int) -> Payment:
    p = db.get(Payment, pid)
    if p is None:
        raise HTTPException(404, "Zahlung nicht gefunden.")
    if not pay.can_manage(db, user, p):
        raise HTTPException(403, "Keine Berechtigung für diese Zahlung.")
    return p


def _user(request: Request, db) -> User:
    # wie überall: auch Passwortwechsel- und Zwei-Faktor-Pflicht durchsetzen
    return current_user(request, db)


@app.get("/payments/{pid:int}")
def payment_detail(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    return render(request, "payment.html", user, **_ctx(db, p), log=pay.log_entries(p), subject=pay.subject_link(p),
                  kinds=pay.KINDS, link=pay.link(p))


def _back(data, pid: int) -> RedirectResponse:
    nxt = str(data.get("next", ""))
    return redirect(safe_next(nxt) if nxt else f"/payments/{pid}")


def _occurred(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=LOCAL_TZ)
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
        return stamp if stamp <= utcnow() else None
    except (ValueError, TypeError):
        return None


@app.post("/payments/{pid:int}/refund/check", dependencies=[Depends(check_csrf)])
async def payment_refund_check(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    data = await request.form()
    message = pay.reconcile_refund(db, p)
    db.commit()
    flash(request, message or "Erstattung bestätigt.", "error" if message else "success")
    return _back(data, pid)


@app.get("/payments/{pid:int}/receipts/{rid:int}.pdf")
def payment_receipt(request: Request, pid: int, rid: int, db: Session = Depends(get_db)):
    _managed(db, _user(request, db), pid)
    return _receipt_response(db, pid, rid)


@app.get("/pay/{token}/receipts/{rid:int}.pdf")
def public_payment_receipt(token: str, rid: int, db: Session = Depends(get_db)):
    return _receipt_response(db, _payment(db, token).id, rid)


def _receipt_response(db, pid, rid):
    receipt = db.get(PaymentReceipt, rid)
    if receipt is None or receipt.payment_id != pid:
        raise HTTPException(404, "Beleg nicht gefunden.")
    return Response(pay.receipt_pdf(receipt), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{receipt.ref}.pdf"', "Cache-Control": "no-store"})


@app.post("/payments/{pid:int}/paid", dependencies=[Depends(check_csrf)])
async def payment_mark_paid(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    data = await request.form()
    method = str(data.get("method", "cash"))
    if method not in ("cash", "transfer"):
        method = "cash"
    occurred = _occurred(data.get("occurred_at"))
    if data.get("occurred_at") and occurred is None:
        flash(request, "Bitte einen gültigen tatsächlichen Zeitpunkt in der Vergangenheit angeben.", "error")
        return _back(data, pid)
    if pay.mark_paid(db, p, method, user.name or user.email, str(data.get("note", ""))[:300], occurred_at=occurred):
        flash(request, f"{p.ref} als bezahlt ({pay.METHODS[method][0]}) vermerkt.")
    db.commit()
    return _back(data, pid)


@app.post("/payments/{pid:int}/refund", dependencies=[Depends(check_csrf)])
async def payment_refund(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    data = await request.form()
    cents = pay.parse_amount(data.get("amount", ""))
    occurred = _occurred(data.get("occurred_at"))
    method = str(data.get("refund_method", ""))
    if method not in ("", "cash", "transfer") or (data.get("occurred_at") and occurred is None):
        flash(request, "Ungültiger Zahlweg oder tatsächlicher Zeitpunkt.", "error")
        return _back(data, pid)
    err = pay.refund(db, p, cents or 0, user.name or user.email, str(data.get("note", ""))[:300], method=method, occurred_at=occurred) if cents else \
        "Bitte einen gültigen Betrag angeben."
    if err:
        db.rollback()
        flash(request, err, "error")
    else:
        db.commit()
        flash(request, f"{pay.money(cents)} erstattet.")
    return _back(data, pid)


@app.post("/payments/{pid:int}/cancel", dependencies=[Depends(check_csrf)])
async def payment_cancel(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    data = await request.form()
    if pay.cancel(db, p, user.name or user.email, str(data.get("note", ""))[:300]):
        flash(request, f"{p.ref} storniert.")
    db.commit()
    return _back(data, pid)


@app.post("/payments/{pid:int}/remind", dependencies=[Depends(check_csrf)])
async def payment_remind(request: Request, pid: int, db: Session = Depends(get_db)):
    user = _user(request, db)
    p = _managed(db, user, pid)
    data = await request.form()
    if p.status in ("open", "pending") and pay.send_mail(db, p, "pay_request"):
        pay._log(p, "Zahlungsaufforderung erneut gesendet.", user.name or user.email)
        flash(request, "Zahlungsaufforderung gesendet.")
    else:
        flash(request, "Keine Mail möglich (keine Adresse, Mailversand aus oder Zahlung nicht offen).", "error")
    db.commit()
    return _back(data, pid)


# --- Einstellungen (Admins) ------------------------------------------------------------------

@app.get("/admin/payments")
def admin_payments(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    cfg = get_settings(db)
    from .config import settings
    return render(request, "admin_payments.html", user, cfg=cfg, has_secret=bool(cfg.get("paypal_secret_enc")),
                  webhook_url=f"{settings.portal_base_url}/paypal/webhook", stats=pay.stats(db), money=pay.money,
                  statuses=pay.STATUSES)


@app.post("/admin/payments", dependencies=[Depends(check_csrf)])
def admin_payments_save(request: Request, paypal_enabled: str = Form(""), paypal_mode: str = Form("sandbox"),
                        paypal_client_id: str = Form(""), paypal_secret: str = Form(""), paypal_webhook_id: str = Form(""),
                        pay_transfer: str = Form(""), pay_recipient: str = Form(""), pay_iban: str = Form(""),
                        pay_bic: str = Form(""), pay_bank: str = Form(""), pay_prefix: str = Form("Z"),
                        pay_days: str = Form("14"), user: User = Depends(admin_user), db: Session = Depends(get_db)):
    iban = pay_iban.replace(" ", "").upper()
    if iban and not (15 <= len(iban) <= 34 and iban[:2].isalpha() and iban[2:4].isdigit() and iban.isalnum()):
        flash(request, "Die IBAN sieht nicht gültig aus.", "error")
        return redirect("/admin/payments")
    try:
        days = max(1, min(90, int(pay_days)))
    except ValueError:
        days = 14
    set_setting(db, "paypal_enabled", "1" if paypal_enabled == "1" else "0")
    set_setting(db, "paypal_mode", "live" if paypal_mode == "live" else "sandbox")
    set_setting(db, "paypal_client_id", paypal_client_id.strip()[:200])
    if paypal_secret.strip():
        set_setting(db, "paypal_secret_enc", encrypt(paypal_secret.strip()))
    set_setting(db, "paypal_webhook_id", paypal_webhook_id.strip()[:100])
    set_setting(db, "pay_transfer", "1" if pay_transfer == "1" else "0")
    set_setting(db, "pay_recipient", " ".join(pay_recipient.split())[:200])
    set_setting(db, "pay_iban", " ".join(iban[i:i + 4] for i in range(0, len(iban), 4)))
    set_setting(db, "pay_bic", pay_bic.strip().upper()[:11])
    set_setting(db, "pay_bank", " ".join(pay_bank.split())[:120])
    set_setting(db, "pay_prefix", "".join(c for c in pay_prefix.upper() if c.isalnum())[:6] or "Z")
    set_setting(db, "pay_days", str(days))
    db.commit()
    flash(request, "Zahlungseinstellungen gespeichert.")
    return redirect("/admin/payments")


@app.post("/admin/payments/test", dependencies=[Depends(check_csrf)])
def admin_payments_test(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        flash(request, pay.test_connection(db))
    except pay.PayPalError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/payments")
