"""Preisbestandteile nach Personenzahl (je Person, je angefangene N Personen, Staffel, Mindest-/Höchstbetrag)
und Storno je Bestandteil – am Beispiel Grillplatz."""

import json
from datetime import timedelta

from app import resources as rs
from app.db import Resource, ResourceBooking, ResourceExtra, SessionLocal, to_local, utcnow

from conftest import client, csrf_of, login
from test_resources import ADMIN, make_resource, module_on, slug_of  # noqa: F401  (Fixture)


def _grill(**kw) -> int:
    rid = make_resource("Grillplatz Weiher", units="day", mode="instant", price_day=10000, deposit_cents=30000,
                        cancel_fee_percent=100, cancel_free_days=14, self_cancel=True, **kw)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        res.extras += [
            ResourceExtra(name="Wasser, Kanal, Strom", per="persons", per_n=25, price_cents=1000, mandatory=True,
                          cancel_rule="refund", position=0),
            ResourceExtra(name="Reinigung", per="tier", mandatory=True, position=1,
                          tiers_json=json.dumps(rs.parse_tiers("bis 50: 20; bis 100: 35,50; darüber: 50"))),
            ResourceExtra(name="Nachvermietung", per="once", price_cents=2500, cancel_rule="only", cancel_days=7, position=2),
            ResourceExtra(name="Bierzeltgarnitur", per="person", price_cents=150, min_cents=1000, max_cents=6000, position=3),
        ]
        db.commit()
    return rid


def _quote(rid, d, persons, **extra):
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        return rs.quote(db, res, rs.FormData(mode="day", date_from=d.isoformat(), date_to=d.isoformat(), persons=str(persons),
                                             **extra))


def test_parse_tiers_and_amounts():
    assert rs.parse_tiers("bis 50: 20; bis 100 Personen = 35,50\ndarüber: 1.000") == [
        {"upto": 50, "cents": 2000}, {"upto": 100, "cents": 3550}, {"upto": 0, "cents": 100000}]
    assert rs.tiers_text(rs.parse_tiers("darüber: 50; bis 10: 5")) == "bis 10: 5,00; darüber: 50,00"
    ex = ResourceExtra(per="persons", per_n=25, price_cents=1000)
    assert [rs.extra_amount(ex, 1, p, 1, 0)[0] for p in (1, 25, 26, 50, 51)] == [1000, 1000, 2000, 2000, 3000]
    ex = ResourceExtra(per="person", price_cents=150, min_cents=1000, max_cents=6000)
    assert [rs.extra_amount(ex, 1, p, 1, 0)[0] for p in (2, 10, 100)] == [1000, 1500, 6000]


def test_quote_by_persons():
    rid = _grill()
    d = to_local(utcnow()).date() + timedelta(days=30)
    q = _quote(rid, d, 60, extra_4="1")
    labels = {ln["label"]: ln["cents"] for ln in q["lines"]}
    assert q["ok"], q["errors"]
    assert labels["Wasser, Kanal, Strom × 3 (je angefangene 25 Personen)"] == 3000
    assert labels["Reinigung (bis 100 Personen)"] == 3550
    assert labels["Bierzeltgarnitur × 60 Personen (Höchstbetrag)"] == 6000
    assert not any("Nachvermietung" in k for k in labels) and q["cancel_only"] == [{"label": "Nachvermietung", "cents": 2500, "days": 7}]
    assert q["total"] == 10000 + 3000 + 3550 + 6000 + 30000
    assert _quote(rid, d, 120)["lines"][1]["cents"] == 5000   # darüber
    # öffentlich: Personenzahl ist Pflicht und steht im ersten Schritt
    slug = slug_of(rid)
    c = client()
    page = c.get(f"/r/{slug}")
    assert "Wie viele Personen?" in page.text and "je angefangene 25 Personen" in page.text
    assert "„Nachvermietung“ wird nur bei Absage weniger als 7 Tage vor Beginn berechnet" in page.text
    r = c.post(f"/r/{slug}/quote", data={"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(),
                                         "date_to": d.isoformat()}).json()
    assert not r["ok"] and any("Personenzahl" in e for e in r["errors"])


