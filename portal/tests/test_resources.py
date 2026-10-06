"""Ressourcenbuchung: Assistent, Schritte, freie Zeiten, Warteliste, Ändern/Verschieben, Erinnerungen, Auswertung,
Kopieren/Ex-/Import, Sammelaktionen, Vereine, Merkliste."""

import json
import re
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import res_clubs, res_wait, resources as rs
from app.db import (
    Notification, Payment, Resource, ResourceBooking, ResourceClub, ResourceTariff, ResourceWait, SessionLocal,
    to_local, utcnow,
)

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


@pytest.fixture(autouse=True)
def module_on():
    settings(module_resources="1", smtp_host="smtp.example.org", mail_from="portal@example.org")
    yield


def day(n: int):
    """Werktag in n Tagen (nie Wochenende, damit keine Wochenendpreise greifen)."""
    d = to_local(utcnow()).date() + timedelta(days=n)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def make_resource(name: str, **kw) -> int:
    with SessionLocal() as db:
        res = db.scalar(select(Resource).where(Resource.name == name))
        if res is not None:
            for b in db.scalars(select(ResourceBooking).where(ResourceBooking.resource_id == res.id)):
                db.delete(b)
            for w in db.scalars(select(ResourceWait).where(ResourceWait.resource_id == res.id)):
                db.delete(w)
            db.delete(res)
            db.commit()
        res = Resource(name=name, slug=rs.unique_slug(db, name), active=True, public=True, min_notice_hours=0,
                       owner_id=1, manager_user_id=1, **kw)
        db.add(res)
        db.flush()
        res.tariffs.append(ResourceTariff(name="Standard", percent=100))
        db.commit()
        return res.id


def slug_of(rid: int) -> str:
    with SessionLocal() as db:
        return db.get(Resource, rid).slug


def mails(to: str = "", kind: str = "") -> list[Notification]:
    with SessionLocal() as db:
        q = select(Notification).order_by(Notification.id)
        if to:
            q = q.where(Notification.to_addr == to)
        if kind:
            q = q.where(Notification.kind == kind)
        return list(db.scalars(q))


def public_book(c, slug: str, data: dict, **extra):
    page = c.get(f"/r/{slug}")
    assert page.status_code == 200, page.text[:300]
    body = {"csrf": csrf_of(page.text), "name": "Erika Muster", "title": "Geburtstag", **data, **extra}
    return c.post(f"/r/{slug}/book", data=body)


def confirm_link(email: str) -> str:
    body = [m for m in mails(email, "res_confirm_email")][-1].body
    return re.search(r"https?://\S+/r/b/\S+/confirm/\S+", body).group(0).split("portal.example.org", 1)[1]


def test_setup_assistant_with_preset():
    c = login(*ADMIN)
    page = c.get("/resources/new")
    assert page.status_code == 200 and "Bürgerhaus / Saal" in page.text
    r = c.post("/resources/new", data={"csrf": csrf_of(page.text), "preset": "hall", "name": "Assistent-Saal",
                                       "location": "Hauptstraße 1", "capacity": "120", "price": "300"})
    assert r.status_code == 303 and r.headers["location"].endswith("?neu=1")
    rid = int(r.headers["location"].split("/")[2])
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        assert res.units == "day" and res.price_day == 30000 and res.deposit_cents == 20000 and not res.active
        assert {x.name for x in res.extras} == {"Endreinigung", "Geschirr und Besteck"}
        assert res.category == "Bürgerhaus"
    page = c.get(r.headers["location"])
    assert "Checkliste" in page.text and "Erinnerungen &amp; Warteliste" in page.text


def test_public_booking_doi_instant_and_ics():
    rid = make_resource("Gruppenraum Test", units="hour", mode="instant", price_hour=1000, slot_minutes=30,
                        min_minutes=60)
    c = client()
    d = day(3)
    r = public_book(c, slug_of(rid), {"mode": "hour", "date": d.isoformat(), "time_from": "10:00", "time_to": "12:00",
                                      "email": "erika@example.org"})
    assert r.status_code == 303 and "/r/b/" in r.headers["location"]
    r = c.get(confirm_link("erika@example.org"))
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.scalar(select(ResourceBooking).where(ResourceBooking.resource_id == rid))
        assert b.status == "confirmed" and b.payment is not None and b.payment.amount_cents == 2000
        token = b.token
    assert any(m.kind == "res_confirmed" for m in mails("erika@example.org"))
    ics = c.get(f"/r/b/{token}/termin.ics")
    assert ics.status_code == 200 and b"BEGIN:VEVENT" in ics.content


