"""Formulare und Online-Anträge als Datei ex- und importieren."""

import io
import secrets
import json
import zipfile

from sqlalchemy import select

from app import applications as apps, forms as fm
from app.db import (
    ApplicationEvent, Form, FormBlock, FormResponse, Group, Process, SessionLocal, User,
)

from app.security import hash_password

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def _setup() -> int:
    settings(module_applications="1")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN[0]))
        group = db.scalar(select(Group).where(Group.name == "Ordnungsamt Export")) or Group(name="Ordnungsamt Export")
        block = db.scalar(select(FormBlock).where(FormBlock.name == "Hund (Export)"))
        if block is None:
            block = FormBlock(name="Hund (Export)", schema_json=json.dumps([
                {"id": "rasse", "type": "short", "title": "Rasse", "subtype": "text"}]))
        process = Process(name="Hundesteuer-Prozess", owner_id=admin.id, draft_json=json.dumps({"steps": [
            {"id": "s1", "type": "task", "title": "Prüfen", "assign": {"mode": "user", "user_id": admin.id}}]}))
        db.add_all([group, block, process])
        db.flush()
        items = [{"id": "name", "type": "short", "title": "Name", "subtype": "text", "required": True},
                 {"id": "anzahl", "type": "short", "title": "Anzahl Hunde", "subtype": "number"},
                 {"id": "nachweis", "type": "file", "title": "Nachweis"},
                 {"id": "hund", "type": "block", "block_id": block.id,
                  "show_if": {"mode": "all", "rules": [{"q": "anzahl", "op": "filled", "value": ""}]}}]
        form = Form(owner_id=admin.id, title="Hund anmelden", kind="application", app_prefix="HUND",
                    schema_json=json.dumps(fm.clean_schema(items)), app_group_id=group.id, app_mailbox="ordnung@example.org",
                    public_token="tok-export-" + secrets.token_hex(4), process_id=process.id, app_seq_year=2026, app_seq=7,
                    app_routing_json=json.dumps([{"question": "name", "value": "x", "group_id": group.id}]),
                    fee_json=json.dumps({"enabled": True, "label": "Hundesteuer", "base": 1500, "methods": "transfer",
                                         "rules": [{"q": "anzahl", "op": "each", "value": "", "cents": 500, "label": "je Hund"}]}))
        db.add(form)
        db.flush()
        resp = FormResponse(form_id=form.id, name="Erika", email="erika@example.org", ref_no="HUND-2026-00007",
                            status="in_progress", answers_json="{}")
        db.add(resp)
        db.flush()
        folder = fm.files_dir(form.id, resp.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "abc123.pdf").write_bytes(b"%PDF-1.4 nachweis")
        resp.answers_json = json.dumps({"name": "Erika", "anzahl": "2", "hund_rasse": "Dackel",
                                        "nachweis": [{"file": "abc123.pdf", "name": "nachweis.pdf", "size": 17, "type": "application/pdf"}]})
        resp.checksum = apps.checksum(resp)
        resp.events.append(ApplicationEvent(kind="created", text="Eingang"))
        db.commit()
        return form.id


def _import(c, content: bytes, name: str):
    token = csrf_of(c.get("/forms").text)
    return c.post("/forms/import", data={"csrf": token}, files={"file": (name, content)})


