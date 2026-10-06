"""Rechtstexte: Fassungen, Vergleich, geplante Fassung, außer Kraft, Querverweise, Kurzschreibweise in Formularen,
Rechtsgrundlagen an Anträgen, Suche, Word/PDF-Import, Anlagen, Ex-/Import, Gliederungshinweise."""

import io
import json
import re
import zipfile
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app import laws as lx
from app.db import Form, LawLevel, LawText, LawVersion, SessionLocal

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")
HS = """# Hauptsatzung der Ortsgemeinde Musterdorf

## Erster Abschnitt – Allgemeines

### § 1 Name

(1) Die Ortsgemeinde führt den Namen Musterdorf.
(2) Es gilt § 2 GemO entsprechend; Näheres regelt § 2 Abs. 1. Siehe auch § 4 BauGB und § 2 der Friedhofssatzung.

### § 2 Bekanntmachungen

Öffentliche Bekanntmachungen erfolgen im Amtsblatt.
"""
GEMO = """# Gemeindeordnung

### § 1 Wesen der Gemeinde

Die Gemeinde ist Grundlage des demokratischen Staates.

### § 2 Aufgaben

Die Gemeinden erfüllen ihre Aufgaben.
"""


@pytest.fixture(autouse=True)
def module_on():
    settings(module_laws="1", module_forms="1", module_applications="1")
    lx.invalidate_refs()
    yield


def make_law(slug: str, md: str, short: str = "", **kw) -> int:
    with SessionLocal() as db:
        law = db.scalar(select(LawText).where(LawText.slug == slug))
        if law is not None:
            db.delete(law)
            db.commit()
        law = LawText(slug=slug, title=lx.parse(md).title or slug, short_title=short, body_md=md, published=True, **kw)
        db.add(law)
        db.flush()
        lx.store(db, law)
        db.commit()
        lx.invalidate_refs()
        return law.id


def editor():
    return login(*ADMIN)


def save(c, law_id: int, md: str, **fields):
    page = c.get(f"/laws/{law_id}/edit")
    with SessionLocal() as db:
        law = db.get(LawText, law_id)
        data = {"csrf": csrf_of(page.text), "title": law.title, "short_title": law.short_title, "slug": law.slug,
                "doc_type": law.doc_type, "valid_from": law.valid_from, "valid_until": law.valid_until,
                "published": "1", "body_md": md, **fields}
    return c.post(f"/laws/{law_id}/edit", data=data)


def test_new_version_public_compare_and_date():
    lid = make_law("hauptsatzung-fassung", HS, "HSF", valid_from="2020-01-01")
    c = editor()
    new = HS.replace("im Amtsblatt", "im Amtsblatt und im Internet").replace("### § 2 Bekanntmachungen", "### § 2 Bekanntmachungen\n") \
        + "\n### § 3 Inkrafttreten\n\nDiese Satzung tritt in Kraft.\n"
    r = save(c, lid, new, valid_from="2026-01-01", new_version="1", version_note="1. Änderung")
    assert r.status_code == 303
    with SessionLocal() as db:
        v = db.scalar(select(LawVersion).where(LawVersion.law_id == lid, LawVersion.public.is_(True)))
        assert v.valid_from == "2020-01-01" and v.valid_until == "2026-01-01"
        vid = v.id
    pub = client()
    old = pub.get(f"/recht/hauptsatzung-fassung/fassung/{vid}")
    assert old.status_code == 200 and "Frühere Fassung" in old.text and "und im Internet" not in old.text
    r = pub.get("/recht/hauptsatzung-fassung?am=2023-05-01")
    assert r.status_code == 303 and r.headers["location"].endswith(f"/fassung/{vid}")
    assert pub.get("/recht/hauptsatzung-fassung?am=2026-02-01").status_code == 200
    cmp = pub.get(f"/recht/hauptsatzung-fassung/vergleich?a={vid}")
    assert cmp.status_code == 200
    assert re.search(r"<ins>[^<]*Internet[^<]*</ins>", cmp.text) and "§ 3 Inkrafttreten" in cmp.text
    assert ">geändert<" in cmp.text and ">neu<" in cmp.text
    # Korrektur ohne „neue Fassung“: nur interne Sicherung, nicht öffentlich
    save(c, lid, new + "\n", valid_from="2026-01-01")
    with SessionLocal() as db:
        hidden = db.scalars(select(LawVersion).where(LawVersion.law_id == lid, LawVersion.public.is_(False))).all()
        assert hidden
        assert pub.get(f"/recht/hauptsatzung-fassung/fassung/{hidden[0].id}").status_code == 404