def test_day_free_slots():
    rid = make_resource("Stundenraum", units="hour", mode="instant", slot_minutes=60, min_minutes=60, buffer_after=30,
                        hours_json=json.dumps({str(i): [["08:00", "20:00"]] for i in range(7)}))
    d = day(4)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="hour", date=d.isoformat(), time_from="10:00", time_to="12:00"), staff=True)
        rs.create(db, res, q, {"name": "X", "email": "", "title": "T"}, {}, internal=True)
        db.commit()
    data = client().get(f"/r/{slug_of(rid)}/day.json?date={d.isoformat()}").json()
    assert data["open"] == [["08:00", "20:00"]]
    assert data["busy"] == [["09:30", "12:30"]]                       # 30 Min. Abstand in beide Richtungen
    assert data["free"] == [["08:00", "09:30"], ["12:30", "20:00"]]


def test_waitlist_offer_hold_and_book():
    rid = make_resource("Grillplatz Warteliste", units="day", mode="instant", price_day=5000)
    slug = slug_of(rid)
    d = day(6)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="day", date_from=d.isoformat(), date_to=d.isoformat()), staff=True)
        b = rs.create(db, res, q, {"name": "Erst", "email": "erst@example.org", "title": "Fest"}, {}, internal=True)
        db.commit()
        first_id = b.id
    c = client()
    page = c.get(f"/r/{slug}")
    quote = c.post(f"/r/{slug}/quote", data={"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(),
                                              "date_to": d.isoformat()}).json()
    assert not quote["ok"] and quote["waitlist"]
    r = public_book(c, slug, {"mode": "day", "date_from": d.isoformat(), "date_to": d.isoformat(),
                              "email": "warte@example.org", "action": "wait"})
    assert r.status_code == 303 and "/r/w/" in r.headers["location"]
    body = mails("warte@example.org", "res_wait_confirm")[-1].body
    link = re.search(r"/r/w/\S+/confirm/\S+", body).group(0)
    assert c.get(link).status_code == 303
    with SessionLocal() as db:
        w = db.scalar(select(ResourceWait).where(ResourceWait.email == "warte@example.org"))
        assert w.status == "waiting" and res_wait.position(db, w) == 1
    # zweite Person wartet hinter der ersten
    c2 = client()
    public_book(c2, slug, {"mode": "day", "date_from": d.isoformat(), "date_to": d.isoformat(),
                           "email": "zweite@example.org", "name": "Zweite", "action": "wait"})
    with SessionLocal() as db:
        w2 = db.scalar(select(ResourceWait).where(ResourceWait.email == "zweite@example.org"))
        res_wait.confirm(db, w2)
        db.commit()
    # Storno durch die Verwaltung → erste Person bekommt das Angebot
    admin = login(*ADMIN)
    token = csrf_of(admin.get(f"/resources/bookings/{first_id}").text)
    admin.post(f"/resources/bookings/{first_id}/cancel", data={"csrf": token, "reason": "abgesagt"})
    with SessionLocal() as db:
        w = db.scalar(select(ResourceWait).where(ResourceWait.email == "warte@example.org"))
        w2 = db.scalar(select(ResourceWait).where(ResourceWait.email == "zweite@example.org"))
        assert w.status == "offered" and w2.status == "waiting"
        wtoken = w.token
    assert mails("warte@example.org", "res_wait_offer")
    # andere können während des Angebots nicht buchen
    other = client()
    page = other.get(f"/r/{slug}")
    quote = other.post(f"/r/{slug}/quote", data={"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(),
                                                  "date_to": d.isoformat()}).json()
    assert not quote["ok"] and any("Warteliste" in e for e in quote["errors"])
    # Buchen über das Angebot: keine Bestätigungsmail nötig
    page = c.get(f"/r/w/{wtoken}")
    assert page.status_code == 200 and "Für Sie reserviert" in page.text
    r = c.post(f"/r/{slug}/book", data={"csrf": csrf_of(page.text), "wait_token": wtoken, "mode": "day",
                                        "date_from": d.isoformat(), "date_to": d.isoformat(), "name": "Warte",
                                        "email": "warte@example.org", "title": "Grillen"})
    assert r.status_code == 303
    with SessionLocal() as db:
        w = db.scalar(select(ResourceWait).where(ResourceWait.email == "warte@example.org"))
        b = db.get(ResourceBooking, w.booking_id)
        assert w.status == "booked" and b.status == "confirmed"


