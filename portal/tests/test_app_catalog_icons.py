"""Antragskatalog: Symbole (Vorschlag, je Antrag, je Kategorie), Farbe, umschaltbare Tabellenansicht."""

import secrets

from sqlalchemy import select

from app import applications as apps, icons
from app.db import Form, SessionLocal, User

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def _form(title, category, **kw) -> int:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN[0]))
        f = Form(owner_id=admin.id, title=title, kind="application", app_category=category, app_catalog=True,
                 public_token="tok-ic-" + secrets.token_hex(4), schema_json="[]", **kw)
        db.add(f)
        db.commit()
        return f.id


def test_suggest():
    assert icons.suggest("Hundesteuer anmelden") == "fa-dog"
    assert icons.suggest("Sondernutzung öffentlicher Straße") == "fa-road"
    assert icons.suggest("Gewerbeanmeldung") in ("fa-store", "fa-briefcase")
    assert icons.suggest("xyz") == "" and icons.clean("fa-evil<script>") == ""


def test_catalog_icons_categories_and_table():
    settings(module_forms="1", module_applications="1", apps_category_styles="{}")
    dog = _form("Hund anmelden", "Steuern")
    own = _form("Brauchtumsfeuer", "Ordnung", app_icon="fa-star", app_color="#123456")
    c = client()
    page = c.get("/antraege")
    assert page.status_code == 200 and "fa-dog" in page.text and 'fa-solid fa-star' in page.text and "--app-color: #123456" in page.text
    # Kategorie-Symbol greift für Anträge ohne eigene Wahl
    admin = login(*ADMIN)
    inbox = admin.get("/forms/applications")
    assert "Kategorien im Antragskatalog" in inbox.text
    r = admin.post("/forms/applications/categories", data={"csrf": csrf_of(inbox.text), "cat": ["Steuern", "Ordnung"],
                                                          "cat_icon": ["fa-euro-sign", ""], "cat_color": ["#00aa00", "#000000"],
                                                          "cat_color_on": ["1", "0"]})
    assert r.status_code == 303
    with SessionLocal() as db:
        styles = apps.category_styles(db)
        assert styles == {"Steuern": {"icon": "fa-euro-sign", "color": "#00aa00"}}
        assert apps.style_of(db.get(Form, dog), styles) == {"icon": "fa-euro-sign", "color": "#00aa00", "auto": True}
        assert apps.style_of(db.get(Form, own), styles)["icon"] == "fa-star"
    # Antrag: eigenes Symbol und Farbe speichern
    page = admin.get(f"/forms/{dog}/application")
    assert 'id="icon-list"' in page.text and "js-icon-picker" in page.text
    # Tabellenansicht umschalten und merken
    t = c.get("/antraege?ansicht=tabelle")
    assert "app-table" in t.text and "jsm_app_catalog_view=tabelle" in t.headers.get("set-cookie", "")
    assert "app-table" in c.get("/antraege").text
    assert "app-table" not in c.get("/antraege?ansicht=karten").text
    # Voreinstellung der Verwaltung
    settings(apps_catalog_view="tabelle")
    assert "app-table" in client().get("/antraege").text
    settings(apps_catalog_view="karten")
