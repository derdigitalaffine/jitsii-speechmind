"""Körperschaften und Einrichtungen (zentrale Stammdaten) und ihre Nutzung in den Modulen."""

import base64

from sqlalchemy import select

from app import krank, orgs
from app.db import Form, KrankEmployer, LawLevel, Organization, Resource, SessionLocal, Setting, User, seed_orgs
from app.security import hash_password
from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _user(email, perms):
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(email=email, name=email.split("@")[0], password_hash=hash_password("passwort-123"), permissions=perms))
            db.commit()


def test_seed_from_law_tree_and_krank_employers():
    with SessionLocal() as db:
        vg = db.scalar(select(Organization).where(Organization.kind == "vg"))
        assert vg is not None and vg.name.startswith("Verbandsgemeinde")
        names = {o.name for o in vg.children}
        assert "Stadt Otterberg" in names and "Ortsgemeinde Otterbach" in names
        assert db.scalar(select(Organization).where(Organization.name == "Stadt Otterberg")).kind == "stadt"
        level = db.scalar(select(LawLevel).where(LawLevel.kind == "vg"))
        assert level.org_id == vg.id
        # Arbeitgeber aus dem Krankmelder werden einmalig übernommen
        db.add(KrankEmployer(name="Kita Sonnenschein"))
        db.add(KrankEmployer(name="Ortsgemeinde Otterbach"))
        db.delete(db.get(Setting, "migrated_orgs"))
        db.flush()
        seed_orgs(db)
        db.commit()
        kita = db.scalar(select(KrankEmployer).where(KrankEmployer.name == "Kita Sonnenschein"))
        assert kita.org is not None and kita.org.kind == "einrichtung"
        og = db.scalar(select(KrankEmployer).where(KrankEmployer.name == "Ortsgemeinde Otterbach"))
        assert og.org.kind == "og"                                       # gleichnamige Körperschaft verknüpft
        assert db.scalar(select(Organization).where(Organization.name == "Verbandsgemeinde Otterbach-Otterberg").where(Organization.kind == "vg")) is not None


def test_admin_crud_logo_and_permission():
    _user("stamm@example.org", "orgs")
    _user("ohne@example.org", "video")
    assert login("ohne@example.org", "passwort-123").get("/admin/orgs").status_code == 403
    c = login("stamm@example.org", "passwort-123")
    page = c.get("/admin/orgs/new")
    with SessionLocal() as db:
        vg_id = db.scalar(select(Organization.id).where(Organization.kind == "vg"))
    r = c.post("/admin/orgs/new", data={"csrf": csrf_of(page.text), "name": "Ortsgemeinde Heiligenmoschel", "kind": "og",
                                         "parent_id": str(vg_id), "active": "1", "email": "og@heiligenmoschel.de",
                                         "website": "heiligenmoschel.de", "color": "#aa3300"},
               files={"logo": ("wappen.png", PNG, "image/png")})
    assert r.status_code == 303
    with SessionLocal() as db:
        og = db.scalar(select(Organization).where(Organization.name == "Ortsgemeinde Heiligenmoschel"))
        assert og.parent_id == vg_id and og.logo and og.website == "https://heiligenmoschel.de" and og.color == "#aa3300"
        oid = og.id
    logo = client().get(f"/org/{oid}/logo")
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    # Einrichtung darunter, Zyklus wird verhindert
    page = c.get(f"/admin/orgs/new?parent={oid}")
    c.post("/admin/orgs/new", data={"csrf": csrf_of(page.text), "name": "Kita Regenbogen", "kind": "kita", "parent_id": str(oid), "active": "1"})
    with SessionLocal() as db:
        kita = db.scalar(select(Organization).where(Organization.name == "Kita Regenbogen"))
        assert orgs.body_of(kita).id == oid
        kid = kita.id
    page = c.get(f"/admin/orgs/{oid}")
    c.post(f"/admin/orgs/{oid}", data={"csrf": csrf_of(page.text), "name": "Ortsgemeinde Heiligenmoschel", "kind": "og",
                                       "parent_id": str(kid), "active": "1"})
    with SessionLocal() as db:
        assert db.get(Organization, oid).parent_id == vg_id
    # SVG als Wappen abgelehnt, Löschen bei Verwendung verhindert
    page = c.get(f"/admin/orgs/{kid}")
    c.post(f"/admin/orgs/{kid}", data={"csrf": csrf_of(page.text), "name": "Kita Regenbogen", "kind": "kita", "parent_id": str(oid), "active": "1"},
           files={"logo": ("x.svg", b"<svg onload='alert(1)'/>", "image/svg+xml")})
    with SessionLocal() as db:
        assert db.get(Organization, kid).logo == ""
        db.add(Resource(name="Dorfgemeinschaftshaus", slug="dgh-heiligenmoschel", provider_id=oid))
        db.commit()
    c.post(f"/admin/orgs/{oid}/delete", data={"csrf": csrf_of(page.text)})
    with SessionLocal() as db:
        assert db.get(Organization, oid) is not None


def test_krank_employers_grouped_by_body():
    with SessionLocal() as db:
        og = db.scalar(select(Organization).where(Organization.name == "Ortsgemeinde Otterbach"))
        kita = Organization(name="Kita Pusteblume", kind="kita", parent=og)
        db.add(kita)
        db.flush()
        e1 = KrankEmployer(name="Kita Pusteblume (Arbeitgeber)", org=kita)
        e2 = KrankEmployer(name="Freier Träger")
        db.add_all([e1, e2])
        db.flush()
        groups = dict(krank.employer_groups([e1, e2]))
        assert [e.name for e in groups["Ortsgemeinde Otterbach"]] == ["Kita Pusteblume (Arbeitgeber)"]
        assert list(groups)[-1] == "Weitere"
        db.rollback()


def test_application_responsible_body_in_catalog():
    settings(module_applications="1", module_forms="1")
    c = login(*ADMIN)
    page = c.get("/forms")
    r = c.post("/forms", data={"csrf": csrf_of(page.text), "title": "Hund anmelden", "kind": "application"})
    fid = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        og = db.scalar(select(Organization).where(Organization.name == "Stadt Otterberg"))
    page = c.get(f"/forms/{fid}/application")
    assert 'name="org_id"' in page.text
    c.post(f"/forms/{fid}/application", data={"csrf": csrf_of(page.text), "is_application": "1", "app_catalog": "1", "org_id": str(og.id)})
    with SessionLocal() as db:
        form = db.get(Form, fid)
        assert form.org_id == og.id
        form.public_token = form.public_token or "tok-hund-anmelden-1234"
        form.active = True
        db.commit()
    cat = client().get("/antraege").text
    assert "Hund anmelden" in cat and "Stadt Otterberg" in cat and 'data-org="' in cat
