import pytest
from app import epaybl, payments as pay, workflow
from app.db import SessionLocal
from conftest import client, csrf_of, login


def test_configuration_cannot_activate_prepared_provider():
    cfg = {'epaybl_enabled': '1', 'epaybl_tenant': 'test', 'epaybl_secret': 'pretend', 'pay_transfer': '1', 'pay_iban': 'DE123'}
    assert not epaybl.provider.ready(cfg)
    class P:
        methods = 'epaybl,transfer'
    assert pay.available(cfg, P()) == ['transfer']
    with pytest.raises(epaybl.Unavailable):
        epaybl.provider.start(P(), cfg)
    with pytest.raises(epaybl.Unavailable):
        epaybl.provider.refund(P(), 100, 'unique', cfg)


def test_public_attempt_cannot_change_payment_or_send_request():
    with SessionLocal() as db:
        p = pay.create(db, kind='application', purpose='ePayBL vorbereitet', lines=[{'label': 'Gebühr', 'unit_cents': 100}], methods='epaybl,transfer')
        db.commit()
        token, pid = p.token, p.id
    c = client()
    page = c.get(f'/pay/{token}')
    assert 'noch nicht verfügbar' in page.text
    r = c.post(f'/pay/{token}/epaybl', data={'csrf': csrf_of(page.text)})
    assert r.status_code == 503
    with SessionLocal() as db:
        from app.db import Payment
        assert db.get(Payment, pid).status == 'open'


def test_configuration_status_is_visible_to_admin():
    c = login('admin@example.org', 'admin-passwort-123')
    page = c.get('/admin/payments')
    assert page.status_code == 200 and 'Noch nicht verfügbar' in page.text
    assert 'epaybl_tenant' in page.text