def test_planned_version_applied_on_date():
    lid = make_law("satzung-geplant", HS, "SG", valid_from="2021-01-01")
    c = editor()
    page = c.get(f"/laws/{lid}/plan")
    future = (date.today() + timedelta(days=30)).isoformat()
    r = c.post(f"/laws/{lid}/plan", data={"csrf": csrf_of(page.text), "valid_from": future, "version_note": "2. Änderung",
                                          "body_md": HS.replace("Musterdorf", "Neudorf")})
    assert r.status_code == 303
    assert lx.apply_planned() == 0
    with SessionLocal() as db:
        db.get(LawText, lid).planned_valid_from = date.today().isoformat()
        db.commit()
    assert lx.apply_planned() == 1
    with SessionLocal() as db:
        law = db.get(LawText, lid)
        assert "Neudorf" in law.body_md and law.planned_md == "" and law.valid_from == date.today().isoformat()
        assert law.version_note == "2. Änderung"
        v = db.scalar(select(LawVersion).where(LawVersion.law_id == lid, LawVersion.public.is_(True)))
        assert "Musterdorf" in v.body_md and v.valid_until == date.today().isoformat()


def test_expired_archived_and_search_filter():
    make_law("alte-satzung", "# Alte Gebührensatzung\n\n### § 1 Gebühr\n\nDie Gebühr beträgt zehn Taler.\n", "AGS",
             valid_until="2020-01-01")
    pub = client()
    index = pub.get("/recht")
    assert "Außer Kraft getretene Texte" in index.text
    assert "0 Fundstellen" in pub.get("/recht/suche?q=Taler").text      # außer Kraft: nur mit „auch außer Kraft“
    assert "Alte Gebührensatzung" in pub.get("/recht/suche?q=Taler&alle=1").text
    page = pub.get("/recht/alte-satzung")
    assert "außer Kraft" in page.text


def test_cross_references():
    make_law("gemeindeordnung", GEMO, "GemO")
    make_law("hauptsatzung-verweise", HS, "HSV")
    page = client().get("/recht/hauptsatzung-verweise").text
    assert '<a class="law-ref" href="/recht/gemeindeordnung/p2" data-preview="/recht/gemeindeordnung/p2">§ 2 GemO</a>' in page
    assert '<a class="law-ref" href="/recht/hauptsatzung-verweise/p2" data-preview="/recht/hauptsatzung-verweise/p2">§ 2 Abs. 1</a>' in page
    assert ">§ 4 BauGB<" not in page and "§ 4 BauGB" in page                 # nicht eingestellt → kein Link
    assert "law-ref" not in page.split("§ 2 der Friedhofssatzung")[0][-80:]  # anderer Text per Name
    preview = client().get("/recht/gemeindeordnung/p2?format=json").json()
    assert preview["label"].startswith("§ 2") and "Aufgaben" in preview["html"]


def test_shortcode_in_form_and_legal_basis():
    make_law("gemeindeordnung", GEMO, "GemO")
    c = editor()
    page = c.get("/forms")
    r = c.post("/forms", data={"csrf": csrf_of(page.text), "title": "Hund anmelden", "kind": "application"})
    fid = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as db:
        form = db.get(Form, fid)
        form.description = "Grundlage ist [[GemO § 2]], siehe auch [[Unbekannt § 9]]."
        db.commit()
        gid = db.scalar(select(LawText.id).where(LawText.slug == "gemeindeordnung"))
    page = c.get(f"/forms/{fid}/application")
    assert "Rechtsgrundlage" in page.text
    r = c.post(f"/forms/{fid}/application", data={"csrf": csrf_of(page.text), "is_application": "1", "app_catalog": "1",
                                                  "legal_law": [str(gid), ""], "legal_para": ["§ 2", ""]})
    assert r.status_code == 303
    with SessionLocal() as db:
        form = db.get(Form, fid)
        assert json.loads(form.legal_json) == [{"law_id": gid, "anchor": "p2", "para": "§ 2"}]
        token = form.public_token
    fill = client().get(f"/f/{token}").text
    assert 'href="/recht/gemeindeordnung/p2"' in fill and "Rechtsgrundlage" in fill
    assert "[[" not in fill and "Unbekannt § 9" in fill
    assert "§ 2 GemO" in client().get("/antraege").text
    law_page = client().get("/recht/gemeindeordnung").text
    assert "Zugehörige Online-Anträge" in law_page and "Hund anmelden" in law_page


def test_search_typo_and_suggestions():
    make_law("hundesteuersatzung", "# Hundesteuersatzung\n\n### § 4 Steuermaßstab\n\nDie Hundesteuer beträgt 60 Euro.\n", "HStS")
    pub = client()
    r = pub.get("/recht/suche?q=Hundsteuer")
    assert "gezeigt werden Treffer" in r.text and "Hundesteuersatzung" in r.text
    items = pub.get("/recht/suche.json?q=§ 4 HStS").json()
    assert items and items[0]["url"] == "/recht/hundesteuersatzung/p4"
    assert pub.get("/recht/suche.json?q=Hundest").json()[0]["url"] == "/recht/hundesteuersatzung"


