"""Krankmelder-Modul: Meldewege, Zugang, Verschlüsselung, Zuständigkeit, Status, Löschfrist, Mails, Import."""

import io
import json
import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import krank, notify
from app.db import (
    Group, KrankAccess, KrankEmployer, KrankReport, KrankResponsible, Notification, SessionLocal, User, utcnow,
)
from app.security import hash_password

from conftest import client, csrf_of, login, settings

def _pdf() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(200, 200))
    c.drawString(20, 100, "AU-Bescheinigung")
    c.showPage()
    c.save()
    return buf.getvalue()


PDF = _pdf()
MONDAY = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def module_on(monkeypatch):
    settings(module_krank="1", krank_public="1", smtp_host="smtp.example.org", mail_from="portal@example.org",
             krank_global_email="personal@example.org", krank_retention_days="0", krank_kinds="simple,au,eau,child")
    monkeypatch.setattr(krank, "today", lambda: MONDAY)
    with SessionLocal() as db:
        krank.set_password(db, "geheim123")
        db.commit()
    yield


def employer(name="Verbandsgemeinde", **kw) -> int:
    with SessionLocal() as db:
        emp = db.scalar(select(KrankEmployer).where(KrankEmployer.name == name))
        if emp is None:
            emp = KrankEmployer(name=name, **kw)
            db.add(emp)
        else:
            for k, v in kw.items():
                setattr(emp, k, v)
        db.commit()
        return emp.id


def public_client():
    c = client()
    r = c.post("/krank/login", data={"password": "geheim123"})
    assert r.status_code == 303 and r.headers["location"] == "/krank"
    return c


def submit(c, kind, files=None, **data):
    r = c.post(f"/krank/{kind}", data=data, files=files or {})
    return r


def last_report() -> KrankReport:
    from sqlalchemy.orm import selectinload
    with SessionLocal() as db:
        return db.scalar(select(KrankReport).options(selectinload(KrankReport.files), selectinload(KrankReport.events))
                         .order_by(KrankReport.id.desc()))


def test_module_switch_blocks_everything():
    settings(module_krank="0")
    c = client()
    assert c.get("/krank").status_code == 404
    assert c.get("/krank-embed").status_code == 404
    assert c.get("/krankmelder").status_code == 404


def test_gate_password_and_token():
    c = client()
    page = c.get("/krank").text
    assert 'name="password"' in page
    assert c.post("/krank/login", data={"password": "falsch"}).headers["location"] == "/krank"
    assert 'name="password"' in c.get("/krank").text
    c = public_client()
    assert "/krank/eau" in c.get("/krank").text
    with SessionLocal() as db:
        token = krank.new_access_token(db)
        db.commit()
    c2 = client()
    assert c2.get("/krank/z/falsch").status_code == 404
    assert c2.get(f"/krank/z/{token}").status_code == 303
    assert "/krank/simple" in c2.get("/krank").text
    settings(krank_public="0")
    assert 'name="password"' not in client().get("/krank").text


def test_simple_report_encrypted_and_mailed():
    emp = employer()
    c = public_client()
    r = submit(c, "simple", first_name="Erika", last_name="Musterfrau", employer=str(emp), email="erika@example.org")
    assert r.status_code == 303 and r.headers["location"].startswith("/krank/fertig?")
    done = c.get(r.headers["location"])
    assert "KM-2026-" in done.text and "Statusseite" in done.text
    rep = last_report()
    assert rep.kind == "simple" and rep.status == "new"
    assert "Musterfrau" not in rep.data_enc            # verschlüsselt gespeichert
    assert krank.data(rep)["date"] == MONDAY.isoformat()
    with SessionLocal() as db:
        mails = db.scalars(select(Notification).where(Notification.kind == "krank").order_by(Notification.id.desc()).limit(2)).all()
    to = {m.to_addr for m in mails}
    assert to == {"personal@example.org", "erika@example.org"}
    staff = next(m for m in mails if m.to_addr == "personal@example.org")
    assert "Musterfrau" not in staff.body and "Musterfrau" not in staff.subject   # nur Hinweis mit Link
    assert "/krankmelder/" in staff.body


