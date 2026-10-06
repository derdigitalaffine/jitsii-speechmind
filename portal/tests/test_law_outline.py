"""Rechtstexte: unterste Ebene (Einzelvorschrift) automatisch erkennen oder festlegen – Verträge mit Ziffern,
reine Nummern (3.2), Abschnitte als kleinste Einheit, Bücher/Teile über Abschnitten, Verweise wie [[Ziffer 3]]."""

from sqlalchemy import select

from app import laws as lx
from app import laws_meta
from app.db import LawText, SessionLocal, get_settings, set_setting

from conftest import client, csrf_of
from test_laws import editor, make_law, module_on, save  # noqa: F401 – Fixture und Hilfen

VERTRAG = """# Mustervertrag über die Nutzung des Dorfgemeinschaftshauses

Zwischen der Ortsgemeinde und dem Verein wird folgender Vertrag geschlossen:

## 1. Gegenstand

Die Gemeinde überlässt dem Verein den Saal.

## 2. Pflichten

Für die Pflichten gilt Folgendes.

### 2.1 Reinigung

Der Verein reinigt den Saal. Schäden siehe [[Ziffer 3]] und [[2.2]].

### 2.2 Schlüssel

Der Schlüssel wird beim Hausmeister abgeholt.

## 3. Haftung

Der Verein haftet für Schäden.
"""

BGB = """# Bürgerliches Gesetzbuch

## Buch 1 Allgemeiner Teil

### Abschnitt 1 Personen

#### Titel 1 Natürliche Personen

##### § 1 Beginn der Rechtsfähigkeit

Die Rechtsfähigkeit des Menschen beginnt mit der Vollendung der Geburt.

##### § 2 Eintritt der Volljährigkeit

Die Volljährigkeit tritt mit der Vollendung des 18. Lebensjahres ein.
"""

REGELN = """# Hausordnung Grillhütte

Abschnitt 1 Allgemeines

Die Grillhütte steht allen offen.

Abschnitt 2 Ruhezeiten

Ab 22 Uhr ist Ruhe.
"""


def kinds(parsed):
    return {n.number: (n.kind, n.anchor) for n in parsed.nodes if n.number}


def test_contract_deepest_numbers_are_norms():
    p = lx.parse(VERTRAG)
    k = kinds(p)
    assert k["1."] == ("norm", "n1") and k["2.1"] == ("norm", "n2-1") and k["2.2"] == ("norm", "n2-2")
    assert k["3."] == ("norm", "n3")
    assert k["2."][0] == "group"           # „2.“ mit 2.1/2.2 darunter ist Zwischenüberschrift, eigener Text bleibt
    assert "Pflichten gilt" in next(n for n in p.nodes if n.number == "2.").plain
    assert lx.unit_name(p) == "Nummern" and lx.jump_prefix(p) == "Nr."
    assert not any("Keine Einzelvorschriften" in w for w in lx.check_outline(p))


def test_bgb_books_and_paragraphs_unchanged():
    p = lx.parse(BGB)
    k = kinds(p)
    assert k["§ 1"] == ("norm", "p1") and k["§ 2"] == ("norm", "p2")
    assert all(k[x][0] == "group" for x in ("Buch 1", "Abschnitt 1", "Titel 1"))
    assert lx.unit_name(p) == "§§ / Artikel"


def test_plain_section_lines_and_modes():
    p = lx.parse(REGELN)
    k = kinds(p)
    assert k["Abschnitt 1"] == ("norm", "abschnitt-1") and k["Abschnitt 2"] == ("norm", "abschnitt-2")
    assert lx.unit_name(p) == "Abschnitte"
    # festgelegt: „§ und Artikel“ → keine Einzelvorschriften, nur Gliederung
    assert lx.parse(VERTRAG, "paragraf").norms == 0
    # festgelegt: reine Nummern → wie automatisch
    assert lx.parse(VERTRAG, "nummer").norms == 4
    md = "# V\n\n## Ziffer 1 Zweck\n\nText.\n\n### Unterpunkt\n\nMehr.\n\n## Ziffer 2 Ende\n\nSchluss.\n"
    auto = kinds(lx.parse(md))
    assert auto["Ziffer 1"][0] == "group" and auto["Ziffer 2"] == ("norm", "ziffer-2")
    fixed = kinds(lx.parse(md, "ziffer"))
    assert fixed["Ziffer 1"] == ("norm", "ziffer-1") and fixed["Ziffer 2"] == ("norm", "ziffer-2")


