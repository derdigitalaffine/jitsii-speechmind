import io
import json
import re
from importlib.metadata import version

from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from app import applications as apps, forms as fm
from app.db import Form, FormResponse, User


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in re.findall(r"\d+", value)[:3]]
    return tuple((parts + [0, 0, 0])[:3])


def _pdf_bytes(*, password: str | None = None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _application_with_pdf(db, blob: bytes, name: str = "anlage.pdf"):
    admin = db.scalar(select(User).where(User.email == "admin@example.org"))
    schema = fm.clean_schema([{"id": "upload", "type": "file", "title": "Unterlage"}])
    form = Form(owner_id=admin.id, title="PDF-Sicherheitstest", kind="application", pdf_uploads=True,
                schema_json=json.dumps(schema))
    db.add(form)
    db.flush()
    resp = FormResponse(form_id=form.id, name="Test", email="test@example.org", ref_no=f"PDFSEC-{form.id}",
                        status="received", answers_json=json.dumps({"upload": [{"file": name, "name": name,
                                                                                "type": "application/pdf"}]}))
    db.add(resp)
    db.flush()
    target = fm.files_dir(form.id, resp.id)
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(blob)
    db.refresh(resp)
    return form, resp


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def test_pypdf_security_floor():
    """Untrusted uploads are parsed by pypdf; never regress below the fixed security release."""
    assert _version_tuple(version("pypdf")) >= (6, 21, 2)


def test_application_pdf_embeds_normal_pdf(db):
    form, resp = _application_with_pdf(db, _pdf_bytes())
    out = apps.pdf(form, resp)
    assert out.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(out)).pages) >= 2


def test_application_pdf_skips_password_protected_pdf(db):
    form, resp = _application_with_pdf(db, _pdf_bytes(password="secret"))
    out = apps.pdf(form, resp)
    assert "verschlüsselt" in _text(out).lower()


def test_application_pdf_skips_malformed_pdf(db):
    form, resp = _application_with_pdf(db, b"%PDF-1.7\nnot-a-valid-xref\n%%EOF\n")
    out = apps.pdf(form, resp)
    assert "nicht lesbar" in _text(out).lower()