def test_simple_not_on_weekend(monkeypatch):
    monkeypatch.setattr(krank, "today", lambda: date(2026, 10, 10))
    emp = employer()
    c = public_client()
    r = submit(c, "simple", first_name="A", last_name="B", employer=str(emp))
    assert r.headers["location"] == "/krank/simple"
    assert "montags bis freitags" in c.get("/krank/simple").text


def test_eau_rules_and_private():
    emp = employer()
    c = public_client()
    r = submit(c, "eau", first_name="Max", last_name="Muster", employer=str(emp), insured="private",
               **{"from": "2026-10-05", "to": "2026-10-09", "doctor": "2026-10-05", "first": "1"})
    assert r.headers["location"] == "/krank/eau"
    assert "Meldung mit AU" in c.get("/krank/eau").text
    r = submit(c, "eau", first_name="Max", last_name="Muster", employer=str(emp), insured="gkv",
               **{"from": "2026-10-09", "to": "2026-10-05", "doctor": "2026-10-05", "first": "1"})
    assert r.headers["location"] == "/krank/eau"
    r = submit(c, "eau", first_name="Max", last_name="Muster", employer=str(emp), insured="gkv", personnel_no="4711",
               **{"from": "2026-09-28", "to": "2026-10-09", "doctor": "2026-10-05", "first": "1"})
    assert r.status_code == 303 and "fertig" in r.headers["location"]
    rep = last_report()
    d = krank.data(rep)
    assert rep.status == "eau_open" and d["personnel_no"] == "4711" and d["days"] == 12
    assert any("Rückdatierung" in w for w in d["warnings"])
    # Folgebescheinigung mit anderem AU-Beginn → Hinweis
    submit(c, "eau", first_name="Max", last_name="Muster", employer=str(emp), insured="gkv",
           **{"from": "2026-10-01", "to": "2026-10-16", "doctor": "2026-10-05", "first": "0"})
    assert any("erste Tag der AU" in w for w in krank.data(last_report())["warnings"])


def test_au_upload_encrypted_and_proof_flow():
    emp = employer()
    c = public_client()
    r = submit(c, "au", first_name="Jo", last_name="Beispiel", employer=str(emp), email="jo@example.org",
               **{"from": "2026-10-05", "to": "2026-10-07", "first": "1"}, files={"file": ("au.pdf", PDF, "application/pdf")})
    assert "fertig" in r.headers["location"]
    rep = last_report()
    assert rep.status == "new" and len(rep.files) == 1
    stored = krank.files_dir(rep.id) / rep.files[0].file
    assert not stored.read_bytes().startswith(b"%PDF")      # auf dem Datenträger verschlüsselt
    assert krank.read_file(rep.files[0]) == PDF
    # Ohne Datei → „Nachweis fehlt“, Nachreichen über die Statusseite
    r = submit(c, "au", first_name="Jo", last_name="Beispiel", employer=str(emp), email="jo@example.org",
               **{"from": "2026-10-08", "to": "2026-10-09", "first": "1"})
    loc = r.headers["location"]
    rep = last_report()
    assert rep.status == "proof_missing"
    token = dict(p.split("=", 1) for p in loc.split("?", 1)[1].split("&"))["s"]
    page = c.get(f"/krank/s/{token}")
    assert page.status_code == 200 and "Nachweis fehlt" in page.text
    bad = c.post(f"/krank/s/{token}", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert bad.status_code == 303
    assert last_report().status == "proof_missing"
    c.post(f"/krank/s/{token}", files={"file": ("nachweis.pdf", PDF, "application/pdf")}, data={"text": "anbei"})
    rep = last_report()
    assert rep.status == "new" and len(rep.files) == 1 and rep.files[0].source == "nachgereicht"


def test_folge_derives_start_and_child_age_warning():
    emp = employer()
    c = public_client()
    base = {"first_name": "Kim", "last_name": "Kind", "employer": str(emp), "child_name": "Lea", "child_dob": "2012-01-01"}
    submit(c, "child", **base, **{"from": "2026-10-01", "to": "2026-10-02", "first": "1"})
    d = krank.data(last_report())
    assert any("12. Lebensjahr" in w for w in d["warnings"]) and last_report().status == "proof_missing"
    submit(c, "child", **base, **{"to": "2026-10-04", "first": "0"})
    d = krank.data(last_report())
    assert d["from"] == "2026-10-03" and d["days"] == 2


def test_inactive_employer_rejected():
    emp = employer("Zweckverband", active=False)
    c = public_client()
    r = submit(c, "simple", first_name="A", last_name="B", employer=str(emp))
    assert r.headers["location"] == "/krank/simple"


def test_embed_without_cookies():
    emp = employer()
    c = client()
    r = c.post("/krank-embed/login", data={"password": "geheim123"})
    loc = r.headers["location"]
    assert loc.startswith("/krank-embed?k=")
    ticket = loc.split("k=", 1)[1]
    fresh = client()                                  # ohne Cookie wie im iframe
    page = fresh.get(f"/krank-embed/simple?k={ticket}")
    assert page.status_code == 200 and f'value="{ticket}"' in page.text
    r = fresh.post("/krank-embed/simple", data={"k": ticket, "first_name": "I", "last_name": "Frame", "employer": str(emp)})
    assert r.headers["location"].startswith("/krank-embed/fertig?")
    assert "frame-ancestors" in fresh.get(r.headers["location"]).headers["content-security-policy"]


def _staff_user(email, perms, employer_id=None, group=False) -> None:
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, name=email.split("@")[0], password_hash=hash_password("passwort-123"), permissions=perms)
            db.add(u)
            db.flush()
        if employer_id:
            if group:
                g = Group(name=f"Personal {email}")
                g.members.append(u)
                db.add(g)
                db.flush()
                db.add(KrankResponsible(employer_id=employer_id, group_id=g.id))
            else:
                db.add(KrankResponsible(employer_id=employer_id, user_id=u.id))
        db.commit()