def test_offer_expires_to_next():
    rid = make_resource("Halle Ablauf", units="day", mode="instant")
    d = day(8)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        start = rs._utc(datetime.combine(d, time()))
        for n, email in enumerate(("a@example.org", "b@example.org")):
            db.add(ResourceWait(resource_id=rid, token=f"tok-exp-{rid}-{n}", status="waiting", mode="day", starts_at=start,
                                ends_at=start + timedelta(days=1), name=email, email=email,
                                created_at=utcnow() - timedelta(hours=10 - n)))
        db.commit()
        res_wait.offer_next(db, res, start, start + timedelta(days=1))
        db.commit()
        first = db.scalar(select(ResourceWait).where(ResourceWait.token == f"tok-exp-{rid}-0"))
        assert first.status == "offered"
        first.offer_until = utcnow() - timedelta(minutes=1)
        db.commit()
    res_wait.expire_offers()
    with SessionLocal() as db:
        assert db.scalar(select(ResourceWait.status).where(ResourceWait.token == f"tok-exp-{rid}-0")) == "expired"
        assert db.scalar(select(ResourceWait.status).where(ResourceWait.token == f"tok-exp-{rid}-1")) == "offered"


def _staff_booking(rid: int, d, *, price_paid: bool = False, email: str = "kunde@example.org") -> int:
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="day", date_from=d.isoformat(), date_to=d.isoformat()), staff=True)
        b = rs.create(db, res, q, {"name": "Kunde", "email": email, "title": "Feier"}, {})
        b.status = "confirmed"
        rs._finalize(db, b)
        if price_paid:
            from app import payments as pay
            pay.mark_paid(db, b.payment, "transfer", "Test")
        db.commit()
        return b.id


