"""Portal-Menü: neue Gruppen, nur Sichtbares, Favoriten (Stern und „Menü anpassen“), ausgeblendete Gruppen."""

import json

import pytest

from app import nav
from app.db import SessionLocal, User

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


@pytest.fixture(autouse=True)
def reset():
    settings(module_forms="1", module_applications="1", module_laws="1", module_maps="1", module_polls="1")
    with SessionLocal() as db:
        for u in db.query(User):
            u.nav_json = ""
        db.commit()
    yield


def nav_html(html: str) -> str:
    start = html.index('id="app-nav"')
    return html[start:html.index("app-nav-custom", start) + 400]


def test_groups_and_single_active_entry():
    c = login(*ADMIN)
    html = nav_html(c.get("/forms/inbox").text)
    labels = [v for v in nav.GROUPS.values() if f"<span>{v.replace('&', '&amp;')}</span>" in html]
    assert labels[0] == "Mein Arbeitsplatz" and labels[-1] == "Administration"
    assert html.count('aria-current="page"') == 1                 # nur „Zum Ausfüllen“, nicht auch „Formulare“
    assert 'href="/forms/inbox" aria-current="page"' in html
    assert 'data-nav-id="trash"' in html and 'href="/profile/menu"' in html
    # Abgeschaltete Module erscheinen nicht
    settings(module_laws="0")
    assert 'href="/laws"' not in nav_html(c.get("/").text)


def test_pin_and_customize():
    c = login(*ADMIN)
    page = c.get("/")
    token = csrf_of(page.text)
    r = c.post("/nav/pin", data={"csrf": token, "id": "recht", "on": "1"})
    assert r.json() == {"ok": True, "fav": ["recht"]}
    c.post("/nav/pin", data={"csrf": token, "id": "users", "on": "1"})
    assert c.post("/nav/pin", data={"csrf": token, "id": "gibtsnicht", "on": "1"}).json()["fav"] == ["recht", "users"]
    html = nav_html(c.get("/").text)
    favs = html[html.index('id="nav-favs"'):html.index("</ul>", html.index('id="nav-favs"'))]
    assert favs.index('data-nav-id="recht"') < favs.index('data-nav-id="users"')
    assert c.post("/nav/pin", data={"csrf": token, "id": "recht", "on": "0"}).json()["fav"] == ["users"]
    # Menü anpassen: Reihenfolge, Gruppe ausblenden
    page = c.get("/profile/menu")
    assert page.status_code == 200 and "Reihenfolge der Favoriten" in page.text
    shown = [g for g in nav.GROUPS if g != "comm"]
    c.post("/profile/menu", data={"csrf": csrf_of(page.text), "fav": ["users", "map", "forms"],
                                  "fav_order": ["map", "users"], "show": shown})
    with SessionLocal() as db:
        data = json.loads(db.query(User).filter(User.email == ADMIN[0]).one().nav_json)
    assert data == {"fav": ["map", "users", "forms"], "hidden": ["comm"], "closed": [g for g in nav.GROUPS if g != "work"]}
    html = nav_html(c.get("/").text)
    assert "<span>Kommunikation</span>" not in html and "1 ausgeblendet" in html
    # auf einer Seite der ausgeblendeten Gruppe erscheint sie trotzdem
    assert "<span>Kommunikation</span>" in nav_html(c.get("/meetings").text)
    c.post("/profile/menu", data={"csrf": csrf_of(page.text), "reset": "1"})
    assert "<span>Kommunikation</span>" in nav_html(c.get("/").text)


def test_limited_user_sees_only_allowed_entries():
    c = login(*ADMIN)
    page = c.get("/admin/users")
    with SessionLocal() as db:
        from app.security import hash_password
        u = db.query(User).filter(User.email == "menu-user@example.org").one_or_none()
        if u is None:
            u = User(email="menu-user@example.org", name="Menü Nutzer", password_hash=hash_password("menu-passwort-123"),
                     permissions="video")
            db.add(u)
        u.must_change_password = False
        db.commit()
    assert page.status_code == 200
    html = nav_html(login("menu-user@example.org", "menu-passwort-123").get("/").text)
    assert 'href="/meetings"' in html and 'href="/admin/users"' not in html and "<span>Administration</span>" not in html


def test_expansion_account_persistence_preserved_when_pinning():
    c=login(*ADMIN);page=c.get('/');token=csrf_of(page.text)
    assert c.post('/nav/expand',data={'closed':['know']}).status_code==400
    r=c.post('/nav/expand',data={'csrf':token,'closed':['know','invalid']});assert r.status_code==200
    c.post('/nav/pin',data={'csrf':token,'id':'map','on':'1'})
    with SessionLocal() as db:
        u=db.query(User).filter(User.email==ADMIN[0]).one()
        assert nav.prefs(u)['closed']==['know'] and nav.prefs(u)['fav']==['map']
        old=u.nav_json;u.nav_json='{"fav": [null, {}], "closed": null}';assert nav.prefs(u)['fav']==[];u.nav_json=old
    page=login(*ADMIN).get('/karte');assert page.status_code==200 and 'Meine Karten' in page.text