def test_staff_scope_status_and_audit():
    a, b = employer("Werke A"), employer("Werke B")
    _staff_user("sachb@example.org", "krank", a, group=True)
    pc = public_client()
    submit(pc, "simple", first_name="Ann", last_name="A", employer=str(a))
    ra = last_report().id
    submit(pc, "simple", first_name="Ben", last_name="B", employer=str(b))
    rb = last_report().id
    c = login("sachb@example.org", "passwort-123")
    assert c.get(f"/krankmelder/{ra}").status_code == 200
    assert c.get(f"/krankmelder/{rb}").status_code == 404
    listing = c.get("/krankmelder/liste").text
    assert "Ann A" in listing and "Ben B" not in listing
    assert c.get("/krankmelder/verwaltung").status_code == 403
    token = csrf_of(c.get(f"/krankmelder/{ra}").text)
    c.post(f"/krankmelder/{ra}/status", data={"csrf": token, "status": "done"})
    with SessionLocal() as db:
        rep = db.get(KrankReport, ra)
        assert rep.status == "done" and rep.processed_by == "sachb"
        actions = {x.action for x in db.scalars(select(KrankAccess).where(KrankAccess.ref_no == rep.ref_no))}
    assert {"angesehen", "status"} <= actions
    csv_text = c.get("/krankmelder/export.csv").text
    assert "Ann" in csv_text and "Ben" not in csv_text
    # Ohne Zuständigkeit kein Zugriff, Admin sieht alles
    _staff_user("ohne@example.org", "krank")
    assert login("ohne@example.org", "passwort-123").get("/krankmelder").status_code == 403
    admin = login("admin@example.org", "admin-passwort-123")
    assert admin.get(f"/krankmelder/{rb}").status_code == 200
    assert admin.get("/krankmelder/verwaltung").status_code == 200
    assert admin.get("/krankmelder/statistik").status_code == 200
    assert admin.get("/krankmelder/protokoll").status_code == 200
    assert "Krankmeldungen" in admin.get("/").text