def test_refs_to_units():
    p = lx.parse(VERTRAG)
    anchors = {n.anchor for n in p.nodes}
    own = ("vertrag", anchors)
    assert lx.resolve_ref("Ziffer 3", own, {})[0] == "/recht/vertrag/n3"
    assert lx.resolve_ref("Nr. 2.2", own, {})[0] == "/recht/vertrag/n2-2"
    assert lx.resolve_ref("2.1", own, {})[0] == "/recht/vertrag/n2-1"
    assert lx.resolve_ref("Ziffer 9", own, {})[0] is None
    refs = {"dgh": ("vertrag", "DGH", anchors), "bimschv 1": ("b", "b", {"p3"})}
    assert lx.resolve_ref("DGH Ziffer 2.1", None, refs)[0] == "/recht/vertrag/n2-1"
    assert lx.resolve_ref("BImSchV 1 § 3", None, refs)[0] == "/recht/b/p3"
    assert lx.resolve_ref("BImSchV 1", None, refs)[0] == "/recht/b"


def test_meta_key_and_editor_setting():
    raw, _body, _notes = laws_meta.split("---\ntitel: X\neinzelvorschrift: Ziffer\n---\n\n# X\n")
    with SessionLocal() as db:
        assert laws_meta.clean(db, raw)[0]["outline"] == "ziffer"
        assert laws_meta.clean(db, {"outline": "§"})[0]["outline"] == "paragraf"
        assert laws_meta.clean(db, {"outline": "reine Nummern"})[0]["outline"] == "nummer"
        assert laws_meta.clean(db, {"outline": "automatisch"})[0]["outline"] == ""
        assert laws_meta.clean(db, {"outline": "Quatsch"})[1]
    law_id = make_law("dgh-vertrag", VERTRAG, "DGH")
    c = editor()
    page = c.get(f"/laws/{law_id}/edit")
    assert 'name="outline"' in page.text and "reine Nummern" in page.text
    prev = c.post("/laws/preview", data={"csrf": csrf_of(page.text), "body_md": VERTRAG, "outline": "paragraf"}).json()
    assert prev["norms"] == 0
    prev = c.post("/laws/preview", data={"csrf": csrf_of(page.text), "body_md": VERTRAG}).json()
    assert prev["norms"] == 4 and prev["unit"] == "Nummern"
    r = save(c, law_id, VERTRAG, outline="paragraf")
    assert r.status_code == 303
    with SessionLocal() as db:
        law = db.get(LawText, law_id)
        assert law.outline == "paragraf" and not any(s.kind == "norm" for s in law.sections)
    save(c, law_id, VERTRAG, outline="")
    with SessionLocal() as db:
        assert {s.anchor for s in db.get(LawText, law_id).sections if s.kind == "norm"} == {"n1", "n2-1", "n2-2", "n3"}


def test_public_view_links_and_styles():
    make_law("dgh-vertrag", VERTRAG, "DGH")
    lx.invalidate_refs()
    page = client().get("/recht/dgh-vertrag")
    assert page.status_code == 200
    assert 'href="/recht/dgh-vertrag/n3"' in page.text          # [[Ziffer 3]] verlinkt
    assert 'class="lex-unit lex-norm lex-d1" id="n2-1"' in page.text
    assert 'class="lex-unit lex-group lex-d0" id="' in page.text
    assert 'data-anchors="n1 n2-1 n2-2 n3"' in page.text and '<span class="input-group-text">Nr.</span>' in page.text
    single = client().get("/recht/dgh-vertrag/n2-2")
    assert single.status_code == 200 and "Schlüssel" in single.text
    hits = client().get("/recht/suche", params={"q": "2.1 Reinigung"})
    assert "Reinigung" in hits.text
    quick = lx.quick(SessionLocal(), "Ziffer 3")
    assert any(q["anchor"] == "n3" for q in quick)


def test_form_legal_basis_with_unit():
    law_id = make_law("dgh-vertrag", VERTRAG, "DGH")
    with SessionLocal() as db:
        out = lx.clean_form_refs(db, [str(law_id), str(law_id), str(law_id)], ["Ziffer 2.1", "3", "Nr. 9"])
    assert [o["anchor"] for o in out] == ["n2-1", "n3", ""]


def test_reparse_all_once():
    law_id = make_law("dgh-vertrag", VERTRAG, "DGH")
    with SessionLocal() as db:
        law = db.get(LawText, law_id)
        for s in law.sections:
            s.kind = "group"                       # Stand vor dem Update simulieren
        set_setting(db, "laws_outline_version", "1")
        db.commit()
        assert lx.reparse_all(db) >= 1
        assert get_settings(db)["laws_outline_version"] == lx.OUTLINE_VERSION
        assert lx.reparse_all(db) == 0
        assert sum(1 for s in db.scalar(select(LawText).where(LawText.id == law_id)).sections if s.kind == "norm") == 4
