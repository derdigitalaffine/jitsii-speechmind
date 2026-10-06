"""Stammdaten eines Rechtstexts aus dem Markdown-Volltext lesen – als YAML-Kopf zwischen „---“-Zeilen
(bevorzugt) oder als „Schlüssel: Wert“-Zeilen direkt am Anfang. Dazu die Musterdatei und ein fertiger Prompt,
mit dem sich ein Text per KI (LLM) in dieses Format bringen lässt."""

import re
import unicodedata
from datetime import date

from . import laws as lx

# Schlüssel (klein, ohne Umlaute/Leerzeichen) → Feld
KEYS = {
    "titel": "title", "title": "title", "bezeichnung": "title",
    "kurztitel": "short_title", "abkurzung": "short_title", "abkuerzung": "short_title", "kurzel": "short_title",
    "kuerzel": "short_title", "short_title": "short_title",
    "adresse": "slug", "slug": "slug", "kurzname": "slug", "url": "slug",
    "art": "doc_type", "typ": "doc_type", "dokumentart": "doc_type", "doc_type": "doc_type", "rechtsform": "doc_type",
    "ebene": "level", "level": "level", "korperschaft": "level", "koerperschaft": "level", "gebietskorperschaft": "level",
    "fassung": "version_note", "stand": "version_note", "version": "version_note", "version_note": "version_note",
    "ausgefertigt": "issued_on", "ausgefertigtam": "issued_on", "ausfertigung": "issued_on", "issued_on": "issued_on",
    "inkraft": "valid_from", "inkraftseit": "valid_from", "inkrafttreten": "valid_from", "gultigab": "valid_from",
    "gueltigab": "valid_from", "valid_from": "valid_from",
    "ausserkraft": "valid_until", "auserkraft": "valid_until", "ausserkraftab": "valid_until", "gultigbis": "valid_until",
    "gueltigbis": "valid_until", "valid_until": "valid_until",
    "einzelvorschrift": "outline", "einzelvorschriften": "outline", "untersteebene": "outline", "gliederung": "outline",
    "outline": "outline",
    "veroffentlicht": "published", "veroeffentlicht": "published", "published": "published", "offentlich": "published",
}
LABELS = {"title": "Titel", "short_title": "Kurztitel", "slug": "Adresse", "doc_type": "Art", "level": "Ebene",
          "version_note": "Fassung", "issued_on": "Ausgefertigt", "valid_from": "In Kraft seit",
          "valid_until": "Außer Kraft ab", "published": "Veröffentlicht", "outline": "Unterste Ebene"}
MONTHS = {"januar": 1, "jan": 1, "februar": 2, "feb": 2, "marz": 3, "maerz": 3, "mar": 3, "april": 4, "apr": 4, "mai": 5,
          "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
          "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12}
LINE_RE = re.compile(r"^\s*([A-Za-zÄÖÜäöüß_][\wÄÖÜäöüß .\-]{0,30}?)\s*:\s*(.*?)\s*$")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "").lower().replace("ß", "ss"))
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


def parse_date(value: str) -> str | None:
    """„12.03.2024“, „2024-03-12“, „12. März 2024“ → „2024-03-12“; None, wenn nicht lesbar."""
    v = str(value or "").strip().strip("\"'")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v) or None
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{2,4})", v)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.fullmatch(r"(\d{1,2})\.?\s*([A-Za-zÄÖÜäöü]+)\.?\s+(\d{4})", v)
            if not m or _norm(m.group(2)) not in MONTHS:
                return None
            d, mo, y = int(m.group(1)), MONTHS[_norm(m.group(2))], int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _doc_type(value: str) -> str | None:
    n = _norm(value)
    for key, label in lx.DOC_TYPES.items():
        if n in (_norm(key), _norm(label)) or (n and _norm(label).startswith(n)):
            return key
    return None


_OUTLINE_WORDS = {"automatisch": "", "auto": "", "paragraf": "paragraf", "paragraph": "paragraf", "paragrafen": "paragraf",
                  "paragraphen": "paragraf", "artikel": "paragraf", "art": "paragraf", "paragrafundartikel": "paragraf",
                  "ziffern": "ziffer", "nummer": "nr", "nummern": "nr", "abschnitte": "abschnitt", "klauseln": "klausel",
                  "punkte": "punkt", "regeln": "regel", "reinenummern": "nummer", "nummerierung": "nummer", "zahlen": "nummer"}