def test_export_structure_only_and_import_reuses_block():
    form_id = _setup()
    c = login(*ADMIN)
    r = c.get(f"/forms/{form_id}/transfer?blocks=1&process=1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    data = json.loads(r.content)
    assert data["format"] == "jitsii-formular-1" and data["process"]["name"] == "Hundesteuer-Prozess"
    assert "responses" not in data and data["blocks"][0]["name"] == "Hund (Export)"
    assert "ordnung@example.org" not in r.text and "tok-export-" not in r.text

    with SessionLocal() as db:
        blocks_before = db.query(FormBlock).count()
        processes_before = db.query(Process).count()
    r = _import(c, r.content, "hund.json")
    assert r.status_code == 303
    new_id = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        form = db.get(Form, new_id)
        assert db.query(FormBlock).count() == blocks_before   # gleichnamiger Block wiederverwendet
        assert db.query(Process).count() == processes_before + 1
        assert form.kind == "application" and form.active is False and form.public_token is None
        assert form.app_group_id is None and form.app_mailbox == "" and form.app_routing_json == "[]"
        assert form.dms_area_id is None and form.process.name == "Hundesteuer-Prozess"
        step = json.loads(form.process.draft_json)["steps"][0]
        assert step["assign"]["user_id"] is None
        fee = json.loads(form.fee_json)
        assert fee["base"] == 1500 and fee["rules"][0]["cents"] == 500 and fee["methods"] == "transfer"
        block_item = next(i for i in fm.raw_schema(form) if i["type"] == "block")
        assert db.get(FormBlock, block_item["block_id"]).name == "Hund (Export)"
        assert block_item["show_if"]["rules"][0]["q"] == "anzahl"
        assert not form.responses


def test_import_creates_missing_block_and_drops_unknown():
    form_id = _setup()
    c = login(*ADMIN)
    with_blocks = json.loads(c.get(f"/forms/{form_id}/transfer?blocks=1").content)
    without = json.loads(c.get(f"/forms/{form_id}/transfer").content)
    assert "process" not in without and "blocks" not in without
    with SessionLocal() as db:   # Zielserver ohne diesen Block simulieren
        for b in db.scalars(select(FormBlock).where(FormBlock.name == "Hund (Export)")):
            b.name = "Hund (umbenannt)"
        db.commit()
    r = _import(c, json.dumps(without).encode(), "ohne.json")
    with SessionLocal() as db:
        form = db.get(Form, int(r.headers["location"].rsplit("/", 1)[1]))
        assert not any(i["type"] == "block" for i in fm.raw_schema(form))
    r = _import(c, json.dumps(with_blocks).encode(), "mit.json")
    with SessionLocal() as db:
        form = db.get(Form, int(r.headers["location"].rsplit("/", 1)[1]))
        block_item = next(i for i in fm.raw_schema(form) if i["type"] == "block")
        assert db.get(FormBlock, block_item["block_id"]).name == "Hund (Export)"


def test_export_with_responses_zip_roundtrip():
    form_id = _setup()
    c = login(*ADMIN)
    r = c.get(f"/forms/{form_id}/transfer?responses=1")
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "formular.json" in zf.namelist() and any(n.endswith("abc123.pdf") for n in zf.namelist())
    r = _import(c, r.content, "hund.zip")
    assert r.status_code == 303
    with SessionLocal() as db:
        form = db.get(Form, int(r.headers["location"].rsplit("/", 1)[1]))
        assert form.app_seq_year == 2026 and form.app_seq == 7 and apps.next_ref(form) == "HUND-2026-00008"
        resp = form.responses[0]
        assert resp.ref_no == "HUND-2026-00007" and resp.status == "in_progress"
        assert resp.answers["hund_rasse"] == "Dackel" and resp.assignee_id is None and resp.track_token is None
        entry = resp.answers["nachweis"][0]
        assert entry["file"] != "abc123.pdf"
        assert (fm.files_dir(form.id, resp.id) / entry["file"]).read_bytes() == b"%PDF-1.4 nachweis"
        assert resp.checksum == apps.checksum(resp)
        kinds = [e.kind for e in resp.events]
        assert "created" in kinds and any("Aus Exportdatei importiert" in e.text for e in resp.events)


def test_import_rejects_garbage_and_needs_permission():
    _setup()
    c = login(*ADMIN)
    for content, name in ((b"kein json", "x.json"), (json.dumps({"format": "jitsii-prozess-1"}).encode(), "p.json"),
                          (b"PK\x03\x04kaputt", "x.zip")):
        r = _import(c, content, name)
        assert r.status_code == 303 and r.headers["location"] == "/forms"
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "ohne-formulare@example.org")) is None:
            db.add(User(email="ohne-formulare@example.org", name="Ohne", password_hash=hash_password("passwort-123"),
                        permissions=""))
            db.commit()
    other = login("ohne-formulare@example.org", "passwort-123")
    token = csrf_of(other.get("/").text)
    assert other.post("/forms/import", data={"csrf": token}, files={"file": ("x.json", b"{}")}).status_code == 403


def test_process_export_import_still_works():
    _setup()
    c = login(*ADMIN)
    with SessionLocal() as db:
        pid = db.scalar(select(Process.id).where(Process.name == "Hundesteuer-Prozess"))
    r = c.get(f"/processes/{pid}/export.json")
    assert r.status_code == 200 and json.loads(r.content)["format"] == "jitsii-prozess-1"
    token = csrf_of(c.get("/processes").text)
    r = c.post("/processes/import", data={"csrf": token}, files={"file": ("p.json", r.content)})
    assert r.status_code == 303 and r.headers["location"].startswith("/processes/")
    with SessionLocal() as db:
        process = db.get(Process, int(r.headers["location"].rsplit("/", 1)[1]))
        assert json.loads(process.draft_json)["steps"][0]["assign"]["user_id"] is None
