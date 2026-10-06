"""Übersicht nach der Anmeldung: Handlungsbedarf, Heute, Schnellaktionen und neue Kacheln."""

from sqlalchemy import delete, select

from app import home
from app.db import Meeting, SessionLocal, ShortLink, User, utcnow

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def _admin_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == ADMIN[0]))


def test_today_quick_actions_and_new_tiles():
    settings(module_laws="1", module_shortlinks="1", module_polls="1", module_forms="1")
    uid = _admin_id()
    with SessionLocal() as db:
        db.execute(delete(Meeting).where(Meeting.room == "dash-heute"))
        db.execute(delete(ShortLink).where(ShortLink.code == "dash-top"))
        db.add(Meeting(owner_id=uid, title="Abstimmung Haushalt", room="dash-heute", starts_at=utcnow()))
        db.add(ShortLink(code="dash-top", target_url="https://example.org", title="Top-Link", owner_id=uid, visit_count=42))
        u = db.get(User, uid)
        u.dashboard_json = ""
        u.nav_json = '{"fav": ["recht"], "hidden": []}'
        db.commit()
    c = login(*ADMIN)
    html = c.get("/").text
    assert "Handlungsbedarf" in html and 'id="dash-today"' in html
    today = html[html.index('id="dash-today-title"'):html.index('id="dash-help"')]
    assert "Abstimmung Haushalt" in today and "/meetings/" in today
    quick = html[html.index('aria-label="Schnellaktionen"'):html.index('id="dash-today"')]
    assert "Meeting starten" in quick and "Besprechung planen" in quick and "Profil" not in quick
    for key in ("favorites", "laws", "shortlinks", "votes"):
        assert f'data-key="{key}"' in html
    assert 'data-key="quick"' not in html                        # Schnellzugriff steht jetzt oben
    fav = html[html.index('data-key="favorites"'):html.index('data-key="favorites"') + 1500]
    assert 'href="/recht"' in fav
    assert "/s/dash-top" in html and ">42<" in html
    # Kachel ausblenden bleibt wie bisher möglich
    r = c.post("/dashboard/layout", data={"csrf": csrf_of(html), "order": "laws,favorites", "hidden": "shortlinks"})
    assert r.json()["ok"]
    html = c.get("/").text
    assert html.index('data-key="laws"') < html.index('data-key="favorites"')
    tile = html[html.index('data-key="shortlinks"'):html.index('data-key="shortlinks"') + 900]
    assert "Ausgeblendet." in tile


def test_actions_sorted_by_urgency():
    with SessionLocal() as db:
        user = db.get(User, _admin_id())
        top, cache = home.overview(db, user, {"forms", "polls"})
    levels = [a["level"] for a in top["actions"]]
    order = {"danger": 0, "warning": 1, "primary": 2, "secondary": 3}
    assert levels == sorted(levels, key=order.get)
    assert "inbox" in cache                                       # Daten werden für die Kacheln wiederverwendet
