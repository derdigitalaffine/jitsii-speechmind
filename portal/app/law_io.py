"""Rechtstexte: Word- und PDF-Dateien in Markdown umwandeln, Rechtstexte samt Ebenen und Anlagen ex- und importieren."""

import base64
import io
import json
import re
import secrets
import zipfile
from xml.etree import ElementTree as ET

from sqlalchemy import select

from . import laws as lx, law_catalog
from .config import settings
from .db import LawAttachment, LawLevel, LawText, LawVersion, utcnow

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FORMAT = "jitsii-rechtstexte-1"
MAX_ATTACHMENT = 20 * 1024 * 1024
MAX_VERSIONS = 50


class LawImportError(ValueError):
    pass


def files_dir(law_id: int):
    return settings.data_dir / "laws" / str(law_id)


# --- Word (.docx) -------------------------------------------------------------------------------

def _run_text(run) -> str:
    out = []
    for el in run:
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag == W + "tab":
            out.append(" ")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
    text = "".join(out)
    props = run.find(W + "rPr")
    bold = props is not None and props.find(W + "b") is not None and props.find(W + "b").get(W + "val") not in ("0", "false")
    return f"**{text.strip()}**" + (" " if text.endswith(" ") else "") if bold and text.strip() else text


def _para_text(p) -> str:
    parts = []
    for el in p.iter():
        if el.tag == W + "r" and el.find(W + "t") is not None or el.tag == W + "r" and el.find(W + "tab") is not None:
            parts.append(_run_text(el))
    return re.sub(r"\*\*\s*\*\*", "", "".join(parts)).strip()


def _heading_level(p, styles: dict[str, int]) -> int:
    props = p.find(W + "pPr")
    if props is None:
        return 0
    style = props.find(W + "pStyle")
    if style is not None:
        sid = style.get(W + "val") or ""
        if sid in styles:
            return styles[sid]
        m = re.match(r"(?i)(?:heading|berschrift|Überschrift)\s*(\d)", sid)
        if m:
            return int(m.group(1))
    outline = props.find(W + "outlineLvl")
    if outline is not None and (outline.get(W + "val") or "").isdigit():
        return int(outline.get(W + "val")) + 1
    return 0