def test_move_in_planner_reprices_and_mails():
    rid = make_resource("Saal Verschieben", units="day", mode="instant", price_day=10000)
    rid2 = make_resource("Saal Ziel", units="day", mode="instant", price_day=15000)
    bid = _staff_booking(rid, day(10))
    admin = login(*ADMIN)
    page = admin.get(f"/resources/planner?start={day(10).isoformat()}")
    assert page.status_code == 200 and 'draggable="true"' in page.text
    target = day(12)
    r = admin.post(f"/resources/bookings/{bid}/move", data={"csrf": csrf_of(page.text), "date": target.isoformat(),
                                                             "resource": str(rid2), "notify": "1"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        assert b.resource_id == rid2 and to_local(b.starts_at).date() == target and b.total_cents == 15000
        assert b.payment.amount_cents == 15000 and b.payment.status == "open"
        old = db.scalars(select(Payment).where(Payment.subject_id == bid, Payment.status == "cancelled")).all()
        assert old
    assert mails("kunde@example.org", "res_changed")
    # belegt → Fehler
    other = _staff_booking(rid2, day(14), email="z@example.org")
    r = admin.post(f"/resources/bookings/{other}/move", data={"csrf": csrf_of(page.text), "date": target.isoformat(),
                                                               "resource": str(rid2)})
    assert r.status_code == 409 and not r.json()["ok"]
    # Stunden-Buchung auf eine Ressource nur mit ganzen Tagen: Zieltag zählt
    rid3 = make_resource("Raum Stunden", units="hour", mode="instant", price_hour=1000)
    with SessionLocal() as db:
        res = db.get(Resource, rid3)
        q = rs.quote(db, res, rs.FormData(mode="hour", date=day(15).isoformat(), time_from="10:00", time_to="12:00"), staff=True)
        hb = rs.create(db, res, q, {"name": "H", "email": "", "title": "T"}, {}, internal=True)
        db.commit()
        hid = hb.id
    r = admin.post(f"/resources/bookings/{hid}/move", data={"csrf": csrf_of(page.text), "date": day(18).isoformat(),
                                                             "resource": str(rid)})
    assert r.json()["ok"], r.text
    with SessionLocal() as db:
        hb = db.get(ResourceBooking, hid)
        assert hb.mode == "day" and to_local(hb.starts_at).date() == day(18)


def test_edit_paid_booking_refund_and_extra_payment():
    rid = make_resource("Saal Bezahlt", units="day", mode="instant", price_day=10000, max_days=5)
    bid = _staff_booking(rid, day(16), price_paid=True)
    admin = login(*ADMIN)
    page = admin.get(f"/resources/bookings/{bid}/edit")
    assert page.status_code == 200 and "Änderung speichern" in page.text
    token = csrf_of(page.text)
    d = day(16)
    r = admin.post(f"/resources/bookings/{bid}/edit", data={
        "csrf": token, "mode": "day", "date_from": d.isoformat(), "date_to": (d + timedelta(days=1)).isoformat(),
        "title": "Feier", "name": "Kunde", "email": "kunde@example.org", "notify": "1"})
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        extra = db.scalars(select(Payment).where(Payment.subject_id == bid, Payment.purpose.like("Nachzahlung%"))).all()
        assert b.total_cents in (20000, 10000 + (b.total_cents - 10000)) and extra and extra[0].amount_cents == b.total_cents - 10000
    r = admin.post(f"/resources/bookings/{bid}/edit", data={
        "csrf": token, "mode": "day", "date_from": d.isoformat(), "date_to": d.isoformat(), "title": "Feier",
        "name": "Kunde", "email": "kunde@example.org", "price": "80"})
    with SessionLocal() as db:
        b = db.get(ResourceBooking, bid)
        assert b.total_cents == 8000 and b.payment.refunded_cents > 0


def test_reminders():
    rid = make_resource("Saal Erinnerung", units="day", mode="instant", remind_days=3, remind_staff_days=2,
                        remind_text="Schlüssel bei Herrn Maier", mailbox="haus@example.org")
    bid = _staff_booking(rid, to_local(utcnow()).date() + timedelta(days=1), email="erinnern@example.org")
    with SessionLocal() as db:
        db.get(ResourceBooking, bid).created_at = utcnow() - timedelta(days=5)
        db.commit()
    assert rs.send_reminders() >= 2
    m = mails("erinnern@example.org", "res_reminder")
    assert m and "Schlüssel bei Herrn Maier" in m[-1].body
    assert any("Erinnerung" in x.subject for x in mails("haus@example.org"))
    rs.send_reminders()
    assert len(mails("erinnern@example.org", "res_reminder")) == 1


def test_stats_csv_bulk_copy_export_import():
    rid = make_resource("Saal Statistik", units="day", mode="request", price_day=10000)
    _staff_booking(rid, day(2))
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="day", date_from=day(20).isoformat(), date_to=day(20).isoformat()), staff=True)
        b = rs.create(db, res, q, {"name": "Anfrage", "email": "anfrage@example.org", "title": "Party"}, {})
        b.status = "requested"
        db.commit()
        req = b.id
    admin = login(*ADMIN)
    page = admin.get(f"/resources/stats?year={day(2).year}")
    assert page.status_code == 200 and "Saal Statistik" in page.text
    csv = admin.get(f"/resources/stats?year={day(2).year}&format=csv")
    assert csv.status_code == 200 and "Saal Statistik" in csv.text
    lst = admin.get(f"/resources/bookings?resource={rid}&status=all")
    assert "Anfrage(n) ausgewählt" in lst.text
    r = admin.post("/resources/bookings/bulk", data={"csrf": csrf_of(lst.text), "ids": [str(req)], "action": "accept"})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(ResourceBooking, req).status == "confirmed"
    export = admin.get(f"/resources/bookings?resource={rid}&status=all&format=csv")
    assert export.status_code == 200 and "Buchungsnummer" in export.text and "Party" in export.text
    r = admin.post(f"/resources/{rid}/copy", data={"csrf": csrf_of(lst.text)})
    assert r.status_code == 303
    with SessionLocal() as db:
        clone = db.get(Resource, int(r.headers["location"].split("/")[2]))
        assert clone.name == "Saal Statistik (Kopie)" and clone.price_day == 10000 and not clone.active
    data = admin.get(f"/resources/{rid}/export.json")
    assert data.json()["format"] == "jitsii-ressource-1"
    r = admin.post("/resources/import", data={"csrf": csrf_of(lst.text)}, files={"file": ("r.json", data.content)})
    assert r.status_code == 303
    with SessionLocal() as db:
        imported = db.get(Resource, int(r.headers["location"].split("/")[2].split("?")[0]))
        assert imported.price_day == 10000 and imported.slug != slug_of(rid)
    bad = admin.post("/resources/import", data={"csrf": csrf_of(lst.text)}, files={"file": ("r.json", b"{}")})
    assert bad.headers["location"] == "/resources"


