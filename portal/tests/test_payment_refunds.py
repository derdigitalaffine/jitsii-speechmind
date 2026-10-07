"""Provider uncertainty must never create a second refund or a false receipt."""
from datetime import timedelta
import uuid
from sqlalchemy import select
from app import payments as pay
from app.db import Payment, PaymentRefund, PaymentReceipt, SessionLocal, utcnow
from conftest import client, login
from test_resources import ADMIN, _staff_booking, day, make_resource, module_on


def payment(db, method='paypal'):
    p = pay.create(db, kind='other', purpose='Erstattungstest', lines=[{'label': 'Test', 'unit_cents': 10000}])
    pay.mark_paid(db, p, method, 'Test', capture_id='CAPTURE-TEST' if method == 'paypal' else '')
    db.commit()
    return p


def test_new_refunds_have_different_ids(db, monkeypatch):
    ids = []
    def api(*args, **kw):
        ids.append(kw['request_id'])
        return {'id': 'R' + str(len(ids)), 'status': 'COMPLETED'}
    monkeypatch.setattr(pay, '_api', api)
    p = payment(db)
    assert pay.refund(db, p, 1000) == ''
    assert pay.refund(db, p, 1000) == ''
    assert len(set(ids)) == 2 and all(str(uuid.UUID(v)) == v for v in ids)
    assert p.refunded_cents == 2000


def test_uncertain_retry_survives_rollback_and_keeps_same_id(db, monkeypatch):
    ids = []
    def api(*args, **kw):
        ids.append(kw['request_id'])
        if len(ids) == 1:
            raise pay.PayPalError('Zeitüberschreitung')
        return {'id': 'REFUND-RETRY', 'status': 'COMPLETED'}
    monkeypatch.setattr(pay, '_api', api)
    p = payment(db)
    assert pay.refund(db, p, 1000)
    db.rollback()
    db.refresh(p)
    assert p.refunded_cents == 0 and p.active_refund
    assert pay.refund(db, p, 1000) and len(ids) == 1
    assert pay.reconcile_refund(db, p) == ''
    db.commit()
    assert ids[0] == ids[1] and p.refunded_cents == 1000


def test_pending_is_not_paid_until_get_confirms(db, monkeypatch):
    calls = []
    def api(db, method, path, *a, **kw):
        calls.append((method, path))
        return {'id': 'REFUND-PENDING', 'status': 'PENDING' if method == 'POST' else 'COMPLETED'}
    monkeypatch.setattr(pay, '_api', api)
    p = payment(db)
    assert pay.refund(db, p, 2000)
    assert p.refunded_cents == 0
    assert pay.reconcile_refund(db, p) == ''
    intent = db.scalar(select(PaymentRefund).where(PaymentRefund.payment_id == p.id))
    pay._complete_refund(db, p, intent)
    assert p.refunded_cents == 2000
    assert calls[-1] == ('GET', '/v2/payments/refunds/REFUND-PENDING')
    assert len([r for r in pay.receipts(db, p) if r.kind == 'refunded']) == 1


def test_provider_amount_mismatch_blocks_accounting(db, monkeypatch):
    monkeypatch.setattr(pay, '_api', lambda *a, **k: {'id': 'R-WRONG', 'status': 'COMPLETED', 'amount': {'value': '999.00', 'currency_code': 'EUR'}})
    p = payment(db)
    assert pay.refund(db, p, 1000)
    assert p.refunded_cents == 0 and p.active_refund


def test_definitive_rejection_allows_corrected_new_request(db, monkeypatch):
    monkeypatch.setattr(pay, '_api', lambda *a, **k: (_ for _ in ()).throw(pay.PayPalError('REFUND_NOT_ALLOWED', definite=True)))
    p = payment(db)
    assert pay.refund(db, p, 1000)
    assert not p.active_refund and p.refunded_cents == 0


def test_alternate_manual_payment_needs_reason_and_backdated_receipt(db, monkeypatch):
    monkeypatch.setattr(pay, '_api', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No external refund')))
    p = payment(db)
    stamp = utcnow() - timedelta(days=2)
    assert pay.refund(db, p, 1000, method='cash')
    assert pay.refund(db, p, 1000, method='cash', note='Hausmeister bereits ausgezahlt', occurred_at=stamp) == ''
    receipt = [r for r in pay.receipts(db, p) if r.kind == 'refunded'][0]
    assert receipt.occurred_at == stamp and receipt.created_at > stamp
    assert pay.receipt_pdf(receipt).startswith(b'%PDF')


def test_split_payment_and_receipt_access():
    rid = make_resource('Kaution getrennt', units='day', mode='instant', price_day=10000, deposit_cents=30000)
    bid = _staff_booking(rid, day(7), price_paid=True)
    with SessionLocal() as db:
        from app.db import ResourceBooking
        b = db.get(ResourceBooking, bid)
        assert b.payment.amount_cents == 10000 and b.deposit_payment.amount_cents == 30000
        assert b.payment.method == 'transfer' and b.deposit_payment.method == 'cash'
        receipt = pay.receipts(db, b.deposit_payment)[0]
        path = f'/pay/{b.deposit_payment.token}/receipts/{receipt.id}.pdf'
        wrong = f'/pay/{b.payment.token}/receipts/{receipt.id}.pdf'
    c = client()
    assert c.get(path).content.startswith(b'%PDF')
    assert c.get(wrong).status_code == 404
    admin = login(*ADMIN)
    page = admin.get(f'/resources/bookings/{bid}')
    assert page.status_code == 200 and 'Kaution' in page.text
