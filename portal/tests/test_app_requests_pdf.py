"""Nachforderungen im Antragsprozess: Nachgereichtes steht im Antrags-PDF und liegt als eigenes PDF in der Ablage."""

import asyncio
import io
import json
import secrets

from pypdf import PdfReader
from sqlalchemy import select

from app import applications as apps, forms as fm, workflow
from app.db import DmsRecord, Form, FormResponse, SessionLocal, User

from conftest import settings


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


class _Data(dict):
    def getlist(self, key):
        v = self.get(key)
        return [] if v is None else (v if isinstance(v, list) else [v])


def test_answered_request_in_pdf_and_dms():
    settings(module_forms="1", module_applications="1", module_dms="1")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.org"))
        items = [{"id": "name", "type": "short", "title": "Name", "subtype": "text"},
                 {"id": "strasse", "type": "short", "title": "Straße", "subtype": "text"}]
        form = Form(owner_id=admin.id, title="Sondernutzung", kind="application", app_prefix="SN",
                    schema_json=json.dumps(fm.clean_schema(items)), public_token="tok-" + secrets.token_hex(4))
        db.add(form)
        db.flush()
        resp = FormResponse(form_id=form.id, name="Erika", email="erika@example.org", ref_no="SN-2026-00001",
                            status="in_progress", answers_json=json.dumps({"name": "Erika", "strasse": "Hauptstr 1"}))
        db.add(resp)
        db.flush()
        req = workflow.create_request(db, resp, "Lageplan und Fläche", "Bitte Fläche angeben und Straße prüfen.",
                                      [{"id": "flaeche", "type": "short", "title": "Fläche in m²", "subtype": "number"}],
                                      ["strasse"], None, "Sachbearbeitung")
        db.flush()
        qid = req.items[0]["id"]
        errors = asyncio.run(workflow.answer_request(db, resp, req, _Data({"q_" + qid: "12", "q_strasse": "Hauptstraße 1"}), {}))
        assert errors == {}
        db.commit()
        text = _text(apps.pdf(form, resp))
        assert "Nachgereichte Angaben" in text and "Lageplan und Fläche" in text
        assert "Fläche in m²" in text and "12" in text
        assert "Hauptstraße 1" in text and "bisher: Hauptstr 1" in text and "später korrigiert" in text
        record = db.scalar(select(DmsRecord).where(DmsRecord.response_id == resp.id))
        files = [f for f in record.files if f.kind == "nachreichung"]
        assert len(files) == 1 and files[0].name.startswith("SN-2026-00001 Nachreichung")
        from app import dms
        stored = _text((dms.files_dir(record.id) / files[0].file).read_bytes())
        assert "Fläche in m²" in stored and "Hauptstraße 1" in stored