def outline_mode(value: str) -> str | None:
    """„Ziffer“, „§“, „automatisch“, „reine Nummern“ … → Schlüssel aus laws.OUTLINE_MODES; None, wenn unbekannt."""
    if str(value or "").strip().startswith("§"):
        return "paragraf"
    n = _norm(value)
    if n in lx.OUTLINE_MODES:
        return n
    if n in _OUTLINE_WORDS:
        return _OUTLINE_WORDS[n]
    return next((k for k, label in lx.OUTLINE_MODES.items() if _norm(label) == n), None)


def _bool(value: str) -> bool | None:
    n = _norm(value)
    if n in ("ja", "yes", "true", "1", "wahr", "x"):
        return True
    if n in ("nein", "no", "false", "0", "falsch"):
        return False
    return None


def split(markdown: str) -> tuple[dict, str, list[str]]:
    """(Rohwerte je Feld, Text ohne Kopf, Hinweise). Rohwerte sind noch nicht geprüft (siehe clean)."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    raw, notes, end = {}, [], 0
    start = next((i for i, x in enumerate(lines) if x.strip()), None)
    if start is None:
        return {}, markdown, []
    if lines[start].strip() == "---":
        close = next((i for i in range(start + 1, min(len(lines), start + 60)) if lines[i].strip() in ("---", "...")), None)
        if close is None:
            return {}, markdown, ["Der Kopf beginnt mit „---“, endet aber nicht mit einer zweiten „---“-Zeile."]
        block, end = lines[start + 1:close], close + 1
        for ln in block:
            if not ln.strip() or ln.strip().startswith("#"):
                continue
            m = LINE_RE.match(ln)
            if not m:
                notes.append(f"Zeile im Kopf nicht verstanden: „{ln.strip()[:60]}“")
                continue
            field = KEYS.get(_norm(m.group(1)))
            if field is None:
                notes.append(f"Unbekannter Schlüssel „{m.group(1).strip()}“ – wird ignoriert.")
                continue
            raw[field] = m.group(2).strip().strip("\"'")
    else:
        # „Schlüssel: Wert“-Zeilen am Anfang – nur bekannte Schlüssel, damit „§ 1: …“ o. Ä. nicht verschluckt wird
        i = start
        while i < len(lines) and lines[i].strip():
            m = LINE_RE.match(lines[i])
            field = KEYS.get(_norm(m.group(1))) if m else None
            if field is None:
                break
            raw[field] = m.group(2).strip().strip("\"'")
            i += 1
        if not raw or (i < len(lines) and lines[i].strip()):
            return {}, markdown, []   # kein sauberer Block → nichts übernehmen
        end = i
    body = "\n".join(lines[end:]).lstrip("\n")
    return raw, body, notes


def clean(db, raw: dict) -> tuple[dict, list[str]]:
    """Rohwerte prüfen: Datum vereinheitlichen, Art und Ebene zuordnen. Gibt (Formularwerte, Hinweise)."""
    from .db import LawLevel
    out, notes = {}, []
    for field, value in raw.items():
        if field in ("issued_on", "valid_from", "valid_until"):
            if value:
                iso = parse_date(value)
                if iso is None:
                    notes.append(f"{LABELS[field]}: „{value}“ ist kein Datum (z. B. 12.03.2024).")
                else:
                    out[field] = iso
        elif field == "doc_type":
            key = _doc_type(value)
            if key:
                out[field] = key
            else:
                notes.append(f"Art „{value}“ unbekannt – möglich: {', '.join(lx.DOC_TYPES.values())}.")
        elif field == "level":
            level = None
            for lv in db.query(LawLevel).all():
                if _norm(lv.name) == _norm(value):
                    level = lv
                    break
            if level is None:
                notes.append(f"Ebene „{value}“ nicht gefunden – bitte unter Rechtstexte › Ebenen anlegen oder im Formular wählen.")
            else:
                out["level_id"] = str(level.id)
        elif field == "outline":
            mode = outline_mode(value)
            if mode is None:
                notes.append(f"Unterste Ebene „{value}“ unbekannt – möglich: automatisch, §, Abschnitt, Klausel, Ziffer, "
                             "Nr., Punkt, Regel, reine Nummern.")
            else:
                out[field] = mode
        elif field == "published":
            flag = _bool(value)
            if flag is None:
                notes.append(f"Veröffentlicht: „{value}“ – bitte ja oder nein.")
            else:
                out["published"] = "1" if flag else ""
        else:
            out[field] = " ".join(value.split())
    return out, notes


def template(levels: list[str] | None = None) -> str:
    """Musterdatei (Markdown mit YAML-Kopf) – auch als Vorlage für KI-Werkzeuge."""
    level = (levels or ["Ortsgemeinde Musterdorf"])[0]
    return f"""---
