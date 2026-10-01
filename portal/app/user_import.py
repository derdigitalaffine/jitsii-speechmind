"""Benutzer per CSV importieren.

Spalten (englisch, Groß-/Kleinschreibung egal, Reihenfolge beliebig):
  email        Pflicht
  name         Anzeigename (leer: aus der Adresse abgeleitet)
  password     Startpasswort (leer: Konto ohne Passwort, auf Wunsch Einladung per Mail)
  groups       Gruppen, getrennt durch ; oder | (fehlende Gruppen werden angelegt)
  permissions  video;shortlinks;forms;users (leer: video)
  admin        yes/no (wird nur bei Import durch Admins beachtet)

Trennzeichen Komma oder Semikolon (Excel speichert in Deutschland mit Semikolon; dann Gruppen
und Rechte mit | trennen), UTF-8 mit oder ohne BOM, ersatzweise Windows-1252. Eine erste Zeile
„sep=,“ (steht in der Vorlage, damit Excel die Spalten erkennt) wird übersprungen.
"""

import csv
import io
import json
import re
import secrets
import time
from pathlib import Path

from sqlalchemy import func, select

from .config import settings
from .db import PERMISSIONS, Group, User
from .planning import EMAIL_RE, name_from_email
from .security import hash_password

COLUMNS = ["email", "name", "password", "groups", "permissions", "admin"]
ALIASES = {"e-mail": "email", "mail": "email", "passwort": "password", "gruppe": "groups", "gruppen": "groups",
           "group": "groups", "rechte": "permissions", "permission": "permissions", "is_admin": "admin"}
MAX_ROWS = 5000
MIN_PASSWORD = 10
TRUE = {"1", "yes", "y", "true", "ja", "j", "x"}


