"""Hausmeister:innen: persönlicher Link, Terminliste, Übergabe/Abnahme, Kautionsfreigabe, Protokoll an Buchende,
Verwaltung und Ablage, Kontakt vor Ort und Erinnerung."""

import json
import re

from sqlalchemy import select

from app import resources as rs
from app.db import DmsRecord, Payment, ResourceBooking, ResourceCaretaker, SessionLocal

from conftest import client, csrf_of, login, settings
from test_resources import ADMIN, _staff_booking, day, mails, make_resource, module_on  # noqa: F401


def _caretaker(admin, rid, email="hm@example.org") -> tuple[int, str]:
    page = admin.get("/resources/caretakers")
    assert page.status_code == 200 and "Hausmeister:in anlegen" in page.text
    token = csrf_of(page.text)
    r = admin.post("/resources/caretakers", data={"csrf": token, "name": "Hans Hausmeister", "email": email,
                                                   "phone": "0631 123", "resources": [str(rid)], "active": "1"})
    assert r.status_code == 303
    with SessionLocal() as db:
        ct = db.scalar(select(ResourceCaretaker).where(ResourceCaretaker.email == email))
        cid = ct.id
    admin.post("/resources/caretakers", data={"csrf": token, "id": str(cid), "action": "send"})
    body = mails(email, "res_caretaker_link")[-1].body
    path = re.search(r"https?://[^/\s]+(/r/hausmeister/\S+)", body).group(1)
    return cid, path


def test_caretaker_handover_release_and_protocol():
    settings(module_dms="1")
    rid = make_resource("Grillhütte HM", units="day", mode="instant", price_day=10000, deposit_cents=30000,
                        deposit_release=True, caretaker_public=True)
    bid = _staff_booking(rid, day(3), price_paid=True, email="buchend@example.org")
    admin = login(*ADMIN)
    cid, path = _caretaker(admin, rid)
    hm = client()
    page = hm.get(path)
    assert page.status_code == 200 and "Grillhütte HM" in page.text and f"{path}/{bid}" in page.text
    page = hm.get(f"{path}/{bid}")
    token = csrf_of(page.text)
    assert hm.post(f"{path}/{bid}", data={"csrf": token, "part": "out", "keys": "2× Tor", "note": "Strom 1234"}).status_code == 303
    r = hm.post(f"{path}/{bid}", data={"csrf": token, "part": "back", "damages": "Grillrost verbogen", "note": "",
                                       "keep": "50,00"})
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        h = rs.handover(b)
        assert h["out"]["caretaker"] and h["deposit_pending"]["keep_cents"] == 5000 and not h.get("deposit_done")
        assert b.payment.refunded_cents == 0
        record = db.scalar(select(DmsRecord).where(DmsRecord.booking_id == bid))
        assert any(f.name == f"Übergabeprotokoll {b.ref}.pdf" for f in record.files)
    proto = mails("buchend@example.org", "res_protocol")
    assert proto and json.loads(proto[-1].attachments_json)[0]["filename"].startswith("Protokoll-")
    assert any("Kaution zur Freigabe" in m.subject for m in mails(kind="res_staff"))
    # Verwaltung gibt frei (Einbehalt geändert)
    page = admin.get(f"/resources/bookings/{bid}")
    assert "Kaution wartet auf Freigabe" in page.text and "Hausmeister:in" in page.text
    r = admin.post(f"/resources/bookings/{bid}/deposit-release", data={"csrf": csrf_of(page.text), "keep": "20"})
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        h = rs.handover(b)
        assert h["deposit_done"] and not h.get("deposit_pending") and h["back"]["keep_cents"] == 2000
        assert db.get(Payment, b.deposit_payment_id).refunded_cents == 28000
    assert admin.get(f"/resources/bookings/{bid}/protokoll.pdf").content[:4] == b"%PDF"
    # Kontakt vor Ort für Buchende
    with SessionLocal() as db:
        tok = db.get(ResourceBooking, bid).token
    assert "Hans Hausmeister, Telefon 0631 123" in client().get(f"/r/b/{tok}").text


def test_caretaker_link_scope_and_lock():
    rid = make_resource("Halle HM", units="day", mode="instant", price_day=5000)
    other = make_resource("Fremde Halle", units="day", mode="instant", price_day=5000)
    foreign = _staff_booking(other, day(4))
    admin = login(*ADMIN)
    cid, path = _caretaker(admin, rid, email="hm2@example.org")
    hm = client()
    assert hm.get(f"{path}/{foreign}").status_code == 404
    page = admin.get("/resources/caretakers")
    admin.post("/resources/caretakers", data={"csrf": csrf_of(page.text), "id": str(cid), "action": "lock"})
    assert hm.get(path).status_code == 404
    assert client().get("/r/hausmeister/falsch").status_code == 404


def test_without_release_refunds_directly_and_reminder():
    rid = make_resource("Platz HM", units="day", mode="instant", price_day=5000, deposit_cents=10000,
                        caretaker_remind=True, remind_staff_days=5)
    bid = _staff_booking(rid, day(2), price_paid=True)
    admin = login(*ADMIN)
    _cid, path = _caretaker(admin, rid, email="hm3@example.org")
    hm = client()
    token = csrf_of(hm.get(f"{path}/{bid}").text)
    hm.post(f"{path}/{bid}", data={"csrf": token, "part": "back", "damages": "", "keep": "0"})
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        assert rs.handover(b)["deposit_done"] and b.deposit_payment.refunded_cents == 10000
    # Erinnerung an Hausmeister:in mit funktionierendem Link; der Link aus der ersten Mail bleibt gültig
    bid2 = _staff_booking(rid, day(3))
    with SessionLocal() as db:
        b2 = db.get(ResourceBooking, bid2)
        b2.staff_reminded_at = None
        db.commit()
    rs.send_reminders()
    rem = mails("hm3@example.org", "res_caretaker_reminder")
    assert rem
    new_path = re.search(r"https?://[^/\s]+(/r/hausmeister/\S+)", rem[-1].body).group(1)
    assert hm.get(new_path).status_code == 200 and hm.get(path).status_code == 200