def test_club_login_tariff_and_monthly_bill():
    rid = make_resource("Vereinsheim", units="day", mode="instant", price_day=10000)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        res.tariffs.append(ResourceTariff(name="Vereine", percent=50))
        for c in db.scalars(select(ResourceClub).where(ResourceClub.email == "tsv@example.org")):
            db.delete(c)
        db.add(ResourceClub(name="TSV Otterberg", email="tsv@example.org", contact_name="Paul", tariff_name="Vereine",
                            billing="monthly"))
        db.commit()
    c = client()
    page = c.get("/r/login")
    c.post("/r/login/send", data={"csrf": csrf_of(page.text), "email": "tsv@example.org"})
    link = re.search(r"/r/login/\S+", mails("tsv@example.org", "res_club_login")[-1].body).group(0)
    r = c.get(link)
    assert r.status_code == 303 and r.headers["location"] == "/r/mein" and res_clubs.COOKIE in r.headers.get("set-cookie", "")
    assert c.get(link).headers["location"] == "/r/login"          # nur einmal gültig
    home = c.get("/r/mein")
    assert home.status_code == 200 and "TSV Otterberg" in home.text
    d = day(5)
    page = c.get(f"/r/{slug_of(rid)}")
    assert "Angemeldet als" in page.text
    r = c.post(f"/r/{slug_of(rid)}/book", data={"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(),
                                                 "date_to": d.isoformat(), "title": "Training"})
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.scalar(select(ResourceBooking).where(ResourceBooking.resource_id == rid))
        assert b.status == "confirmed" and b.total_cents == 5000 and b.billing == "monthly" and b.payment is None
        assert b.organizer == "TSV Otterberg" and b.email == "tsv@example.org"
        club = db.get(ResourceClub, b.club_id)
        month = to_local(b.starts_at).strftime("%Y-%m")
        assert month in res_clubs.months_with_items(db, club)
        cid = club.id
    admin = login(*ADMIN)
    page = admin.get(f"/resources/clubs/{cid}")
    assert page.status_code == 200 and "Abrechnen" in page.text
    admin.post(f"/resources/clubs/{cid}/bill", data={"csrf": csrf_of(page.text), "month": month})
    with SessionLocal() as db:
        p = db.scalar(select(Payment).where(Payment.kind == "resource_club", Payment.subject_id == cid))
        assert p.amount_cents == 5000
        assert db.scalar(select(ResourceBooking.billed_payment_id).where(ResourceBooking.resource_id == rid)) == p.id
    assert mails("tsv@example.org", "res_club_statement")
    assert c.post("/r/logout", data={"csrf": csrf_of(c.get("/r/mein").text)}).status_code == 303


def test_club_signup_needs_approval():
    settings(res_club_signup="1", res_club_mailbox="haus@example.org")
    with SessionLocal() as db:
        for c in db.scalars(select(ResourceClub).where(ResourceClub.email == "neu@example.org")):
            db.delete(c)
        db.commit()
    c = client()
    page = c.get("/r/verein")
    c.post("/r/verein", data={"csrf": csrf_of(page.text), "club_name": "Gesangverein", "email": "neu@example.org",
                              "privacy": "1"})
    with SessionLocal() as db:
        club = db.scalar(select(ResourceClub).where(ResourceClub.email == "neu@example.org"))
        assert club.pending and not res_clubs.send_login(db, "neu@example.org")
        cid = club.id
    admin = login(*ADMIN)
    page = admin.get("/resources/clubs")
    assert "wartet auf Freigabe" in page.text
    admin.post("/resources/clubs", data={"csrf": csrf_of(page.text), "id": str(cid), "action": "approve"})
    assert mails("neu@example.org", "res_club_login")
    settings(res_club_signup="0")
    assert client().get("/r/verein").status_code == 404


