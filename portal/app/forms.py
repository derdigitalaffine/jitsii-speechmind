"""Formularserver: Aufbau, Prüfung der Antworten, Auswertung, Export und Benachrichtigungen.

Ein Formular ist eine Liste von Elementen (JSON). Fragetypen wie in Nextcloud Forms:
kurze Antwort (Text, E-Mail, Telefon, Zahl, eigenes Muster), langer Text, Einfachauswahl,
Mehrfachauswahl, Auswahlliste, Datum, Uhrzeit, Datum mit Uhrzeit, lineare Skala, Farbe und
Datei-Upload. Dazu Gliederungselemente: Überschrift, Zwischenüberschrift, Hinweistext,
Trennlinie und Seitenumbruch (mehrseitige Formulare).

Antworten werden je Frage unter ihrer ID gespeichert, Auswahlen als Text der Option. So bleiben
alte Antworten lesbar, wenn das Formular später geändert wird.
"""

import csv
import io
import json
import re
import secrets
import shutil
from collections import Counter
from datetime import date, datetime, time as dtime
from pathlib import Path

from sqlalchemy import select

from . import mailtpl, notify
from .config import settings
from .db import Form, FormInvite, FormResponse, FormShare, Group, GroupMember, User, get_settings, to_local, utcnow
from .planning import EMAIL_RE
from .security import new_link_token

# Typ: (Bezeichnung, Icon, ist eine Frage)
TYPES = {
    "short": ("Kurze Antwort", "fa-font", True),
    "long": ("Langer Text", "fa-align-left", True),
    "radio": ("Einfachauswahl", "fa-circle-dot", True),
    "checkbox": ("Mehrfachauswahl", "fa-square-check", True),
    "dropdown": ("Auswahlliste", "fa-square-caret-down", True),
    "date": ("Datum", "fa-calendar", True),
    "time": ("Uhrzeit", "fa-clock", True),
    "datetime": ("Datum und Uhrzeit", "fa-calendar-days", True),
    "scale": ("Lineare Skala", "fa-sliders", True),
    "color": ("Farbe", "fa-palette", True),
    "file": ("Datei-Upload", "fa-paperclip", True),
    "geo": ("Ort in der Karte (Punkt, Linie, Fläche)", "fa-location-dot", True),
    "heading": ("Überschrift", "fa-heading", False),
    "subheading": ("Zwischenüberschrift", "fa-text-height", False),
    "text": ("Hinweistext", "fa-paragraph", False),
    "divider": ("Trennlinie", "fa-minus", False),
    "pagebreak": ("Neue Seite", "fa-file-circle-plus", False),
}
SUBTYPES = {"text": "Text", "email": "E-Mail-Adresse", "phone": "Telefonnummer", "number": "Zahl",
            "regex": "Eigenes Muster (regulärer Ausdruck)"}
