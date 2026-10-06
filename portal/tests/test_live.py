"""Live-Umfragen: anlegen, Fragen (Auswahl, Ja/Nein, Skala, Sterne, Schieberegler), Teilnahme per QR ohne Namen
(je Gerät eine änderbare Antwort), moderierter/freier Ablauf, Ergebnis sofort/nach Freigabe, Präsentationsmodus."""

import pytest
from sqlalchemy import delete, select

from app import live as lv
from app.db import LiveAnswer, LivePoll, SessionLocal

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


@pytest.fixture(autouse=True)
def module_on():
    settings(module_polls="1")
    with SessionLocal() as db:
        db.execute(delete(LivePoll))
        db.commit()
    yield


def make(c, pacing="moderated") -> tuple[int, str]:
    page = c.get("/votes")
    r = c.post("/votes/live/new", data={"csrf": csrf_of(page.text), "title": "Bürgerversammlung", "pacing": pacing})
    assert r.status_code == 303
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    edit = c.get(f"/votes/live/{pid}")
    token = csrf_of(edit.text)
    for data in ({"kind": "single", "title": "Lieblingsort?", "options": "Weiher\nSpielplatz\nKirche", "chart": "pie"},
                 {"kind": "scale", "title": "Wie zufrieden?", "min": "1", "max": "5", "low": "gar nicht", "high": "sehr",
                  "show_results": "release"},
                 {"kind": "slider", "title": "Budget in Tsd. €", "min": "0", "max": "200", "step": "10", "unit": "T€",
                  "chart": "number"},
                 {"kind": "multi", "title": "Was fehlt?", "options": "Bänke\nLicht\nBäume\nToiletten", "max_choices": "2"}):
        assert c.post(f"/votes/live/{pid}/fragen", data={"csrf": token, **data}).status_code == 303
    with SessionLocal() as db:
        return pid, db.get(LivePoll, pid).public_token


def answer(c, token, device, qid, value, header=True):
    return c.post(f"/l/{token}/answer", json={"question": qid, "value": value},
                  headers={"X-Live-Device": device} if header else {})


def join(token):
    c = client()
    page = c.get(f"/l/{token}")
    assert page.status_code == 200 and "ohne Namen" in page.text.replace("Ohne Namen", "ohne Namen")
    return c, c.cookies.get(lv.DEVICE_COOKIE)


def test_moderated_flow_device_answers_and_release():
    admin = login(*ADMIN)
    pid, token = make(admin)
    with SessionLocal() as db:
        qs = [q.id for q in db.get(LivePoll, pid).questions]
    c, dev = join(token)
    assert len(dev) == 32
    assert c.get(f"/l/{token}/state.json").json()["status"] == "draft"
    assert answer(c, token, dev, qs[0], {"o": "o1"}).status_code == 409          # noch nicht gestartet
    edit = admin.get(f"/votes/live/{pid}")
    admin.post(f"/votes/live/{pid}/status", data={"csrf": csrf_of(edit.text), "action": "open"})
    st = c.get(f"/l/{token}/state.json").json()
    assert st["status"] == "open" and [q["id"] for q in st["questions"]] == [qs[0]]   # moderiert: nur die aktuelle
    assert answer(c, token, dev, qs[0], {"o": "o1"}, header=False).status_code == 403  # fremde Seite ohne Kennung
    assert answer(c, token, dev, qs[1], {"n": 3}).status_code == 409                    # nicht aktiv
    r = answer(c, token, dev, qs[0], {"o": "o1"}).json()
    assert r["ok"] and r["questions"][0]["results"]["rows"][0]["count"] == 1           # Ergebnis sofort
    answer(c, token, dev, qs[0], {"o": "o2"})                                            # Antwort ändern
    c2, dev2 = join(token)
    answer(c2, token, dev2, qs[0], {"o": "o2"})
    with SessionLocal() as db:
        poll = db.get(LivePoll, pid)
        rows = lv.tally(db, poll.questions[0])["rows"]
        assert [r["count"] for r in rows] == [0, 2, 0]
        assert db.scalar(select(LiveAnswer.device).limit(1)) != dev                   # nur Hash gespeichert
    # weiter zur Skala (Ergebnis erst nach Freigabe)
    admin.post(f"/votes/live/{pid}/schritt", data={"csrf": csrf_of(edit.text), "dir": "next"})
    r = answer(c, token, dev, qs[1], {"n": 4}).json()
    assert r["ok"] and "results" not in r["questions"][0] and r["questions"][0]["answered"]
    assert answer(c, token, dev, qs[1], {"n": 9}).status_code == 400                    # außerhalb der Skala
    admin.post(f"/votes/live/{pid}/fragen/{qs[1]}/release", data={"csrf": csrf_of(edit.text)})
    st = c.get(f"/l/{token}/state.json").json()
    assert st["questions"][0]["results"]["stats"]["avg"] == 4
    # Sperren
    admin.post(f"/votes/live/{pid}/fragen/{qs[1]}/lock", data={"csrf": csrf_of(edit.text)})
    assert answer(c2, token, dev2, qs[1], {"n": 2}).status_code == 409


def test_free_pacing_multi_slider_and_presenter():
    admin = login(*ADMIN)
    pid, token = make(admin, pacing="free")
    edit = admin.get(f"/votes/live/{pid}")
    admin.post(f"/votes/live/{pid}/status", data={"csrf": csrf_of(edit.text), "action": "open"})
    c, dev = join(token)
    st = c.get(f"/l/{token}/state.json").json()
    assert len(st["questions"]) == 4                                                   # frei: alle Fragen
    multi, slider = st["questions"][3]["id"], st["questions"][2]["id"]
    assert answer(c, token, dev, multi, {"o": ["o1", "o2", "o3"]}).status_code == 400   # höchstens 2
    assert answer(c, token, dev, multi, {"o": ["o1", "o3"]}).json()["ok"]
    assert answer(c, token, dev, slider, {"n": 120}).json()["ok"]
    with SessionLocal() as db:
        poll = db.get(LivePoll, pid)
        res = lv.tally(db, poll.questions[2])
        assert res["stats"]["avg"] == 120 and res["stats"]["unit"] == "T€"
        assert [r["count"] for r in lv.tally(db, poll.questions[3])["rows"]] == [1, 0, 1, 0]
    present = admin.get(f"/votes/live/{pid}/praesentation")
    assert present.status_code == 200 and "lp-result" in present.text and "/l/" in present.text
    assert admin.get(f"/votes/live/{pid}/qr.svg").headers["content-type"].startswith("image/svg")
    staff = admin.get(f"/votes/live/{pid}/state.json").json()
    assert staff["participants"] == 1 and "results" in staff["questions"][1]          # Beamer sieht alles
    r = admin.post(f"/votes/live/{pid}/fragen/{multi}/chart", data={"csrf": csrf_of(edit.text), "chart": "donut"},
                   headers={"Accept": "application/json"})
    assert r.json()["questions"][3]["chart"] == "donut"
    # Übersicht und Löschen
    assert "Live-Umfragen" in admin.get("/votes").text
    # fremde Personen sehen die Umfrage nicht
    assert client().get(f"/votes/live/{pid}", follow_redirects=False).status_code in (303, 404)
    admin.post(f"/votes/live/{pid}/loeschen", data={"csrf": csrf_of(edit.text)})
    with SessionLocal() as db:
        assert db.get(LivePoll, pid) is None
