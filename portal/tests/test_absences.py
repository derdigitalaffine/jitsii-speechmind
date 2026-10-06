"""Abwesenheiten & Vertretungen: eigene planen, Zustimmung der Vertretung (Profil), Eintragen durch Berechtigte und
Gruppenleitungen, Aufgaben und Anträge für die Vertretung, Benachrichtigungen in Kopie, Anzeige ohne Grund."""

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app import absence as ab, notify, workflow
from app.db import (
    Absence, ApplicationTask, Form, FormResponse, Group, Notification, SessionLocal, User,
)
from app.security import hash_password

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")
PW = "abwesend-passwort-1"


def person(email: str, name: str, **kw) -> int:
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, name=name, password_hash=hash_password(PW), permissions="video,forms")
            db.add(u)
        u.must_change_password, u.active, u.password_set = False, True, True
        for k, v in kw.items():
            setattr(u, k, v)
        db.commit()
        return u.id


def day(offset: int = 0) -> str:
    return (date.fromisoformat(ab.today()) + timedelta(days=offset)).isoformat()


@pytest.fixture(autouse=True)
def clean():
    settings(module_forms="1", module_applications="1", smtp_host="smtp.example.org", mail_from="portal@example.org")
    with SessionLocal() as db:
        db.execute(delete(Absence))
        db.execute(delete(Notification))
        db.commit()
    yield
    settings(smtp_host="", mail_from="")


def test_own_absence_with_confirmation_flow():
    anna = person("anna@example.org", "Anna Abwesend")
    ben = person("ben@example.org", "Ben Vertretung", sub_confirm=True)
    c = login("anna@example.org", PW)
    page = c.get("/abwesenheiten")
    assert page.status_code == 200 and "Eigene Abwesenheit eintragen" in page.text and "Für andere eintragen" not in page.text
    r = c.post("/abwesenheiten", data={"csrf": csrf_of(page.text), "starts_on": day(0), "ends_on": day(4),
                                       "substitute_id": str(ben), "note": "Akten im Schrank"})
    assert r.status_code == 303
    with SessionLocal() as db:
        a = db.scalar(select(Absence).where(Absence.user_id == anna))
        assert a.status == "pending" and ab.current(db, anna) is None          # wirkt erst nach Zustimmung
        mail = db.scalar(select(Notification).where(Notification.kind == "absence_request"))
        assert mail.to_addr == "ben@example.org" and "Anna Abwesend" in mail.subject
    # Überschneidung wird abgelehnt
    r = c.post("/abwesenheiten", data={"csrf": csrf_of(page.text), "starts_on": day(2), "ends_on": day(6)}, follow_redirects=True)
    assert "bereits eine Abwesenheit" in r.text
    b = login("ben@example.org", PW)
    page = b.get("/abwesenheiten")
    assert "Bitte um Ihre Zustimmung" in page.text and "Akten im Schrank" in page.text
    assert "Bitten um Vertretung" in b.get("/").text                          # Handlungsbedarf auf der Übersicht
    b.post(f"/abwesenheiten/{a.id}/antwort", data={"csrf": csrf_of(page.text), "accept": "1"})
    with SessionLocal() as db:
        a = db.get(Absence, a.id)
        assert a.status == "confirmed" and ab.represented(db, db.get(User, ben)) == [anna]
        assert db.scalar(select(Notification).where(Notification.kind == "absence_answer")).to_addr == "anna@example.org"
    # Anzeige ohne Grund in der Benutzerverwaltung
    html = login(*ADMIN).get("/admin/users").text
    assert f"abwesend bis {ab.fmt(day(4))}, Vertretung: Ben Vertretung" in html


