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