def template_csv() -> str:
    """Vorlage mit Beispielzeilen (nur ASCII, damit Excel sie ohne Kodierungsprobleme öffnet)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerow(["erika.mustermann@example.org", "Erika Mustermann", "", "Bauamt;Kita", "video;forms", "no"])
    writer.writerow(["max.muster@example.org", "Max Muster", "Startpasswort-2026", "Bauamt", "video", "no"])
    writer.writerow(["it@example.org", "", "", "", "video;shortlinks;forms;users", "yes"])
    # „sep=,“ lässt auch deutsches Excel die Komma-Datei per Doppelklick richtig in Spalten öffnen
    return "sep=,\r\n" + buf.getvalue()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;|]", value or "") if p.strip()]


def parse(data: bytes, db, actor: User) -> tuple[list[dict], list[str]]:
    """Liest die CSV und prüft jede Zeile. Gibt (Zeilen, allgemeine Fehler) zurück. Ändert nichts."""
    text = _decode(data)
    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith("sep="):
        text = "\n".join(lines[1:])
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return [], ["Die Datei ist leer."]
    keys = [ALIASES.get(h.strip().lower(), h.strip().lower()) for h in header]
    if "email" not in keys:
        return [], ["Die Spalte „email“ fehlt. Bitte die Vorlage verwenden."]
    unknown = [h for h, k in zip(header, keys) if k not in COLUMNS and h.strip()]
    problems = [f"Unbekannte Spalte(n) werden ignoriert: {', '.join(unknown)}"] if unknown else []
    existing_groups = {g.name.lower(): g.name for g in db.scalars(select(Group))}
    seen, rows = set(), []
    for line_no, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue
        if len(rows) >= MAX_ROWS:
            problems.append(f"Mehr als {MAX_ROWS} Zeilen – der Rest wird ignoriert.")
            break
        values = {k: (raw[i].strip() if i < len(raw) else "") for i, k in enumerate(keys) if k in COLUMNS}
        email = values.get("email", "").lower()
        row = {"line": line_no, "email": email, "name": " ".join(values.get("name", "").split())[:200],
               "password": values.get("password", ""), "groups": [], "new_groups": [], "permissions": "",
               "admin": False, "action": "", "errors": [], "notes": []}
        if not EMAIL_RE.match(email):
            row["errors"].append("ungültige E-Mail-Adresse")
        elif email in seen:
            row["errors"].append("Adresse steht mehrfach in der Datei")
        seen.add(email)
        if row["password"] and len(row["password"]) < MIN_PASSWORD:
            row["errors"].append(f"Passwort kürzer als {MIN_PASSWORD} Zeichen")
        for name in _split(values.get("groups", "")):
            name = " ".join(name.split())[:120]
            canonical = existing_groups.get(name.lower())
            if canonical is None:
                existing_groups[name.lower()] = name
                row["new_groups"].append(name)
                canonical = name
            if canonical not in row["groups"]:
                row["groups"].append(canonical)
        perms_raw = [p.lower() for p in _split(values.get("permissions", ""))]
        bad_perms = [p for p in perms_raw if p not in PERMISSIONS]
        if bad_perms:
            row["errors"].append("unbekannte Rechte: " + ", ".join(bad_perms) + f" (erlaubt: {', '.join(PERMISSIONS)})")
        row["permissions"] = ",".join(p for p in PERMISSIONS if p in perms_raw) if perms_raw else "video"
        if values.get("admin", "").lower() in TRUE:
            if actor.is_admin:
                row["admin"] = True
            else:
                row["notes"].append("„admin“ ignoriert – nur Admins dürfen Admins anlegen")
        user = db.scalar(select(User).where(func.lower(User.email) == email)) if email else None
        if row["errors"]:
            row["action"] = "error"
        elif user is None:
            row["action"] = "create"
            row["name"] = row["name"] or name_from_email(email)
        else:
            row["action"] = "update"
            row["name"] = row["name"] or user.name
            missing = [g for g in row["groups"] if g.lower() not in {x.name.lower() for x in user.groups}]
            row["groups"] = missing
            row["notes"].append("existiert bereits – nur Gruppen werden ergänzt"
                                + (f": {', '.join(missing)}" if missing else " (nichts zu tun)"))
            if user.is_admin and not actor.is_admin:
                row["action"], row["notes"] = "skip", ["Admin-Konto – nur durch Admins änderbar"]
            elif not missing:
                row["action"] = "skip"
        rows.append(row)
    return rows, problems


def summary(rows: list[dict]) -> dict:
    created = [r for r in rows if r["action"] == "create"]
    return {"create": len(created), "with_password": sum(1 for r in created if r["password"]),
            "without_password": sum(1 for r in created if not r["password"]),
            "extend": sum(1 for r in rows if r["action"] == "update"),
            "skip": sum(1 for r in rows if r["action"] == "skip"),
            "error": sum(1 for r in rows if r["action"] == "error"),
            "new_groups": sorted({g for r in rows if r["action"] in ("create", "update") for g in r["new_groups"]})}


# --- Zwischenablage zwischen Vorschau und Übernahme --------------------------------

def _dir() -> Path:
    path = settings.data_dir / "imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stash(rows: list[dict]) -> str:
    """Speichert die geprüften Zeilen kurz auf dem Server (enthält Passwörter, daher nicht im Cookie)."""
    for old in _dir().glob("*.json"):  # Reste abgebrochener Importe (älter als eine Stunde) aufräumen
        try:
            if time.time() - old.stat().st_mtime > 3600:
                old.unlink()
        except OSError:
            pass
    token = secrets.token_hex(16)
    path = _dir() / f"{token}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    return token


def unstash(token: str, remove: bool = False) -> list[dict] | None:
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        return None
    path = _dir() / f"{token}.json"
    try:
        if time.time() - path.stat().st_mtime > 3600:
            path.unlink(missing_ok=True)
            return None
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if remove:
        path.unlink(missing_ok=True)
    return rows


def apply(db, rows: list[dict], force_change: bool) -> tuple[list[User], list[User], int]:
    """Legt Konten und Gruppen an. Gibt (neue Konten ohne Passwort, alle neuen Konten, ergänzte Mitgliedschaften)."""
    groups = {g.name.lower(): g for g in db.scalars(select(Group))}

    def group(name: str) -> Group:
        g = groups.get(name.lower())
        if g is None:
            g = Group(name=name)
            db.add(g)
            groups[name.lower()] = g
        return g

    without_password, created, added = [], [], 0
    for row in rows:
        if row["action"] == "create":
            if db.scalar(select(User).where(func.lower(User.email) == row["email"])):
                continue  # inzwischen anderweitig angelegt
            has_pw = bool(row["password"])
            user = User(email=row["email"], name=row["name"], is_admin=row["admin"], permissions=row["permissions"],
                        password_hash=hash_password(row["password"] if has_pw else secrets.token_urlsafe(32)),
                        password_set=has_pw, must_change_password=has_pw and force_change)
            db.add(user)
            user.groups = [group(n) for n in row["groups"]]
            created.append(user)
            if not has_pw:
                without_password.append(user)
        elif row["action"] == "update":
            user = db.scalar(select(User).where(func.lower(User.email) == row["email"]))
            if user is None:
                continue
            for name in row["groups"]:
                g = group(name)
                if g not in user.groups:
                    user.groups.append(g)
                    added += 1
    db.flush()
    return without_password, created, added