CHOICE_TYPES = {"radio", "checkbox", "dropdown"}
GEOMETRIES = {"point": "Punkt", "line": "Linie", "polygon": "Fläche"}
OTHER = "__other__"
MAX_FILE_MB = 20
PHONE_RE = re.compile(r"^\+?[0-9 ()/\-.]{3,30}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
EXT_RE = re.compile(r"^[a-z0-9]{1,10}$")


def _str(value, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def _int(value, lo: int, hi: int, default: int | None) -> int | None:
    try:
        return min(max(int(value), lo), hi)
    except (TypeError, ValueError):
        return default


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def new_id() -> str:
    return secrets.token_hex(4)


# --- Aufbau ------------------------------------------------------------------

def clean_schema(raw) -> list[dict]:
    """Bereinigt den Aufbau aus dem Baukasten (nur bekannte Felder, Längen begrenzt, eindeutige IDs)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    items, seen = [], set()
    for src in raw if isinstance(raw, list) else []:
        if not isinstance(src, dict) or src.get("type") not in TYPES:
            continue
        kind = src["type"]
        qid = str(src.get("id") or "")
        if not ID_RE.match(qid) or qid in seen:
            qid = new_id()
        seen.add(qid)
        item = {"id": qid, "type": kind, "title": _str(src.get("title"), 500),
                "description": _str(src.get("description"), 5000)}
        if TYPES[kind][2]:
            item["required"] = bool(src.get("required"))
        if kind == "short":
            item["subtype"] = src.get("subtype") if src.get("subtype") in SUBTYPES else "text"
            item["placeholder"] = _str(src.get("placeholder"), 200)
            if item["subtype"] == "regex":
                pattern = _str(src.get("pattern"), 300)
                try:
                    re.compile(pattern)
                except re.error:
                    pattern = ""
                item["pattern"] = pattern
                item["pattern_hint"] = _str(src.get("pattern_hint"), 200)
            if item["subtype"] == "number":
                item["min"], item["max"] = _num(src.get("min")), _num(src.get("max"))
        elif kind == "long":
            item["placeholder"] = _str(src.get("placeholder"), 200)
            item["max_length"] = _int(src.get("max_length"), 1, 20000, None)
        elif kind in CHOICE_TYPES:
            options, labels = [], set()
            for opt in src.get("options") or []:
                label = _str(opt.get("label") if isinstance(opt, dict) else opt, 500)
                if label and label not in labels:
                    labels.add(label)
                    oid = str(opt.get("id") if isinstance(opt, dict) else "") or new_id()
                    options.append({"id": oid if ID_RE.match(oid) else new_id(), "label": label})
            item["options"] = options[:300]
            item["shuffle"] = bool(src.get("shuffle"))
            if kind != "dropdown":
                item["other"] = bool(src.get("other"))
            if kind == "checkbox":
                item["min"] = _int(src.get("min"), 0, 300, None)
                item["max"] = _int(src.get("max"), 1, 300, None)
        elif kind in ("date", "datetime"):
            item["min"] = _str(src.get("min"), 16)
            item["max"] = _str(src.get("max"), 16)
        elif kind == "scale":
            item["min"] = _int(src.get("min"), 0, 1, 1)
            item["max"] = _int(src.get("max"), 2, 10, 5)
            item["low_label"] = _str(src.get("low_label"), 100)
            item["high_label"] = _str(src.get("high_label"), 100)
        elif kind == "file":
            exts = [e.strip().lower().lstrip(".") for e in re.split(r"[,;\s]+", str(src.get("file_types") or ""))]
            item["file_types"] = [e for e in exts if EXT_RE.match(e)][:30]
            item["max_size_mb"] = _int(src.get("max_size_mb"), 1, MAX_FILE_MB, 10)
            item["max_files"] = _int(src.get("max_files"), 1, 10, 1)
        elif kind == "geo":
            item["geometry"] = src.get("geometry") if src.get("geometry") in GEOMETRIES else "point"
            item["allow_gps"] = src.get("allow_gps") is not False
            item["show_inputs"] = src.get("show_inputs") is not False
        elif kind == "heading" or kind == "subheading" or kind == "pagebreak":
            pass
        items.append(item)
    return items[:500]


def schema(form: Form) -> list[dict]:
    try:
        data = json.loads(form.schema_json or "[]")
    except ValueError:
        data = []
    return data if isinstance(data, list) else []


def questions(items: list[dict]) -> list[dict]:
    return [i for i in items if TYPES.get(i.get("type"), ("", "", False))[2]]


def pages(items: list[dict]) -> list[dict]:
    """Teilt das Formular an Seitenumbrüchen. Jede Seite: {title, description, items}."""
    result = [{"title": "", "description": "", "items": []}]
    for item in items:
        if item["type"] == "pagebreak":
            result.append({"title": item.get("title", ""), "description": item.get("description", ""), "items": []})
        else:
            result[-1]["items"].append(item)
    # leere erste Seite (Formular beginnt mit Seitenumbruch) weglassen
    return [p for i, p in enumerate(result) if p["items"] or i > 0] or result


def shuffled(options: list[dict]) -> list[dict]:
    opts = list(options)
    secrets.SystemRandom().shuffle(opts)
    return opts


def is_open(form: Form) -> bool:
    return form.active and not (form.expires_at and form.expires_at < utcnow())


# --- Antworten prüfen ------------------------------------------------------------

def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate(items: list[dict], data, files) -> tuple[dict, dict, dict]:
    """Prüft die Eingaben. Gibt (Antworten, Fehler je Frage-ID, Uploads je Frage-ID) zurück.

    data: Formularwerte (getlist/get), files: {feldname: [UploadFile]}
    """
    answers, errors, uploads = {}, {}, {}
    for item in questions(items):
        qid, kind, name = item["id"], item["type"], f"q_{item['id']}"
        required = item.get("required")
        value = None
        if kind == "checkbox":
            labels = {o["label"] for o in item.get("options", [])}
            chosen = [v for v in data.getlist(name) if v in labels]
            if item.get("other") and OTHER in data.getlist(name):
                other = _str(data.get(name + "__other"), 500)
                if other:
                    chosen.append(other)
                else:
                    errors[qid] = "Bitte den Text für „Sonstiges“ angeben."
            n = len(chosen)
            if required and not n:
                errors.setdefault(qid, "Bitte mindestens eine Option wählen.")
            elif n and item.get("min") and n < item["min"]:
                errors[qid] = f"Bitte mindestens {item['min']} Optionen wählen."
            elif n and item.get("max") and n > item["max"]:
                errors[qid] = f"Bitte höchstens {item['max']} Optionen wählen."
            value = chosen or None
        elif kind == "file":
            given = [f for f in files.get(name, []) if getattr(f, "filename", "")]
            if required and not given:
                errors[qid] = "Bitte eine Datei hochladen."
            elif len(given) > item.get("max_files", 1):
                errors[qid] = f"Höchstens {item.get('max_files', 1)} Datei(en)."
            else:
                for f in given:
                    ext = Path(f.filename).suffix.lower().lstrip(".")
                    if item.get("file_types") and ext not in item["file_types"]:
                        errors[qid] = "Erlaubt sind nur: " + ", ".join(item["file_types"])
                    elif (f.size or 0) > item.get("max_size_mb", 10) * 1024 * 1024:
                        errors[qid] = f"Die Datei „{f.filename}“ ist größer als {item.get('max_size_mb', 10)} MB."
                if qid not in errors and given:
                    uploads[qid] = given
            continue
        else:
            raw = _str(data.get(name), 20000)
            if kind in ("radio", "dropdown"):
                labels = {o["label"] for o in item.get("options", [])}
                if raw == OTHER and item.get("other"):
                    raw = _str(data.get(name + "__other"), 500)
                    if not raw:
                        errors[qid] = "Bitte den Text für „Sonstiges“ angeben."
                elif raw and raw not in labels:
                    errors[qid] = "Bitte eine der angebotenen Optionen wählen."
            elif kind == "short":
                raw = raw[:1000].replace("\n", " ")
                sub = item.get("subtype", "text")
                if raw and sub == "email" and not EMAIL_RE.match(raw):
                    errors[qid] = "Bitte eine gültige E-Mail-Adresse angeben."
                elif raw and sub == "phone" and not PHONE_RE.match(raw):
                    errors[qid] = "Bitte eine gültige Telefonnummer angeben."
                elif raw and sub == "number":
                    num = _num(raw)
                    if num is None:
                        errors[qid] = "Bitte eine Zahl angeben."
                    elif item.get("min") is not None and num < item["min"]:
                        errors[qid] = f"Die Zahl muss mindestens {item['min']:g} sein."
                    elif item.get("max") is not None and num > item["max"]:
                        errors[qid] = f"Die Zahl darf höchstens {item['max']:g} sein."
                elif raw and sub == "regex" and item.get("pattern"):
                    try:
                        ok = re.fullmatch(item["pattern"], raw) is not None
                    except re.error:
                        ok = True
                    if not ok:
                        errors[qid] = item.get("pattern_hint") or "Die Eingabe hat nicht das erwartete Format."
            elif kind == "long":
                if item.get("max_length") and len(raw) > item["max_length"]:
                    errors[qid] = f"Bitte höchstens {item['max_length']} Zeichen."
            elif kind == "date" and raw:
                d = _parse_date(raw)
                if d is None:
                    errors[qid] = "Bitte ein gültiges Datum angeben."
                elif item.get("min") and _parse_date(item["min"]) and d < _parse_date(item["min"]):
                    errors[qid] = f"Frühestens {_parse_date(item['min']).strftime('%d.%m.%Y')}."
                elif item.get("max") and _parse_date(item["max"]) and d > _parse_date(item["max"]):
                    errors[qid] = f"Spätestens {_parse_date(item['max']).strftime('%d.%m.%Y')}."
            elif kind == "time" and raw:
                try:
                    dtime.fromisoformat(raw)
                except ValueError:
                    errors[qid] = "Bitte eine gültige Uhrzeit angeben."
            elif kind == "datetime" and raw:
                try:
                    dt = datetime.fromisoformat(raw)
                    if item.get("min") and _parse_date(item["min"][:10]) and dt.date() < _parse_date(item["min"][:10]):
                        errors[qid] = "Der Zeitpunkt liegt zu früh."
                    elif item.get("max") and _parse_date(item["max"][:10]) and dt.date() > _parse_date(item["max"][:10]):
                        errors[qid] = "Der Zeitpunkt liegt zu spät."
                except ValueError:
                    errors[qid] = "Bitte Datum und Uhrzeit angeben."
            elif kind == "scale" and raw:
                n = _int(raw, -1, 99, None)
                if n is None or not item.get("min", 1) <= n <= item.get("max", 5):
                    errors[qid] = "Bitte einen Wert auf der Skala wählen."
            elif kind == "color" and raw and not COLOR_RE.match(raw):
                errors[qid] = "Bitte eine Farbe wählen."
            elif kind == "geo" and raw and item.get("geometry", "point") != "point":
                shape = parse_shape(raw, item["geometry"])
                if shape is None:
                    errors[qid] = ("Bitte eine Linie mit mindestens zwei Punkten zeichnen." if item["geometry"] == "line"
                                   else "Bitte eine Fläche mit mindestens drei Eckpunkten zeichnen.")
                else:
                    answers[qid] = shape
                    continue
            elif kind == "geo" and raw:
                point = parse_point(raw, data.get(name + "__acc"), data.get(name + "__src"))
                if point is None:
                    errors[qid] = "Bitte einen Punkt in der Karte wählen oder Breite und Länge angeben (z. B. 49.4930, 7.7680)."
                else:
                    answers[qid] = point
                    continue
            if required and not raw:
                errors.setdefault(qid, "Bitte ausfüllen.")
            value = raw or None
        if value is not None and qid not in errors:
            answers[qid] = value
    return answers, errors, uploads


GEO_RE = re.compile(r"^\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$")


def parse_point(raw: str, accuracy=None, source=None) -> dict | None:
    """„Breite, Länge“ (WGS84) → {lat, lon, acc, src}. Genauigkeit in Metern nur bei GPS."""
    m = GEO_RE.match(raw or "")
    if not m:
        return None
    lat, lon = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    point = {"lat": round(lat, 6), "lon": round(lon, 6)}
    acc = _num(accuracy)
    if acc is not None and 0 < acc < 100000:
        point["acc"] = round(acc)
    if source in ("gps", "map", "manual"):
        point["src"] = source
    return point


def _haversine(a, b) -> float:
    import math
    r = 6371008.8
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _ring_area(pts) -> float:
    import math
    r, area = 6371008.8, 0.0
    for i, p1 in enumerate(pts):
        p2 = pts[(i + 1) % len(pts)]
        area += math.radians(p2[0] - p1[0]) * (2 + math.sin(math.radians(p1[1])) + math.sin(math.radians(p2[1])))
    return abs(area * r * r / 2)


def parse_shape(raw: str, kind: str) -> dict | None:
    """Linie/Fläche aus dem Formular (GeoJSON-Geometrie) → {type, coordinates, length, area, center}."""
    from .maps import clean_geometry
    try:
        geom = clean_geometry(json.loads(raw), max_points=1000)
    except ValueError:
        return None
    want = {"line": "LineString", "polygon": "Polygon"}[kind]
    if geom is None or geom["type"] != want:
        return None
    pts = geom["coordinates"] if kind == "line" else geom["coordinates"][0][:-1]
    length = sum(_haversine(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    area = 0.0
    if kind == "polygon":
        length += _haversine(pts[-1], pts[0])
        area = _ring_area(pts)
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return {"type": kind, "coordinates": geom["coordinates"], "length": round(length, 1), "area": round(area, 1),
            "center": [round((min(lons) + max(lons)) / 2, 6), round((min(lats) + max(lats)) / 2, 6)]}


def _fmt_len(m: float) -> str:
    return f"{m / 1000:.2f} km".replace(".", ",") if m >= 1000 else f"{round(m)} m"


def _fmt_area(m2: float) -> str:
    if m2 >= 1e6:
        return f"{m2 / 1e6:.3f} km²".replace(".", ",")
    if m2 >= 1e4:
        return f"{m2 / 1e4:.2f} ha".replace(".", ",")
    return f"{round(m2)} m²"


def geo_feature(value, label: str = "") -> dict | None:
    """Antwort einer Kartenfrage als GeoJSON-Feature (für Karten in Auswertung und Vorgang)."""
    if not isinstance(value, dict):
        return None
    if value.get("type") == "line":
        geom = {"type": "LineString", "coordinates": value.get("coordinates")}
    elif value.get("type") == "polygon":
        geom = {"type": "Polygon", "coordinates": value.get("coordinates")}
    elif "lat" in value:
        geom = {"type": "Point", "coordinates": [value["lon"], value["lat"]]}
    else:
        return None
    return {"type": "Feature", "geometry": geom, "properties": {"label": label}}


def files_dir(form_id: int, response_id: int | None = None) -> Path:
    base = settings.data_dir / "forms" / str(form_id)
    return base / str(response_id) if response_id is not None else base


async def store_uploads(response: FormResponse, uploads: dict) -> dict:
    """Speichert hochgeladene Dateien und gibt die Einträge für die Antworten zurück."""
    stored = {}
    target = files_dir(response.form_id, response.id)
    for qid, files in uploads.items():
        entries = []
        for f in files:
            target.mkdir(parents=True, exist_ok=True)
            ext = Path(f.filename).suffix.lower()[:11]
            name = secrets.token_hex(8) + (ext if re.match(r"^\.[a-z0-9]{1,10}$", ext) else "")
            size = 0
            with open(target / name, "wb") as out:
                while chunk := await f.read(1024 * 1024):
                    size += len(chunk)
                    out.write(chunk)
            entries.append({"file": name, "name": Path(f.filename).name[:200], "size": size,
                            "type": (f.content_type or "")[:100]})
        stored[qid] = entries
    return stored


def delete_files(form_id: int, response_id: int | None = None) -> None:
    shutil.rmtree(files_dir(form_id, response_id), ignore_errors=True)


# --- Darstellung, Export, Auswertung ---------------------------------------------

def display(item: dict, value) -> str:
    if value is None or value == "":
        return ""
    kind = item.get("type")
    if kind == "file":
        return ", ".join(f.get("name", "") for f in value if isinstance(f, dict))
    if kind == "geo" and isinstance(value, dict) and value.get("type") == "line":
        return f"Linie, {len(value.get('coordinates') or [])} Punkte, Länge {_fmt_len(value.get('length') or 0)}"
    if kind == "geo" and isinstance(value, dict) and value.get("type") == "polygon":
        n = max(len((value.get("coordinates") or [[]])[0]) - 1, 0)
        return f"Fläche, {n} Eckpunkte, {_fmt_area(value.get('area') or 0)} (Umfang {_fmt_len(value.get('length') or 0)})"
    if kind == "geo" and isinstance(value, dict) and "lat" in value:
        return f"{value.get('lat'):.6f}, {value.get('lon'):.6f}" + (f" (±{value['acc']} m)" if value.get("acc") else "")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if kind == "date":
        d = _parse_date(str(value))
        return d.strftime("%d.%m.%Y") if d else str(value)
    if kind == "datetime":
        try:
            return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y, %H:%M")
        except ValueError:
            return str(value)
    return str(value)


def respondent(resp: FormResponse) -> str:
    if resp.name and resp.email:
        return f"{resp.name} <{resp.email}>"
    return resp.name or resp.email or "anonym"


def _headers(items: list[dict]) -> list[str]:
    seen: Counter = Counter()
    heads = []
    for q in questions(items):
        title = q.get("title") or TYPES[q["type"]][0]
        seen[title] += 1
        heads.append(title if seen[title] == 1 else f"{title} ({seen[title]})")
    return heads


def to_csv(form: Form, responses: list[FormResponse]) -> str:
    """CSV für Excel: Semikolon, UTF-8 mit BOM."""
    items = questions(schema(form))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Nr.", "Eingang", "Von (Name)", "Von (E-Mail)", *_headers(items)])
    for n, resp in enumerate(responses, start=1):
        answers = resp.answers
        writer.writerow([n, to_local(resp.created_at).strftime("%d.%m.%Y %H:%M:%S"), resp.name, resp.email,
                         *[display(q, answers.get(q["id"])) for q in items]])
    return "﻿" + buf.getvalue()


def to_json(form: Form, responses: list[FormResponse]) -> str:
    items = questions(schema(form))
    heads = _headers(items)
    data = {
        "formular": {"id": form.id, "titel": form.title, "beschreibung": form.description,
                     "exportiert": to_local(utcnow()).isoformat(timespec="seconds")},
        "fragen": [{"id": q["id"], "titel": h, "typ": q["type"]} for q, h in zip(items, heads)],
        "antworten": [
            {"nr": n, "id": r.id, "eingang": to_local(r.created_at).isoformat(timespec="seconds"),
             "name": r.name or None, "email": r.email or None,
             "werte": {h: _json_value(q, r.answers.get(q["id"])) for q, h in zip(items, heads)}}
            for n, r in enumerate(responses, start=1)],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _json_value(item: dict, value):
    if item["type"] == "file" and isinstance(value, list):
        return [f.get("name") for f in value if isinstance(f, dict)]
    if item["type"] == "geo" and isinstance(value, dict):
        feature = geo_feature(value)   # GeoJSON-Geometrie, dazu Länge/Fläche in Metern
        if feature and value.get("type") in ("line", "polygon"):
            return {"geometrie": feature["geometry"], "laenge_m": value.get("length"), "flaeche_m2": value.get("area")}
        return value
    if item["type"] == "scale" and value not in (None, ""):
        return _int(value, -1, 99, None)
    if item["type"] == "short" and item.get("subtype") == "number" and value not in (None, ""):
        num = _num(value)
        return int(num) if num is not None and num.is_integer() else num
    return value


def answers_text(form: Form, resp: FormResponse) -> str:
    lines = []
    answers = resp.answers
    for q in questions(schema(form)):
        value = display(q, answers.get(q["id"]))
        lines.append(f"{q.get('title') or TYPES[q['type']][0]}:\n  {value or '–'}")
    return "\n".join(lines)


def summary(form: Form, responses: list[FormResponse]) -> list[dict]:
    """Auswertung je Frage: Häufigkeiten bei Auswahl und Skala, sonst die letzten Antworten."""
    result = []
    for q in questions(schema(form)):
        values = [r.answers.get(q["id"]) for r in responses]
        given = [v for v in values if v not in (None, "", [])]
        entry = {"q": q, "count": len(given), "total": len(responses)}
        if q["type"] in CHOICE_TYPES:
            counts = Counter()
            for v in given:
                for label in (v if isinstance(v, list) else [v]):
                    counts[label] += 1
            labels = [o["label"] for o in q.get("options", [])]
            rows = [(label, counts.pop(label, 0)) for label in labels]
            other = sum(counts.values())
            if other or q.get("other"):
                rows.append(("Sonstiges", other))
            entry["rows"] = rows
            entry["others"] = list(counts.keys())[:20]
            entry["chart"] = {"type": "doughnut" if q["type"] != "checkbox" and len(rows) <= 6 else "bar",
                              "horizontal": True, "labels": [r[0] for r in rows], "values": [r[1] for r in rows]}
        elif q["type"] == "scale":
            nums = [_int(v, -1, 99, None) for v in given]
            nums = [n for n in nums if n is not None]
            rng = list(range(q.get("min", 1), q.get("max", 5) + 1))
            c = Counter(nums)
            entry["rows"] = [(str(n), c.get(n, 0)) for n in rng]
            entry["average"] = (sum(nums) / len(nums)) if nums else None
            entry["chart"] = {"type": "bar", "labels": [str(n) for n in rng], "values": [c.get(n, 0) for n in rng]}
        elif q["type"] == "short" and q.get("subtype") == "number":
            nums = [n for n in (_num(v) for v in given) if n is not None]
            entry["average"] = (sum(nums) / len(nums)) if nums else None
            entry["minmax"] = (min(nums), max(nums)) if nums else None
            entry["latest"] = [display(q, v) for v in given[-8:]][::-1]
        elif q["type"] == "geo":
            feats = [geo_feature(v, f"Antwort {n}") for n, v in enumerate(values, start=1)]
            entry["points"] = [f for f in feats if f][:5000]
            entry["latest"] = [display(q, v) for v in given[-8:]][::-1]
        else:
            entry["latest"] = [display(q, v) for v in given[-8:]][::-1]
        result.append(entry)
    return result


# --- Einladungen und Mails -----------------------------------------------------

def deadline_text(form: Form) -> str:
    if not form.expires_at:
        return ""
    return "Bitte bis " + to_local(form.expires_at).strftime("%d.%m.%Y, %H:%M Uhr") + " ausfüllen."


def invite_link(inv: FormInvite) -> str:
    return f"{settings.portal_base_url}/f/i/{inv.token}"


def public_link(form: Form) -> str | None:
    return f"{settings.portal_base_url}/f/{form.public_token}" if form.public_token else None


def _send_invite(db, form: Form, inv: FormInvite, actor: User, key: str, cfg) -> bool:
    subject, body = mailtpl.render(db, key, {
        "name": inv.name or inv.email, "titel": form.title, "beschreibung": form.description,
        "link": invite_link(inv), "absender": actor.name, "frist": deadline_text(form)}, cfg)
    return notify.enqueue(db, inv.email, subject, body, key, cfg, reply_to=actor.email)


def invite(db, form: Form, actor: User, user_ids: list[int], group_ids: list[int],
           emails: list[str]) -> tuple[int, int, bool]:
    """Lädt Benutzer, Gruppenmitglieder und Gäste ein. Gibt (neu, schon eingeladen, Mail eingerichtet)."""
    cfg = get_settings(db)
    existing = {i.email for i in form.invites}
    targets: list[tuple[str, str, int | None, str]] = []
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids), User.active.is_(True))):
            targets.append((u.email, u.name, u.id, ""))
    for g in db.scalars(select(Group).where(Group.id.in_(group_ids))) if group_ids else []:
        for u in g.members:
            if u.active:
                targets.append((u.email, u.name, u.id, g.name))
    for email in emails:
        user = db.scalar(select(User).where(User.email == email))
        targets.append((email, user.name if user else "", user.id if user else None, ""))
    added, skipped = 0, 0
    for email, name, uid, via in targets:
        if email in existing:
            skipped += 1
            continue
        existing.add(email)
        inv = FormInvite(email=email, name=name, user_id=uid, via=via, token=new_link_token())
        form.invites.append(inv)
        db.flush()
        if _send_invite(db, form, inv, actor, "form_invite", cfg):
            inv.invited_at = utcnow()
        added += 1
    return added, skipped, notify.mail_configured(cfg)


def remind(db, form: Form, actor: User, invites: list[FormInvite] | None = None) -> int:
    cfg = get_settings(db)
    count = 0
    for inv in invites if invites is not None else form.invites:
        if inv.submitted_at:
            continue
        if _send_invite(db, form, inv, actor, "form_reminder" if inv.invited_at else "form_invite", cfg):
            if inv.invited_at:
                inv.reminded_at = utcnow()
            else:
                inv.invited_at = utcnow()
            count += 1
    return count


def notify_new_response(db, form: Form, resp: FormResponse) -> None:
    """Mail an die Verantwortlichen, auf Wunsch mit CSV/JSON (diese Antwort oder alle)."""
    if not form.notify:
        return
    cfg = get_settings(db)
    recipients = []
    if form.owner and form.owner.active:
        recipients.append(form.owner.email)
    for addr in re.split(r"[,;\s]+", form.notify_to or ""):
        addr = addr.strip().lower()
        if addr and EMAIL_RE.match(addr) and addr not in recipients:
            recipients.append(addr)
    if not recipients:
        return
    all_responses = list(form.responses)
    number = next((n for n, r in enumerate(all_responses, start=1) if r.id == resp.id), len(all_responses))
    scope = all_responses if form.notify_scope == "all" else [resp]
    slug = re.sub(r"[^a-z0-9]+", "-", form.title.lower()).strip("-")[:40] or "formular"
    name = f"{slug}-alle-antworten" if form.notify_scope == "all" else f"{slug}-antwort-{number}"
    attachments = []
    if form.notify_csv:
        attachments.append({"filename": f"{name}.csv", "content": to_csv(form, scope), "mime": "text/csv"})
    if form.notify_json:
        attachments.append({"filename": f"{name}.json", "content": to_json(form, scope),
                            "mime": "application/json"})
    subject, body = mailtpl.render(db, "form_response", {
        "titel": form.title, "nummer": number, "anzahl": len(all_responses),
        "zeitpunkt": to_local(resp.created_at).strftime("%d.%m.%Y, %H:%M Uhr"),
        "von": respondent(resp), "antworten": answers_text(form, resp) if form.notify_answers else "",
        "link": f"{settings.portal_base_url}/forms/{form.id}/responses/{resp.id}"}, cfg)
    for addr in recipients:
        notify.enqueue(db, addr, subject, body, "form_response", cfg, attachments=attachments or None)


def confirm_to_respondent(db, form: Form, resp: FormResponse, email: str, name: str) -> None:
    if not form.confirm_mail or not email:
        return
    subject, body = mailtpl.render(db, "form_confirmation", {
        "name": name or email, "titel": form.title, "antworten": answers_text(form, resp),
        "zeitpunkt": to_local(resp.created_at).strftime("%d.%m.%Y, %H:%M Uhr")})
    notify.enqueue(db, email, subject, body, "form_confirmation")


def respondent_email(form: Form, answers: dict) -> str:
    """Erste beantwortete E-Mail-Frage (für die Eingangsbestätigung bei öffentlichen Links)."""
    for q in questions(schema(form)):
        if q["type"] == "short" and q.get("subtype") == "email" and answers.get(q["id"]):
            return str(answers[q["id"]])
    return ""


def copy_form(db, form: Form, owner: User) -> Form:
    items = schema(form)
    for item in items:  # neue IDs, damit nichts mit dem Original verwechselt wird
        item["id"] = new_id()
    clone = Form(owner_id=owner.id, title=(form.title + " (Kopie)")[:255], description=form.description,
                 schema_json=json.dumps(items, ensure_ascii=False), anonymous=form.anonymous,
                 multiple=form.multiple, submit_message=form.submit_message, confirm_mail=form.confirm_mail,
                 notify=form.notify, notify_answers=form.notify_answers, notify_json=form.notify_json,
                 notify_csv=form.notify_csv, notify_scope=form.notify_scope, active=True)
    db.add(clone)
    return clone


def template_items() -> list[dict]:
    """Startaufbau eines neuen Formulars."""
    return [{"id": new_id(), "type": "short", "title": "Name", "description": "", "required": True,
             "subtype": "text", "placeholder": ""},
            {"id": new_id(), "type": "short", "title": "E-Mail-Adresse", "description": "", "required": False,
             "subtype": "email", "placeholder": ""}]


def user_invites(db, user: User) -> list[FormInvite]:
    """Einladungen einer angemeldeten Person (über Konto oder E-Mail-Adresse)."""
    q = select(FormInvite).where((FormInvite.user_id == user.id) | (FormInvite.email == user.email))
    return list(db.scalars(q.order_by(FormInvite.id.desc())))


# --- Freigaben im Portal -------------------------------------------------------

VIEW, INVITE, EDIT, OWNER = 1, 2, 3, 4
LEVELS = {VIEW: ("Ergebnisse einsehen", "Antworten, Auswertung und Export ansehen"),
          INVITE: ("Einladen", "zusätzlich Teilnehmende einladen, erinnern und den öffentlichen Link verwalten"),
          EDIT: ("Bearbeiten", "zusätzlich Fragen und Einstellungen ändern, Antworten und das Formular löschen")}


def access_level(db, form: Form, user: User) -> int:
    """0 = kein Zugriff, 1–3 = Freigabestufe, 4 = Besitzer:in oder Admin."""
    if user.is_admin or form.owner_id == user.id:
        return OWNER
    group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    levels = db.scalars(select(FormShare.level).where(
        FormShare.form_id == form.id,
        (FormShare.user_id == user.id) | (FormShare.group_id.in_(group_ids))))
    return max(levels, default=0)


def shared_with(db, user: User) -> list[tuple[Form, int]]:
    """Formulare, die für die Person (direkt oder über eine Gruppe) freigegeben sind, mit Stufe."""
    group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    rows = db.execute(select(FormShare.form_id, FormShare.level).where(
        (FormShare.user_id == user.id) | (FormShare.group_id.in_(group_ids)))).all()
    best: dict[int, int] = {}
    for form_id, level in rows:
        best[form_id] = max(level, best.get(form_id, 0))
    found = db.scalars(select(Form).where(Form.id.in_(best), Form.owner_id.is_(None) | (Form.owner_id != user.id))).all() if best else []
    return sorted(((f, best[f.id]) for f in found), key=lambda x: x[0].updated_at, reverse=True)