def test_tasks_and_mail_copies_for_substitute():
    anna = person("anna@example.org", "Anna Abwesend")
    ben = person("ben@example.org", "Ben Vertretung", sub_confirm=False)
    with SessionLocal() as db:
        db.execute(delete(Form).where(Form.title == "Vertretungsantrag"))
        form = Form(title="Vertretungsantrag", kind="application", owner_id=anna)
        db.add(form)
        db.flush()
        resp = FormResponse(form_id=form.id, ref_no="VT-1", status="received", assignee_id=anna)
        db.add(resp)
        db.flush()
        db.add(ApplicationTask(response_id=resp.id, step_id="s1", name="Prüfen", kind="task", assignee_id=anna))
        a = ab.create(db, db.get(User, anna), db.get(User, anna), day(0), day(2), db.get(User, ben))
        db.commit()
        assert a.status == "confirmed"                                       # ohne Zustimmungspflicht sofort
        benu = db.get(User, ben)
        tasks = workflow.my_tasks(db, benu)
        assert [t.name for t in tasks] == ["Prüfen"]
        from app import applications as apps
        assert apps.access(db, benu, db.get(FormResponse, resp.id)) == 2
        notify.enqueue(db, "anna@example.org", "Neue Aufgabe", "Text", "app_task")
        notify.enqueue(db, "anna@example.org", "Ihr Code", "123456", "login_code")   # Sicherheitsmails nie kopieren
        db.commit()
        copies = db.scalars(select(Notification).where(Notification.to_addr == "ben@example.org",
                                                       Notification.kind.like("%_vt"))).all()
        assert len(copies) == 1 and copies[0].subject == "[Vertretung für Anna Abwesend] Neue Aufgabe"
    page = login("ben@example.org", PW).get("/tasks")
    assert "Als Vertretung" in page.text and "für Anna Abwesend" in page.text
    # nach dem Ende keine Übernahme mehr
    with SessionLocal() as db:
        a = db.scalar(select(Absence).where(Absence.user_id == anna))
        a.starts_on, a.ends_on = day(-5), day(-1)
        db.commit()
        assert workflow.my_tasks(db, db.get(User, ben)) == []


def test_who_may_enter_for_others():
    lead = person("lead@example.org", "Lea Leitung")
    anna = person("anna@example.org", "Anna Abwesend")
    other = person("otto@example.org", "Otto Andere")
    hr = person("hr@example.org", "Hanna Personal", permissions="video,absences")
    with SessionLocal() as db:
        db.execute(delete(Group).where(Group.name == "Bürgerbüro-Test"))
        g = Group(name="Bürgerbüro-Test", lead_id=lead)
        g.members = [db.get(User, anna), db.get(User, lead)]
        db.add(g)
        db.commit()
        assert {u.id for u in ab.manageable(db, db.get(User, lead))} == {anna}
        assert other in {u.id for u in ab.manageable(db, db.get(User, hr))}
    c = login("lead@example.org", PW)
    page = c.get("/abwesenheiten")
    assert "Für andere eintragen" in page.text and "Bürgerbüro-Test" in page.text
    ok = c.post("/abwesenheiten", data={"csrf": csrf_of(page.text), "user_id": str(anna), "starts_on": day(0),
                                       "ends_on": day(1), "substitute_id": str(lead)})
    assert ok.status_code == 303
    denied = c.post("/abwesenheiten", data={"csrf": csrf_of(page.text), "user_id": str(other), "starts_on": day(0),
                                           "ends_on": day(1)})
    assert denied.status_code == 403
    # ohne Recht kein Bereich „für andere“; fremde Abwesenheit nicht löschbar
    o = login("otto@example.org", PW)
    page = o.get("/abwesenheiten")
    assert "Für andere eintragen" not in page.text
    with SessionLocal() as db:
        aid = db.scalar(select(Absence.id).where(Absence.user_id == anna))
    assert o.post(f"/abwesenheiten/{aid}/loeschen", data={"csrf": csrf_of(page.text)}).status_code == 403
    # Gruppenleitung in der Benutzerverwaltung setzen
    admin = login(*ADMIN)
    with SessionLocal() as db:
        gid = db.scalar(select(Group.id).where(Group.name == "Bürgerbüro-Test"))
    page = admin.get("/admin/users")
    admin.post(f"/admin/groups/{gid}", data={"csrf": csrf_of(page.text), "name": "Bürgerbüro-Test", "lead_id": str(hr),
                                             "members": [str(anna)]})
    with SessionLocal() as db:
        assert db.get(Group, gid).lead_id == hr


