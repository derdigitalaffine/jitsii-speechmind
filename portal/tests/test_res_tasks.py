"""Buchungsaufgaben in „Meine Aufgaben“: Anfragen, Kautionsfreigaben, Übergaben, fehlende Abnahmen, überfällige Zahlungen."""

import json
from datetime import timedelta

from app import main, resources as rs
from app.db import Payment, Resource, ResourceBooking, SessionLocal, User, to_local, utcnow

from conftest import login, settings
from test_resources import ADMIN, _staff_booking, day, make_resource, module_on  # noqa: F401


def _book(rid, d, status, **kw) -> int:
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="day", date_from=d.isoformat(), date_to=d.isoformat()), staff=True)
        b = rs.create(db, res, q, {"name": "Kunde", "email": "k@example.org", "title": "Feier"}, {})
        b.status = status
        for k, v in kw.items():
            setattr(b, k, v)
        db.commit()
        return b.id


def test_booking_tasks_collected_and_shown():
    rid = make_resource("Saal Aufgaben", units="day", mode="request", price_day=10000, deposit_cents=5000)
    req = _book(rid, day(9), "requested")
    today = to_local(utcnow()).date()
    hand = _staff_booking(rid, today + timedelta(days=1))
    pend = _staff_booking(rid, day(12))
    with SessionLocal() as db:
        b = db.get(ResourceBooking, pend)
        b.handover_json = json.dumps({"back": {"by": "Hans"}, "deposit_pending": {"by": "Hans", "keep_cents": 0}})
        b2 = db.get(ResourceBooking, hand)
        p = db.get(Payment, b2.payment_id)
        p.due_at = utcnow() - timedelta(days=2)
        old = ResourceBooking(**{c: getattr(b2, c) for c in ("resource_id", "mode", "name", "email", "title", "deposit_cents")},
                              ref="RB-T-OLD", token="tok-task-old", status="confirmed",
                              starts_at=utcnow() - timedelta(days=3), ends_at=utcnow() - timedelta(days=2))
        db.add(old)
        db.commit()
        admin = db.get(User, 1)
        kinds = {(t["kind"], t["booking"].id) for t in rs.booking_tasks(db, admin)}
        assert ("request", req) in kinds and ("deposit", pend) in kinds and ("handover", hand) in kinds
        assert ("payment", hand) in kinds and ("return", old.id) in kinds
        first = rs.booking_tasks(db, admin)[0]
        assert first["late"]
    main._badge_cache.clear()
    c = login(*ADMIN)
    page = c.get("/tasks")
    assert page.status_code == 200 and "Ressourcenbuchung" in page.text and "Kaution freigeben: Saal Aufgaben" in page.text
    assert f"/resources/bookings/{pend}#uebergabe" in page.text


def test_tasks_page_without_applications_module():
    settings(module_applications="0")
    try:
        main._badge_cache.clear()
        c = login(*ADMIN)
        page = c.get("/tasks")
        assert page.status_code == 200 and "Antragseingang" not in page.text
        assert 'href="/tasks"' in page.text   # Menüeintrag unter Ressourcen
    finally:
        settings(module_applications="1")