def test_retention_and_purge():
    emp = employer()
    settings(krank_retention_days="30")
    pc = public_client()
    submit(pc, "simple", first_name="Del", last_name="Me", employer=str(emp))
    rid = last_report().id
    admin = login("admin@example.org", "admin-passwort-123")
    token = csrf_of(admin.get(f"/krankmelder/{rid}").text)
    admin.post(f"/krankmelder/{rid}/status", data={"csrf": token, "status": "done"})
    with SessionLocal() as db:
        rep = db.get(KrankReport, rid)
        assert rep.delete_after is not None
        rep.delete_after = utcnow() - timedelta(minutes=1)
        db.commit()
    assert krank.purge_expired() >= 1
    with SessionLocal() as db:
        assert db.get(KrankReport, rid) is None
        assert db.scalar(select(KrankAccess).where(KrankAccess.action == "gelöscht", KrankAccess.detail == "Löschfrist abgelaufen"))


def test_queue_purges_health_data(monkeypatch):
    emp = employer("Mit Anhang", attach_files=True)
    pc = public_client()
    submit(pc, "au", first_name="Pia", last_name="Pdf", employer=str(emp), **{"from": "2026-10-05", "to": "2026-10-06", "first": "1"},
           files={"file": ("au.pdf", PDF, "application/pdf")})
    with SessionLocal() as db:
        staff = db.scalars(select(Notification).where(Notification.to_addr == "personal@example.org").order_by(Notification.id.desc())).first()
        assert "Pia Pdf" in staff.body and staff.attachments_json
    sent = []
    monkeypatch.setattr(notify, "deliver", lambda cfg, to, subject, body, attachments=None, reply_to=None: sent.append(attachments))
    notify.process_queue()
    assert sent and any(a and a[0]["filename"].endswith(".pdf") for a in sent)
    with SessionLocal() as db:
        n = db.get(Notification, staff.id)
        assert n.status == "sent" and "Pia" not in n.body and n.attachments_json is None


def test_pdf_with_attachment():
    emp = employer()
    pc = public_client()
    submit(pc, "au", first_name="Paul", last_name="Pdf", employer=str(emp), **{"from": "2026-10-05", "to": "2026-10-06", "first": "1"},
           files={"file": ("au.pdf", PDF, "application/pdf")})
    with SessionLocal() as db:
        rep = db.get(KrankReport, last_report().id)
        out = krank.pdf(rep)
    from pypdf import PdfReader
    assert out.startswith(b"%PDF") and len(PdfReader(io.BytesIO(out)).pages) == 2


def test_my_reports_opt_in():
    emp = employer()
    _staff_user("mitarbeiter@example.org", "video")
    c = login("mitarbeiter@example.org", "passwort-123")
    page = c.get("/krank/simple")
    assert 'value="mitarbeiter@example.org"' in page.text
    token = csrf_of(page.text)
    r = c.post("/krank/simple", data={"csrf": token, "first_name": "Mit", "last_name": "Arbeiter", "employer": str(emp)})
    done = c.get(r.headers["location"]).text
    assert "verschlüsselt gespeichert" in done and "Einschalten und diese Meldung übernehmen" in done
    rep = last_report()
    assert rep.user_id is None
    q = dict(p.split("=", 1) for p in r.headers["location"].split("?", 1)[1].split("&"))
    from urllib.parse import unquote
    c.post("/krank/meine/uebernehmen", data={"csrf": token, "r": q["r"], "d": unquote(q["d"])})
    mine = c.get("/krank/meine").text
    assert rep.ref_no in mine
    c.post("/krank/meine/einstellung", data={"csrf": token, "on": "0"})
    assert last_report().user_id is None


def test_proof_reminder():
    emp = employer()
    settings(krank_proof_reminder_days="3")
    pc = public_client()
    submit(pc, "au", first_name="Rita", last_name="Reminder", employer=str(emp), email="rita@example.org",
           **{"from": "2026-10-05", "to": "2026-10-06", "first": "1"})
    with SessionLocal() as db:
        rep = db.get(KrankReport, last_report().id)
        rep.created_at = utcnow() - timedelta(days=4)
        db.commit()
    assert krank.send_proof_reminders() >= 1
    assert krank.send_proof_reminders() == 0          # nur einmal
    with SessionLocal() as db:
        assert db.scalar(select(Notification).where(Notification.to_addr == "rita@example.org",
                                                    Notification.subject.like("Erinnerung%")))


