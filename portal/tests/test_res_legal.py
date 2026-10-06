"""Ressourcen mit verknüpften Rechtstexten: Benutzungsordnung (beim Buchen bestätigen), Gebührenordnung."""

import json
from datetime import timedelta

from app import res_admin, resources as rs
from app.db import Resource, SessionLocal, to_local, utcnow

from conftest import client, csrf_of, login, settings
from test_laws import make_law
from test_resources import ADMIN, make_resource, slug_of

MD_BO = "# Benutzungsordnung Grillhütte\n\n## § 1 Geltung\n\nGilt für die Grillhütte.\n\n## § 4 Ruhezeiten\n\nAb 22 Uhr Ruhe.\n"
MD_GO = "# Gebührenordnung Grillhütte\n\n## § 1 Gebühren\n\nPauschale 100 Euro.\n"


def setup_function():
    settings(module_resources="1", module_laws="1")


def test_link_laws_accept_and_show():
    bo = make_law("bo-grillhuette", MD_BO, short="BO")
    go = make_law("go-grillhuette", MD_GO)
    rid = make_resource("Grillhütte Recht", units="day", price_day=10000)
    admin = login(*ADMIN)
    page = admin.get(f"/resources/{rid}/edit")
    assert "Rechtstexte verknüpfen" in page.text
    r = admin.post(f"/resources/{rid}/edit", data={
        "csrf": csrf_of(page.text), "name": "Grillhütte Recht", "units": "day", "price_day": "100", "active": "1", "public": "1",
        "legal_law": [str(bo), str(go), ""], "legal_para": ["§ 4", "", ""], "legal_role": ["terms", "fees", "terms"],
        "legal_accept": ["0"]})
    assert r.status_code == 303
    with SessionLocal() as db:
        raw = rs.legal_raw(db.get(Resource, rid))
        assert [(x["role"], x["accept"], x["anchor"]) for x in raw] == [("terms", True, "p4"), ("fees", False, "")]
    slug = slug_of(rid)
    pub = client()
    page = pub.get(f"/r/{slug}")
    assert "Benutzungsordnung: <a class=\"law-ref\" href=\"/recht/bo-grillhuette/p4\"" in page.text
    assert "Gebühren-/Entgeltordnung: <a class=\"law-ref\" href=\"/recht/go-grillhuette\"" in page.text
    assert "Ich habe die <a class=\"law-ref\"" in page.text and "Benutzungsordnung (§ 4 BO)" in page.text
    d = to_local(utcnow()).date() + timedelta(days=20)
    form = {"csrf": csrf_of(page.text), "mode": "day", "date_from": d.isoformat(), "date_to": d.isoformat(), "title": "Fest",
            "name": "Erika", "email": "erika@example.org", "action": "book"}
    r = pub.post(f"/r/{slug}/book", data=form)
    assert "Bitte die Nutzungsbedingungen bestätigen." in (r.text if r.status_code == 200 else pub.get(r.headers["location"]).text)
    with SessionLocal() as db:
        from app.db import ResourceBooking
        assert not db.query(ResourceBooking).filter_by(resource_id=rid).count()
        r = pub.post(f"/r/{slug}/book", data={**form, "terms": "1"})
        b = db.query(ResourceBooking).filter_by(resource_id=rid).one()
        assert rs.confirmation_pdf(db, b)[:4] == b"%PDF"
    # Rechtstext zeigt die Ressource
    assert f"/r/{slug}" in pub.get("/recht/bo-grillhuette").text
    # unveröffentlicht → nicht mehr verlinkt und nicht mehr zu bestätigen
    with SessionLocal() as db:
        from app.db import LawText
        db.get(LawText, bo).published = False
        db.commit()
        assert [x["role"] for x in rs.legal_refs(db, db.get(Resource, rid))] == ["fees"]


def test_export_import_maps_laws_by_slug():
    go = make_law("go-export", MD_GO)
    rid = make_resource("Halle Export", units="day", price_day=5000)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        res.legal_json = json.dumps([{"law_id": go, "anchor": "", "para": "", "role": "fees", "accept": False},
                                     {"law_id": 999999, "anchor": "", "para": "", "role": "terms", "accept": True}])
        db.commit()
        raw = res_admin.export(db.get(Resource, rid))
        data = json.loads(raw)
        assert [x["slug"] for x in data["legal"]] == ["go-export"]
        new = res_admin.import_(db, raw, db.get(Resource, rid).owner)
        db.flush()
        assert [(x["law_id"], x["role"]) for x in rs.legal_raw(new)] == [(go, "fees")]
        db.rollback()
