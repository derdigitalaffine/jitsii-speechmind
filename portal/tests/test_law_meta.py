"""Rechtstexte: Stammdaten aus dem Markdown-Kopf, Musterdatei, Prompt, Prüfung in der Vorschau."""

from sqlalchemy import select

from app import laws_meta
from app.db import LawLevel, LawText, SessionLocal

from conftest import csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")

YAML_MD = """---
titel: Benutzungssatzung Grillhütte Kopfdorf
kurztitel: GrillKopf
art: Satzung
ebene: Kopfdorf
fassung: Fassung vom 12.03.2024
ausgefertigt: 12. März 2024
in kraft: 01.04.2024
veröffentlicht: ja
farbe: blau
---

# Benutzungssatzung Grillhütte Kopfdorf

### § 1 Geltung

(1) Gilt.
"""


def test_split_variants():
    raw, body, notes = laws_meta.split(YAML_MD)
    assert raw["title"].startswith("Benutzungssatzung") and raw["published"] == "ja" and body.startswith("# Benutzungssatzung")
    assert any("farbe" in n for n in notes)
    raw, body, _ = laws_meta.split("Titel: Hauptsatzung\nArt: Satzung\n\n# Hauptsatzung\n\n§ 1 Name")
    assert raw == {"title": "Hauptsatzung", "doc_type": "Satzung"} and body.startswith("# Hauptsatzung")
    assert laws_meta.split("Hinweis: steht nur so da\n# x")[0] == {}      # unbekannter Schlüssel → kein Kopf
    assert laws_meta.split("---\ntitel: x\nohne Ende")[2]                  # fehlende schließende Zeile → Hinweis


def test_create_with_header_and_preview():
    settings(module_laws="1")
    with SessionLocal() as db:
        if not db.scalar(select(LawLevel).where(LawLevel.name == "Kopfdorf")):
            db.add(LawLevel(name="Kopfdorf", kind="og"))
            db.commit()
        level_id = db.scalar(select(LawLevel.id).where(LawLevel.name == "Kopfdorf"))
    c = login(*ADMIN)
    page = c.get("/laws/new")
    token = csrf_of(page.text)
    prev = c.post("/laws/preview", data={"csrf": token, "body_md": YAML_MD}).json()
    assert prev["ok"] and prev["meta"]["Titel"].startswith("Benutzungssatzung") and prev["meta"]["Ebene"] == "Kopfdorf"
    assert prev["meta_raw"]["issued_on"] == "2024-03-12" and prev["norms"] == 1
    assert any("farbe" in n for n in prev["meta_notes"])
    r = c.post("/laws/new", data={"csrf": token, "body_md": YAML_MD, "title": "", "doc_type": "sonstiges", "read_meta": "1"})
    assert r.status_code == 303
    with SessionLocal() as db:
        law = db.scalar(select(LawText).where(LawText.short_title == "GrillKopf"))
        assert law.title == "Benutzungssatzung Grillhütte Kopfdorf" and law.doc_type == "satzung" and law.level_id == level_id
        assert law.issued_on == "2024-03-12" and law.valid_from == "2024-04-01" and law.published
        assert law.version_note == "Fassung vom 12.03.2024" and not law.body_md.startswith("---")
    # ohne Haken bleibt der Kopf im Text und die Formularwerte gelten
    r = c.post("/laws/new", data={"csrf": token, "body_md": YAML_MD.replace("GrillKopf", "GrillOhne"), "title": "Formulartitel",
                                  "doc_type": "sonstiges", "read_meta": ["0"]})
    with SessionLocal() as db:
        law = db.scalar(select(LawText).where(LawText.title == "Formulartitel"))
        assert law.body_md.startswith("---") and law.doc_type == "sonstiges"


def test_template_and_prompt_downloads():
    c = login(*ADMIN)
    md = c.get("/laws/muster.md")
    assert md.status_code == 200 and md.text.startswith("---\ntitel:") and "attachment" in md.headers["content-disposition"]
    raw, body, notes = laws_meta.split(md.text)
    assert raw["doc_type"] == "Satzung" and not notes and "### § 1" in body
    p = c.get("/laws/prompt.txt")
    assert p.status_code == 200 and "Antworte NUR mit dem fertigen Markdown" in p.text and "[[GemO § 24]]" in p.text
    assert "Kopfdorf" in p.text or "Ortsgemeinde" in p.text