def _booking(rid, days_ahead, persons=60) -> int:
    d = to_local(utcnow()).date() + timedelta(days=days_ahead)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        q = rs.quote(db, res, rs.FormData(mode="day", date_from=d.isoformat(), date_to=d.isoformat(), persons=str(persons)),
                     staff=True)
        b = rs.create(db, res, q, {"name": "Kunde", "email": "k@example.org", "persons": persons, "title": "Grillfest"}, {})
        b.status = "confirmed"
        db.commit()
        return b.id


def test_cancel_fee_per_component():
    rid = _grill()
    with SessionLocal() as db:
        early = db.get(ResourceBooking, _booking(rid, 30))
        assert rs.cancel_fee_lines(early) == []                       # rechtzeitig: alles zurück
        mid = db.get(ResourceBooking, _booking(rid, 10))
        # innerhalb 14 Tagen: Pauschale + Reinigung (Storno-Regel 100 %), Nebenkosten erstattet, Nachvermietung erst ab 7 Tagen
        assert rs.cancel_fee_lines(mid) == [{"label": "Stornogebühr (100 %)", "cents": 10000 + 3550}]
        late = db.get(ResourceBooking, _booking(rid, 3))
        assert rs.cancel_fee(late) == 10000 + 3550 + 2500
        assert "Nachvermietung" in [x["label"] for x in rs.cancel_fee_lines(late)]
        # Bestandteil „bleibt fällig“ ohne Storno-Regel der Ressource
        res = db.get(Resource, rid)
        res.cancel_fee_percent = 0
        res.extras[0].cancel_rule, res.extras[0].cancel_days = "keep", 5
        db.commit()
    keep = _booking(rid, 3)
    with SessionLocal() as db:
        b = db.get(ResourceBooking, keep)
        assert rs.cancel_fee_lines(b) == [{"label": "Wasser, Kanal, Strom × 3 (je angefangene 25 Personen) (bleibt fällig)",
                                           "cents": 3000}, {"label": "Nachvermietung", "cents": 2500}]
        assert "Ausnahme:" in rs.cancel_rules_text(db.get(Resource, rid))


def test_editor_saves_person_fields():
    rid = make_resource("Grillplatz Editor", units="day", price_day=10000)
    admin = login(*ADMIN)
    page = admin.get(f"/resources/{rid}/edit")
    assert "Preisbestandteil hinzufügen" not in page.text   # Knopf entsteht per JS; Daten liegen im JSON
    form = {"csrf": csrf_of(page.text), "name": "Grillplatz Editor", "units": "day", "price_day": "100",
            "extras_json": json.dumps([
                {"name": "Nebenkosten", "per": "persons", "per_n": "25", "price": "10", "mandatory": True, "active": True,
                 "cancel_rule": "refund"},
                {"name": "Reinigung", "per": "tier", "tiers": "bis 50: 20; darüber: 40", "min": "", "max": "", "active": True},
                {"name": "Nachvermietung", "per": "once", "price": "25", "cancel_rule": "only", "cancel_days": "7", "active": True}])}
    r = admin.post(f"/resources/{rid}/edit", data=form)
    assert r.status_code == 303
    with SessionLocal() as db:
        x = {e.name: e for e in db.get(Resource, rid).extras}
        assert x["Nebenkosten"].per_n == 25 and x["Nebenkosten"].cancel_rule == "refund"
        assert rs.tiers(x["Reinigung"]) == [{"upto": 50, "cents": 2000}, {"upto": 0, "cents": 4000}]
        assert x["Nachvermietung"].cancel_rule == "only" and x["Nachvermietung"].cancel_days == 7