def _docx() -> bytes:
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def p(text, style=""):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"
    body = (p("Friedhofssatzung", "Title") + p("Erster Abschnitt", "Heading2") + p("§ 1 Geltungsbereich", "Heading3")
            + p("(1) Diese Satzung gilt für den Friedhof.") + p("§ 2 Ruhezeit", "Heading3") + p("Die Ruhezeit beträgt 20 Jahre."))
    styles = (f'<w:styles {W}><w:style w:styleId="Title"><w:name w:val="Title"/></w:style>'
              '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
              '<w:style w:styleId="Heading3"><w:name w:val="heading 3"/></w:style></w:styles>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", styles)
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _pdf() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    y = 800
    for line in ("Benutzungsordnung Bürgerhaus", "", "§ 1 Zweck", "Das Bürgerhaus dient der Gemeinschaft.", "",
                 "§ 2 Benutzung", "(1) Die Benutzung ist zu beantragen.", "1"):
        cv.drawString(50, y, line)
        y -= 18
    cv.save()
    return buf.getvalue()


def test_docx_and_pdf_import():
    md = lx.parse(__import__("app.law_io", fromlist=["x"]).docx_to_markdown(_docx()))
    assert md.title == "Friedhofssatzung" and md.norms == 2
    c = editor()
    page = c.get("/laws/upload")
    r = c.post("/laws/upload", data={"csrf": csrf_of(page.text), "published": "1", "doc_type": "satzung"},
               files=[("files", ("friedhof.docx", _docx())), ("files", ("buergerhaus.pdf", _pdf()))])
    assert r.status_code == 303
    with SessionLocal() as db:
        fried = db.scalar(select(LawText).where(LawText.title == "Friedhofssatzung"))
        haus = db.scalar(select(LawText).where(LawText.title.like("Benutzungsordnung%")))
        assert fried is not None and sum(1 for s in fried.sections if s.kind == "norm") == 2
        assert haus is not None and sum(1 for s in haus.sections if s.kind == "norm") == 2
        assert "\n1\n" not in haus.body_md                       # Seitenzahl entfernt


def test_attachments_export_import_and_preview_warnings():
    lid = make_law("satzung-anlagen", HS, "SAN")
    with SessionLocal() as db:
        lvl = db.scalar(select(LawLevel).where(LawLevel.name == "Testgemeinde")) or LawLevel(name="Testgemeinde", kind="og")
        db.add(lvl)
        db.flush()
        db.get(LawText, lid).level_id = lvl.id
        db.commit()
    c = editor()
    page = c.get(f"/laws/{lid}/edit")
    assert "Anlagen (PDF)" in page.text and "Neue Fassung vorbereiten" in page.text
    token = csrf_of(page.text)
    c.post(f"/laws/{lid}/attachments", data={"csrf": token}, files={"files": ("plan.pdf", _pdf(), "application/pdf")})
    with SessionLocal() as db:
        att = db.get(LawText, lid).attachments[0]
    r = client().get(f"/recht/satzung-anlagen/anlage/{att.id}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    exported = c.get("/laws/export")
    data = json.loads(exported.content)
    item = next(x for x in data["laws"] if x["slug"] == "satzung-anlagen")
    assert item["level_path"][-1]["name"] == "Testgemeinde" and item["attachments"]
    # Import: vorhandenen Text aktualisieren (frühere Fassung bleibt), neuen Text samt Ebene anlegen
    item["body_md"] = HS.replace("Musterdorf", "Importdorf")
    item["valid_from"] = "2027-01-01"
    data["laws"] = [item, {**item, "slug": "ganz-neu", "title": "Ganz neue Satzung",
                           "level_path": [{"name": "Neue Ebene", "kind": "vg"}]}]
    r = c.post("/laws/import", data={"csrf": token, "update": "1"}, files={"file": ("x.json", json.dumps(data).encode())})
    assert r.status_code == 303
    with SessionLocal() as db:
        law = db.get(LawText, lid)
        assert "Importdorf" in law.body_md and any(v.public for v in law.versions)
        new = db.scalar(select(LawText).where(LawText.slug == "ganz-neu"))
        assert new.level.name == "Neue Ebene" and new.attachments
    # Gliederungshinweise in der Vorschau
    r = c.post("/laws/preview", data={"csrf": token, "html": "1",
                                      "body_md": "# T\n\n### § 1 A\n\nText\n\n### § 3 B\n\n### § 3 C\n\nx\n"})
    warnings = r.json()["warnings"]
    assert any("Nach 1 folgt § 3" in w for w in warnings) and any("mehrfach" in w for w in warnings)
    assert any("keinen Text" in w for w in warnings) and "html" in r.json()["toc"][0]


def test_link_refs_unit():
    lx.invalidate_refs()
    make_law("gemeindeordnung", GEMO, "GemO")
    html = "<p>Nach § 1 GemO und Art. 5 GG sowie <a href='x'>§ 2 GemO</a>.</p>"
    out = str(lx.link_refs(html, "eigene", {"p1"}))
    assert 'href="/recht/gemeindeordnung/p1"' in out and "Art. 5 GG" in out and out.count("law-ref") == 1
    assert re.search(r"<a href='x'>§ 2 GemO</a>", out)
