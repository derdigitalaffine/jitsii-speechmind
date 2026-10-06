"""Öffentliches Menü, Startseite für Bürger:innen, Suche über alle Bereiche und das Verzeichnis „Termine buchen“."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import delete

from app import public_nav as pn
from app.db import BookingPage, BookingWindow, LawText, SessionLocal, utcnow

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


@pytest.fixture(autouse=True)
def clean():
    settings(public_nav="", public_home="1", public_home_title="", public_home_text="", public_contact="",
             module_applications="1", module_forms="1", module_maps="1", module_laws="1", module_resources="1",
             module_bookings="1", module_krank="1", krank_public="0")
    with SessionLocal() as db:
        db.execute(delete(BookingPage).where(BookingPage.title.like("Bürgersprechstunde%")))
        db.commit()
    pn.invalidate()
    yield
    pn.invalidate()


def _page(listed=True, invite_only=False) -> str:
    with SessionLocal() as db:
        page = BookingPage(title="Bürgersprechstunde Bürgermeister", public_token=f"tok-{listed}-{invite_only}-x" * 2,
                           listed=listed, invite_only=invite_only, min_notice_hours=0, location="Rathaus")
        db.add(page)
        db.flush()
        start = (utcnow() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        db.add(BookingWindow(page_id=page.id, starts_at=start, ends_at=start + timedelta(hours=1)))
        db.commit()
        return page.public_token


def test_header_shows_all_public_modules_and_mobile_menu():
    html = client().get("/recht").text
    for label in ("Anträge", "Räume &amp; Plätze", "Karte", "Ortsrecht"):
        assert label in html
    assert "Termine buchen" not in html          # noch keine freigegebene Buchungsseite
    assert "Krankmeldung" not in html            # Krankmelder nicht ohne Konto erreichbar
    assert 'id="pubnav"' in html and 'data-bs-target="#pubnav"' in html
    assert 'aria-current="page"' in html          # Ortsrecht als aktuelle Seite markiert
    _page()
    pn.invalidate()
    html = client().get("/karte").text
    assert "Termine buchen" in html
    settings(module_maps="0")
    pn.invalidate()
    assert 'href="/karte"' not in client().get("/recht").text


def test_order_hidden_and_custom_links_via_admin():
    c = login(*ADMIN)
    page = c.get("/admin/oeffentlich")
    assert page.status_code == 200 and "Bereiche im Kopf" in page.text
    r = c.post("/admin/oeffentlich", data={
        "csrf": csrf_of(page.text), "order": ["recht", "karte", "antraege", "raeume", "termine", "krank"],
        "show": ["recht", "karte", "raeume"], "link_label": ["Homepage", "Kaputt", ""],
        "link_url": ["https://www.example.de", "javascript:alert(1)", ""], "public_home": "1",
        "public_home_title": "Bürgerportal Musterdorf", "public_contact": "Rathaus, Hauptstraße 1"})
    assert r.status_code == 303
    with SessionLocal() as db:
        from app.db import get_settings
        conf = json.loads(get_settings(db)["public_nav"])
    assert conf["hidden"] == ["antraege", "termine", "krank"] and conf["links"] == [{"label": "Homepage", "url": "https://www.example.de"}]
    pn.invalidate()
    html = client().get("/recht").text
    assert html.index('href="/recht"') < html.index('href="/karte"')
    assert 'href="/antraege"' not in html and "https://www.example.de" in html and "javascript:" not in html


def test_public_home_search_and_switch_off():
    settings(public_home_title="Bürgerportal Musterdorf", public_contact="Telefon 0123 456")
    r = client().get("/")
    assert r.status_code == 200 and "Bürgerportal Musterdorf" in r.text and "Telefon 0123 456" in r.text
    assert 'action="/suche"' in r.text and "Unsere Online-Angebote" in r.text
    assert "set-cookie" not in {k.lower() for k in r.headers}        # ohne Anmeldung kein Cookie
    settings(public_home="0")
    r = client().get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    # angemeldet bleibt „/“ das Dashboard
    assert "Übersicht" in login(*ADMIN).get("/").text


def test_search_and_booking_directory():
    token = _page()
    _page(listed=True, invite_only=True)          # nur mit Einladung → nie öffentlich
    pn.invalidate()
    with SessionLocal() as db:
        from app import laws as lx
        db.execute(delete(LawText).where(LawText.slug == "sprechsatzung"))
        law = LawText(slug="sprechsatzung", title="Satzung über die Bürgersprechstunde", body_md="# S\n\n### § 1 Zweck\n\nText.",
                      published=True)
        db.add(law)
        db.flush()
        lx.store(db, law)
        db.commit()
    d = client().get("/b")
    assert d.status_code == 200 and d.text.count("Bürgersprechstunde Bürgermeister") == 1
    assert f'href="/b/{token}"' in d.text and "Nächster freier Termin" in d.text
    s = client().get("/suche", params={"q": "Bürgersprechstunde"})
    assert s.status_code == 200 and f"/b/{token}" in s.text and "/recht/sprechsatzung" in s.text
    assert "Nichts gefunden" in client().get("/suche", params={"q": "xyzzyquatsch"}).text
    settings(module_bookings="0")
    pn.invalidate()
    assert client().get("/b").status_code == 404