def test_cart_two_resources_one_mail_one_payment():
    r1 = make_resource("Saal Merkliste", units="day", mode="instant", price_day=10000)
    r2 = make_resource("Küche Merkliste", units="day", mode="instant", price_day=3000)
    c = client()
    d = day(9)
    r = public_book(c, slug_of(r1), {"mode": "day", "date_from": d.isoformat(), "date_to": d.isoformat(),
                                     "email": "merk@example.org", "action": "add"})
    assert r.status_code == 303 and r.headers["location"] == "/r?merkliste=1"
    assert "Ihre Merkliste" in c.get("/r").text
    page = c.get(f"/r/{slug_of(r2)}")
    assert "merk@example.org" in page.text                         # Angaben übernommen
    r = c.post(f"/r/{slug_of(r2)}/book", data={"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(),
                                                "date_to": d.isoformat(), "name": "Erika Muster", "email": "merk@example.org",
                                                "title": "Geburtstag"})
    assert r.status_code == 303 and "/r/b/" in r.headers["location"]
    confirm = mails("merk@example.org", "res_confirm_email")
    assert len(confirm) == 1 and "Saal Merkliste" in confirm[0].body and "Küche Merkliste" in confirm[0].body
    c.get(confirm_link("merk@example.org"))
    with SessionLocal() as db:
        rows = db.scalars(select(ResourceBooking).where(ResourceBooking.email == "merk@example.org")).all()
        assert len(rows) == 2 and len({b.group_ref for b in rows}) == 1 and all(b.status == "confirmed" for b in rows)
        assert rows[0].payment_id == rows[1].payment_id and rows[0].payment.amount_cents == 13000
        first = rows[0]
    assert len(mails("merk@example.org", "res_confirmed")) == 1
    # eine Teilstornierung storniert die offene Zahlung und fordert den Rest neu an
    admin = login(*ADMIN)
    token = csrf_of(admin.get(f"/resources/bookings/{first.id}").text)
    admin.post(f"/resources/bookings/{first.id}/cancel", data={"csrf": token})
    with SessionLocal() as db:
        rest = db.scalar(select(ResourceBooking).where(ResourceBooking.email == "merk@example.org",
                                                       ResourceBooking.status == "confirmed"))
        assert rest.payment is not None and rest.payment.amount_cents == rest.total_cents and rest.payment.status == "open"


def test_pages_render():
    rid = make_resource("Saal Seiten", units="day,hour", mode="request", price_day=1000)
    bid = _staff_booking(rid, day(11))
    admin = login(*ADMIN)
    for url in ("/resources", f"/resources/{rid}", f"/resources/{rid}/edit", "/resources/planner", "/resources/bookings",
                f"/resources/bookings/{bid}", f"/resources/bookings/{bid}/edit", "/resources/stats", "/resources/clubs",
                "/resources/calendars", "/resources/holidays", "/resources/new"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    pub = client()
    for url in ("/r", f"/r/{slug_of(rid)}", "/r/login", "/r/merkliste"):
        r = pub.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert pub.get("/r/mein").headers["location"] == "/r/login"


def test_photo_and_terms_upload():
    """Regression: request.form() liefert starlette-UploadFiles – Fotos und Nutzungsordnung wurden verworfen."""
    import io
    from PIL import Image
    from reportlab.pdfgen import canvas
    rid = make_resource("Saal Fotos", units="day")
    img = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(img, "PNG")
    pdf = io.BytesIO()
    cv = canvas.Canvas(pdf)
    cv.drawString(10, 10, "Nutzungsordnung")
    cv.save()
    admin = login(*ADMIN)
    token = csrf_of(admin.get(f"/resources/{rid}/edit").text)
    admin.post(f"/resources/{rid}/photos", data={"csrf": token}, files={"photos": ("saal.png", img.getvalue(), "image/png")})
    admin.post(f"/resources/{rid}/terms", data={"csrf": token}, files={"file": ("ordnung.pdf", pdf.getvalue(), "application/pdf")})
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        assert len(res.photos) == 1 and res.terms_file.endswith(".pdf")
    assert client().get(f"/r/{slug_of(rid)}/nutzungsordnung.pdf").content.startswith(b"%PDF")