def _styles(zf: zipfile.ZipFile) -> dict[str, int]:
    """Formatvorlagen-ID → Überschriftenebene (auch deutsche Namen wie „Überschrift 2“)."""
    try:
        if zf.getinfo("word/styles.xml").file_size > 5 * 1024 * 1024:
            return {}
        root = ET.fromstring(zf.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return {}
    out = {}
    for st in root.iter(W + "style"):
        name = st.find(W + "name")
        label = (name.get(W + "val") if name is not None else "") or ""
        m = re.match(r"(?i)^(?:heading|überschrift)\s*(\d)$", label.strip())
        if m:
            out[st.get(W + "styleId") or ""] = int(m.group(1))
        elif label.strip().lower() == "title":
            out[st.get(W + "styleId") or ""] = 1
    return out


def docx_to_markdown(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        # Entpackte Größe begrenzen (ZIP-Bombe): der Text eines Rechtstexts ist weit kleiner
        if sum(i.file_size for i in zf.infolist()) > 200 * 1024 * 1024 or zf.getinfo("word/document.xml").file_size > 30 * 1024 * 1024:
            raise LawImportError("Die Word-Datei ist zu groß.")
        root = ET.fromstring(zf.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise LawImportError("Die Datei ist kein lesbares Word-Dokument (.docx).") from None
    styles = _styles(zf)
    body = root.find(W + "body")
    lines: list[str] = []
    for block in list(body) if body is not None else []:
        if block.tag == W + "p":
            text = _para_text(block)
            level = _heading_level(block, styles)
            if level and text:
                lines += ["", "#" * min(level, 6) + " " + text.replace("**", ""), ""]
            elif text:
                lines += [text, ""]
        elif block.tag == W + "tbl":
            rows = []
            for tr in block.iter(W + "tr"):
                rows.append([" ".join(_para_text(p) for p in tc.iter(W + "p")).replace("|", "/") for tc in tr.iter(W + "tc")])
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines += ["", "| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]] + [""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


# --- PDF ----------------------------------------------------------------------------------------

def pdf_to_markdown(data: bytes) -> str:
    """Text aus einem PDF mit Textebene (keine Texterkennung für eingescannte Seiten). Die Gliederung erkennt danach
    der Parser aus allein stehenden Zeilen wie „§ 3 Ortsbezirke“."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:500]]
    except (PdfReadError, ValueError, KeyError):
        raise LawImportError("Das PDF lässt sich nicht lesen.") from None
    text = "\n".join(pages)
    if len(text.strip()) < 20:
        raise LawImportError("Das PDF enthält keinen Text (eingescannt?). Bitte eine Textfassung (Word, Markdown) verwenden.")
    lines, out = text.replace("\r", "").split("\n"), []
    for line in lines:
        s = line.strip()
        if re.fullmatch(r"(?:Seite\s*)?\d+(?:\s*(?:von|/)\s*\d+)?", s):   # Seitenzahlen
            continue
        # Trennstriche am Zeilenende zusammenziehen, sonst Absatz/Überschrift erhalten
        if out and out[-1].endswith("-") and s[:1].islower():
            out[-1] = out[-1][:-1] + s
            continue
        is_head = bool(lx.NORM_RE.match(s) or lx.GROUP_RE.match(s) or lx.ABS_LINE_RE.match(line))
        if out and s and out[-1] and not is_head and not out[-1].endswith((".", ":", ";")) and not (
                lx.NORM_RE.match(out[-1]) or lx.GROUP_RE.match(out[-1])):
            out[-1] += " " + s
            continue
        if is_head and out and out[-1]:
            out.append("")
        out.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def to_markdown(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx") or data[:4] == b"PK\x03\x04":
        return docx_to_markdown(data)
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return pdf_to_markdown(data)
    return lx.decode_upload(data)


# --- Export / Import -----------------------------------------------------------------------------

def _level_path(level: LawLevel | None) -> list[dict]:
    return [{"name": lv.name, "kind": lv.kind, "description": lv.description} for lv in lx.level_path(level)]


def export(db, laws: list[LawText], *, versions: bool = True, attachments: bool = True) -> bytes:
    data = {"format": FORMAT, "exported_at": utcnow().isoformat(timespec="seconds"), "laws": []}
    for law in laws:
        item = {k: getattr(law, k) for k in ("title", "short_title", "slug", "doc_type", "body_md", "version_note",
                                              "issued_on", "valid_from", "valid_until", "published", "planned_md",
                                              "planned_valid_from", "planned_note")}
        item["topics"] = law_catalog.topics(law)
        item["level_path"] = _level_path(law.level)
        if versions:
            item["versions"] = [{"saved_at": v.saved_at.isoformat(timespec="seconds"), "saved_by": v.saved_by,
                                 "version_note": v.version_note, "body_md": v.body_md, "public": v.public, "title": v.title,
                                 "valid_from": v.valid_from, "valid_until": v.valid_until} for v in law.versions]
        if attachments:
            item["attachments"] = []
            for a in law.attachments:
                path = files_dir(law.id) / a.file
                if path.is_file():
                    item["attachments"].append({"name": a.name, "data": base64.b64encode(path.read_bytes()).decode()})
        data["laws"].append(item)
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def _ensure_level(db, path: list[dict]) -> LawLevel | None:
    parent = None
    for entry in path[:10]:
        name = " ".join(str(entry.get("name") or "").split())[:200]
        if not name:
            break
        q = select(LawLevel).where(LawLevel.name == name,
                                   LawLevel.parent_id.is_(None) if parent is None else LawLevel.parent_id == parent.id)
        level = db.scalar(q)
        if level is None:
            level = LawLevel(name=name, parent=parent, kind=entry.get("kind") if entry.get("kind") in lx.LEVEL_KINDS else "sonstige",
                             description=str(entry.get("description") or "")[:2000])
            db.add(level)
            db.flush()
        parent = level
    return parent


def _date(value) -> str:
    value = str(value or "").strip()
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""


def import_(db, raw: bytes, user, *, update_existing: bool) -> tuple[int, int]:
    """Gibt (neu, aktualisiert) zurück. Vorhandene Texte (gleiche Adresse) werden auf Wunsch als neue Fassung
    aktualisiert – der bisherige Stand bleibt als frühere Fassung erhalten –, sonst als neue Texte angelegt."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LawImportError("Die Datei ist kein Export von Rechtstexten.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("laws"), list):
        raise LawImportError("Die Datei ist kein Export von Rechtstexten.")
    created = updated = 0
    for item in data["laws"][:500]:
        if not isinstance(item, dict) or not str(item.get("body_md") or "").strip():
            continue
        md = str(item["body_md"])[:lx.MAX_SIZE]
        level = _ensure_level(db, item.get("level_path") or [])
        existing = db.scalar(select(LawText).where(LawText.slug == str(item.get("slug") or ""))) if update_existing else None
        if existing is not None:
            law = existing
            if law.body_md != md:
                # neue Fassung (anderes Inkrafttreten): bisherige bleibt öffentlich abrufbar, sonst interne Sicherung
                new_from = _date(item.get("valid_from"))
                lx.snapshot(db, law, public=bool(new_from) and new_from != law.valid_from, valid_until=new_from,
                            saved_by=user.name)
            updated += 1
        else:
            law = LawText(created_by=user.id, slug=lx.unique_slug(db, str(item.get("slug") or item.get("title") or "rechtstext")))
            db.add(law)
            created += 1
        law.title = " ".join(str(item.get("title") or lx.parse(md).title or "Rechtstext").split())[:400]
        if "topics" in item:
            try:
                law.topics_json = json.dumps(law_catalog.clean_topics(item["topics"]), ensure_ascii=False)
            except ValueError as exc:
                raise LawImportError(str(exc)) from exc
        law.short_title = " ".join(str(item.get("short_title") or "").split())[:80]
        law.doc_type = item.get("doc_type") if item.get("doc_type") in lx.DOC_TYPES else "sonstiges"
        law.version_note = " ".join(str(item.get("version_note") or "").split())[:255]
        for key in ("issued_on", "valid_from", "valid_until", "planned_valid_from"):
            setattr(law, key, _date(item.get(key)))
        law.planned_md = str(item.get("planned_md") or "")[:lx.MAX_SIZE] if law.planned_valid_from else ""
        law.planned_note = " ".join(str(item.get("planned_note") or "").split())[:255]
        law.level_id = level.id if level else None
        law.body_md = md
        law.published = bool(item.get("published")) if existing is None else law.published
        law.updated_by = user.id
        db.flush()
        if existing is None:
            for v in (item.get("versions") or [])[:MAX_VERSIONS]:
                if isinstance(v, dict) and v.get("body_md"):
                    db.add(LawVersion(law_id=law.id, saved_by=str(v.get("saved_by") or "")[:255],
                                      version_note=str(v.get("version_note") or "")[:255], body_md=str(v["body_md"])[:lx.MAX_SIZE],
                                      public=bool(v.get("public")), title=str(v.get("title") or "")[:400],
                                      valid_from=_date(v.get("valid_from")), valid_until=_date(v.get("valid_until"))))
        for n, a in enumerate((item.get("attachments") or [])[:30]):
            try:
                content = base64.b64decode(a.get("data") or "", validate=True)
            except (ValueError, AttributeError):
                continue
            if content.startswith(b"%PDF") and len(content) <= MAX_ATTACHMENT:
                add_attachment(law, str(a.get("name") or "Anlage.pdf"), content, position=n)
        lx.store(db, law)
    lx.invalidate_refs()
    return created, updated


def add_attachment(law: LawText, name: str, content: bytes, position: int | None = None) -> LawAttachment:
    files_dir(law.id).mkdir(parents=True, exist_ok=True)
    file = secrets.token_hex(10) + ".pdf"
    (files_dir(law.id) / file).write_bytes(content)
    clean = re.sub(r"[\x00-\x1f/\\]", "", name).strip()[:255] or "Anlage.pdf"
    att = LawAttachment(name=clean, file=file, size=len(content),
                        position=position if position is not None else len(law.attachments))
    law.attachments.append(att)
    return att