titel: Satzung über die Benutzung der Grillhütte der Ortsgemeinde Musterdorf
kurztitel: GrillS
art: Satzung
ebene: {level}
fassung: Fassung vom 12.03.2024
ausgefertigt: 12.03.2024
in kraft: 01.04.2024
außer kraft:
veröffentlicht: nein
einzelvorschrift: automatisch
---

# Satzung über die Benutzung der Grillhütte der Ortsgemeinde Musterdorf

Der Ortsgemeinderat hat auf Grund des § 24 der Gemeindeordnung (GemO) folgende Satzung beschlossen:

## Erster Abschnitt – Allgemeines

### § 1 Geltungsbereich

(1) Diese Satzung gilt für die Grillhütte am Weiher.

(2) Die Grillhütte ist eine öffentliche Einrichtung der Ortsgemeinde.

### § 2 Benutzung

(1) Die Benutzung bedarf der Erlaubnis. Für das Entgelt gilt [[§ 3]].

## Zweiter Abschnitt – Entgelte

### § 3 Entgelt

| Leistung | Betrag |
| --- | --- |
| Pauschale je Tag | 100 € |
| Wasser, Kanal, Strom je angefangene 25 Personen | 10 € |

## Schlussbestimmungen

### § 4 Inkrafttreten

Diese Satzung tritt am Tage nach ihrer öffentlichen Bekanntmachung in Kraft.
"""


def prompt(levels: list[str] | None = None) -> str:
    """Fertiger Prompt: Text per KI in das Portal-Format bringen (Ergebnis danach einfügen und prüfen lassen)."""
    kinds = ", ".join(lx.DOC_TYPES.values())
    lv = "; ".join(levels or []) or "z. B. Ortsgemeinde Musterdorf"
    return f"""Wandle den unten stehenden Rechtstext (Satzung, Verordnung, Gesetz …) in Markdown im folgenden Format um.
Antworte NUR mit dem fertigen Markdown, ohne Erklärungen und ohne Codeblock-Zeichen (```).

Regeln:
1. Ganz oben ein Kopf zwischen zwei Zeilen „---“ mit genau diesen Schlüsseln (leer lassen, was nicht im Text steht):
   titel, kurztitel, art, ebene, fassung, ausgefertigt, in kraft, außer kraft, veröffentlicht, einzelvorschrift
   - art: eine von {kinds}
   - einzelvorschrift: automatisch (Normalfall); nur bei Texten ohne § und Artikel die Bezeichnung der kleinsten
     Einheit, z. B. Ziffer, Abschnitt, Klausel, Nr., Punkt, Regel oder „reine Nummern“ (1., 3.2 …)
   - ebene: eine von {lv}
   - Datumsangaben als TT.MM.JJJJ, veröffentlicht: nein
2. Danach „# “ + vollständiger Titel, dann die Eingangsformel (Präambel) als normaler Text.
3. Gliederungsebenen (Teil, Kapitel, Abschnitt) als „## …“, Unterebenen als „### …“ usw.
4. Jeder Paragraf bzw. Artikel als eigene Überschrift eine Ebene tiefer als sein Abschnitt, z. B. „### § 3 Benutzung“
   bzw. „### Art. 2 Änderung“ – Nummer und Überschrift in einer Zeile. Texte ohne § (Verträge, Regeln, Richtlinien):
   die kleinste Einheit genauso, z. B. „### Ziffer 3 Haftung“, „## 3. Haftung“ oder „### 3.2 Schäden“.
5. Absätze beginnen mit „(1) “, „(2) “ … am Zeilenanfang, mit Leerzeile dazwischen. Nummern und Buchstaben
   in Aufzählungen bleiben erhalten (1., 2. bzw. a), b)).
6. Verweise auf Paragrafen DESSELBEN Textes als [[§ 4]] (bzw. [[Ziffer 3]], [[Nr. 3.2]]), auf andere Gesetze als
   [[GemO § 24]] (Abkürzung + §).
7. Tabellen als Markdown-Tabellen. Nichts weglassen, nichts umformulieren, keine eigenen Ergänzungen;
   Silbentrennungen und Seitenumbrüche aus PDFs entfernen.

Beispiel für das Format:

{template(levels)}

Hier der umzuwandelnde Text:

"""
