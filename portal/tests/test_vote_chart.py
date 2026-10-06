"""Live-Ansicht von Abstimmungen: Balken liegend oder stehend (Voreinstellung je Abstimmung, umschaltbar)."""

import json

from sqlalchemy import select

from app.db import SessionLocal, Vote

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def test_chart_default_and_live_toggle():
    settings(module_votes="1")
    c = login(*ADMIN)
    page = c.get("/votes/new")
    assert page.status_code == 200 and 'name="chart"' in page.text
    q = [{"title": "Sommerfest?", "kind": "single", "options": [{"label": "Ja"}, {"label": "Nein"}]}]
    r = c.post("/votes/new", data={"csrf": csrf_of(page.text), "title": "Sommerfest", "results": "live", "access": "public",
                                   "chart": "column", "questions_json": json.dumps(q)})
    assert r.status_code == 303, r.text[:300]
    with SessionLocal() as db:
        vote = db.scalar(select(Vote).where(Vote.title == "Sommerfest").order_by(Vote.id.desc()))
        assert vote.chart == "column"
        vid = vote.id
    live = c.get(f"/votes/{vid}/live")
    assert live.status_code == 200 and 'data-chart="column"' in live.text and 'aria-label="Balken stehend"' in live.text
    copy = c.post(f"/votes/{vid}/copy", data={"csrf": csrf_of(live.text)})
    with SessionLocal() as db:
        assert db.scalar(select(Vote).where(Vote.title == "Sommerfest (Kopie)")).chart == "column"
    assert copy.status_code == 303