def _old_krankmelder(tmp: Path) -> Path:
    dbp = tmp / "data" / "krankmeldungen.db"
    dbp.parent.mkdir(parents=True)
    con = sqlite3.connect(dbp)
    con.executescript("""
      CREATE TABLE submissions (id INTEGER PRIMARY KEY, type TEXT, status TEXT, processed_at DATETIME, processed_by TEXT,
        employee_name TEXT, employee_email TEXT, employee_id TEXT, submission_date DATETIME, sender_ip TEXT, user_agent TEXT,
        validation_result TEXT, error_message TEXT, data_json TEXT, created_at DATETIME, updated_at DATETIME);
      CREATE TABLE au_scans (id INTEGER PRIMARY KEY, submission_id INTEGER, file_name TEXT, file_path TEXT, file_size INTEGER, mime_type TEXT, created_at DATETIME);
      CREATE TABLE employers (id INTEGER PRIMARY KEY, name TEXT, active BOOLEAN, color TEXT, sort_order INTEGER);
      CREATE TABLE employer_settings (id INTEGER PRIMARY KEY, employer TEXT, sb_email TEXT, sb_emails TEXT, send_global_copy INTEGER, requires_remarks INTEGER, subject_prefix TEXT, global_email TEXT);
      CREATE TABLE global_settings (id INTEGER PRIMARY KEY, key TEXT, value TEXT);
      CREATE TABLE cms_content (id INTEGER PRIMARY KEY, slug TEXT, content TEXT);
      CREATE TABLE feedback (id INTEGER PRIMARY KEY, rating INTEGER, note TEXT, submission_id INTEGER, created_at DATETIME);
    """)
    con.execute("INSERT INTO employers VALUES (1, 'Altgemeinde', 1, '#ff0000', 1)")
    con.execute("INSERT INTO employer_settings (employer, sb_emails, send_global_copy, requires_remarks, subject_prefix) "
                "VALUES ('Altgemeinde', '[\"alt@example.org\"]', 0, 1, 'KM-Alt')")
    con.execute("INSERT INTO global_settings (key, value) VALUES ('SB_EMAIL', 'personal@example.org')")
    con.execute("INSERT INTO cms_content (slug, content) VALUES ('instructions', '# Alte Anleitung')")
    con.execute("INSERT INTO submissions (id, type, status, processed_at, processed_by, employee_name, data_json, created_at) VALUES "
                "(7, 'auscan', 'processed', '2026-01-03 10:00:00', 'Sachb', 'Alt Mann', ?, '2026-01-02 08:00:00')",
                (json.dumps({"employee_name": "Mann", "employee_vorname": "Alt", "employer": "Altgemeinde",
                             "from_date": "2026-01-02", "to_date": "2026-01-05", "is_first_cert": True}),))
    con.execute("INSERT INTO au_scans (submission_id, file_name, file_path, mime_type) VALUES (7, 'scan.pdf', '/app/uploads/abc.pdf', 'application/pdf')")
    con.execute("INSERT INTO feedback (rating, note, created_at) VALUES (5, 'super', '2026-01-02 09:00:00')")
    con.commit()
    con.close()
    (tmp / "uploads").mkdir()
    (tmp / "uploads" / "abc.pdf").write_bytes(PDF)
    archive = tmp / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(dbp, "data/krankmeldungen.db")
        zf.write(tmp / "uploads" / "abc.pdf", "uploads/abc.pdf")
    return archive


def test_import_from_standalone(tmp_path):
    archive = _old_krankmelder(tmp_path)
    with SessionLocal() as db:
        counts = krank.import_archive(db, archive, None)
        db.commit()
    assert counts["reports"] == 1 and counts["files"] == 1 and counts["employers"] >= 1
    with SessionLocal() as db:
        rep = db.scalar(select(KrankReport).where(KrankReport.import_key.like("krankmelder:7:%")))
        assert rep.kind == "au" and rep.status == "done" and rep.processed_by == "Sachb"
        assert krank.full_name(rep) == "Alt Mann" and krank.read_file(rep.files[0]) == PDF
        emp = db.scalar(select(KrankEmployer).where(KrankEmployer.name == "Altgemeinde"))
        assert emp.emails == "alt@example.org" and emp.allow_remarks and emp.subject_prefix == "KM-Alt"
    with SessionLocal() as db:
        again = krank.import_archive(db, archive, None)
        db.commit()
    assert again["reports"] == 0 and again["skipped"] == 1