def test_profile_setting_and_dashboard_tile():
    person("ben@example.org", "Ben Vertretung", sub_confirm=False)
    b = login("ben@example.org", PW)
    page = b.get("/profile")
    assert 'name="sub_confirm"' in page.text
    b.post("/profile", data={"csrf": csrf_of(page.text), "name": "Ben Vertretung", "sub_confirm": "1"})
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "ben@example.org")).sub_confirm
    assert 'data-key="absence"' in b.get("/").text


def test_deputy_access_bookings_resources_dms_and_citizen_note():
    from datetime import timedelta as td

    from app import bookings as bk, dms, resources as rs, shares as sh
    from app.db import BookingPage, BookingWindow, DmsAccess, DmsArea, Poll, PollShare, Resource, utcnow
    anna = person("anna@example.org", "Anna Abwesend")
    ben = person("ben@example.org", "Ben Vertretung", sub_confirm=False)
    with SessionLocal() as db:
        for model, col, val in ((BookingPage, BookingPage.title, "Sprechstunde Anna"), (Poll, Poll.title, "Umfrage Anna"),
                                (Resource, Resource.slug, "raum-anna"), (DmsArea, DmsArea.name, "Akten Anna")):
            db.execute(delete(model).where(col == val))
        page = BookingPage(title="Sprechstunde Anna", owner_id=anna, public_token="anna-sprechstunde-token-1",
                           min_notice_hours=0)
        db.add(page)
        poll = Poll(title="Umfrage Anna")
        db.add(poll)
        res = Resource(name="Raum Anna", slug="raum-anna", manager_user_id=anna)
        db.add(res)
        area = DmsArea(name="Akten Anna")
        db.add(area)
        db.flush()
        db.add(PollShare(poll_id=poll.id, user_id=anna, level=sh.EDIT))
        db.add(DmsAccess(area_id=area.id, user_id=anna, level=dms.WRITE))
        start = (utcnow() + td(days=1)).replace(minute=0, second=0, microsecond=0)
        db.add(BookingWindow(page_id=page.id, starts_at=start, ends_at=start + td(hours=1)))
        benu = db.get(User, ben)
        before = (sh.access_level(db, "booking", page, benu), rs.level(db, benu, res), dms.levels(db, benu).get(area.id, 0))
        assert before == (0, 0, 0)
        ab.create(db, db.get(User, anna), db.get(User, anna), day(0), day(3), benu,
                  auto_reply="Ich bin im Urlaub. Bitte wenden Sie sich an Ben.")
        db.commit()
        assert sh.access_level(db, "booking", page, benu) == sh.EDIT
        assert any(p.id == page.id for p, _ in sh.shared_with(db, "booking", benu))
        assert sh.access_level(db, "poll", poll, benu) == sh.VIEW              # Umfragen nur lesend
        assert rs.level(db, benu, res) == 3
        assert dms.levels(db, benu)[area.id] == dms.READ                    # Ablage nur lesend
        # Bürger-Mail: Hinweis oben, Antwort an die Vertretung
        b, err = bk.book(db, db.get(BookingPage, page.id), start, "Bürgerin", "buergerin@example.org")
        db.commit()
        assert not err
        mail = db.scalar(select(Notification).where(Notification.to_addr == "buergerin@example.org"))
        assert mail.body.startswith("Ich bin im Urlaub.") and mail.reply_to == "ben@example.org"
        owner_copy = db.scalar(select(Notification).where(Notification.to_addr == "ben@example.org",
                                                          Notification.kind == "booking_owner_vt"))
        assert owner_copy is not None