def test_dms_filing_when_enabled():
    from app.db import DmsRecord
    emp = employer("Mit Ablage", dms_enabled=True)
    pc = public_client()
    submit(pc, "simple", first_name="Dora", last_name="Dms", employer=str(emp))
    rid = last_report().id
    with SessionLocal() as db:
        rep = db.get(KrankReport, rid)
        rec = db.get(DmsRecord, rep.dms_record_id)
        assert rec.kind == "krank" and rec.applicant == "Dora Dms" and rec.closed_at is None
    admin = login("admin@example.org", "admin-passwort-123")
    token = csrf_of(admin.get(f"/krankmelder/{rid}").text)
    admin.post(f"/krankmelder/{rid}/status", data={"csrf": token, "status": "done"})
    with SessionLocal() as db:
        rec = db.get(DmsRecord, db.get(KrankReport, rid).dms_record_id)
        assert rec.closed_at is not None and any(f.kind == "abschluss" for f in rec.files)


def test_admin_pages_render():
    emp = employer()
    admin = login("admin@example.org", "admin-passwort-123")
    token = csrf_of(admin.get("/krankmelder/verwaltung").text)
    r = admin.post("/krankmelder/verwaltung/zugang", data={"csrf": token, "action": "new_token"})
    assert r.status_code == 303
    page = admin.get("/krankmelder/verwaltung").text
    assert "/krank/z/" in page
    assert admin.get(f"/krankmelder/arbeitgeber/{emp}").status_code == 200
    assert admin.get("/krankmelder/qr.svg").headers["content-type"].startswith("image/svg")
    assert admin.get("/admin/modules").status_code == 200
    assert "Krankmelder" in admin.get("/admin/templates").text
    assert admin.get("/krank/anleitung").status_code == 200
    assert admin.get("/krankmelder/hilfe").status_code == 200


def test_all_pages_render():
    emp = employer()
    pc = public_client()
    for kind in ("simple", "au", "eau", "child"):
        assert pc.get(f"/krank/{kind}").status_code == 200
    r = submit(pc, "eau", first_name="Eva", last_name="Eau", employer=str(emp), insured="gkv",
               **{"from": "2026-10-05", "to": "2026-10-07", "doctor": "2026-10-05", "first": "1"})
    q = dict(p.split("=", 1) for p in r.headers["location"].split("?", 1)[1].split("&"))
    assert pc.get(f"/krank-embed/s/{q['s']}").status_code == 200
    assert pc.get(f"/krank/s/{q['s']}/pdf").content.startswith(b"%PDF")
    assert pc.get("/krank-embed/anleitung").status_code == 200
    admin = login("admin@example.org", "admin-passwort-123")
    assert "Eva Eau" in admin.get("/krankmelder").text
    rid = last_report().id
    token = csrf_of(admin.get(f"/krankmelder/{rid}").text)
    admin.post(f"/krankmelder/{rid}/status", data={"csrf": token, "status": "eau_failed"})
    admin.post(f"/krankmelder/{rid}/nachricht", data={"csrf": token, "text": "Bitte AU-Beginn prüfen"})
    admin.post(f"/krankmelder/{rid}/notiz", data={"csrf": token, "text": "intern: angerufen"})
    status_page = pc.get(f"/krank/s/{q['s']}").text
    assert "Bitte AU-Beginn prüfen" in status_page and "intern: angerufen" not in status_page
    assert "Abruf erfolglos" in status_page
    detail = admin.get(f"/krankmelder/{rid}").text
    assert "intern: angerufen" in detail
    assert admin.get(f"/krankmelder/{rid}/pdf").content.startswith(b"%PDF")
    r = admin.post(f"/krankmelder/{rid}/loeschen", data={"csrf": token, "reason": "Test"})
    assert r.status_code == 303
    assert pc.get(f"/krank/s/{q['s']}").status_code == 404
