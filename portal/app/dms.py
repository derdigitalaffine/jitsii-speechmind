"""Ablage (DMS): Aktenplan mit Lese-/Schreibrechten, Index der Online-Anträge, manuelle Ablage, Recherche,
gespeicherte Suchen und Löschfristen.

Jeder Online-Antrag erscheint ab Eingang in der Ablage (laufend, mit Status) – im Bereich seines Prozesses, sonst
im Bereich seines Formulars, sonst unter „Nicht einsortiert“. Von Hand verschobene Einträge bleiben, wo sie sind.
Jeder Eintrag ist einer Person (Bürger:in/Antragsteller:in) zugeordnet.
Beim Abschluss legt das Portal einen unveränderlichen Abschlussstand ab: Antrags-PDF mit Anlagen und alle
erzeugten Dokumente (Bescheide) als Kopie mit SHA-256-Prüfsumme. Die Aufbewahrungsfrist beginnt mit dem Ende
des Abschlussjahres.
"""

import hashlib
import mimetypes
import re
import secrets
import shutil
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from . import applications as apps, forms as fm
from .config import settings
from .db import (
    ApplicationEvent, DmsAccess, DmsArea, DmsFile, DmsLog, DmsRecord, FormResponse, GroupMember, Person, SessionLocal,
    User, get_settings, to_local, utcnow,
)

READ, WRITE = 1, 2
LEVELS = {READ: "lesen", WRITE: "lesen und ablegen"}


def files_dir(record_id: int):
    return settings.data_dir / "dms" / str(record_id)


# --- Aktenplan und Rechte -----------------------------------------------------------------

def areas(db) -> list[DmsArea]:
    return db.scalars(select(DmsArea).order_by(DmsArea.position, DmsArea.code, DmsArea.name)).all()


def tree(db) -> list[tuple[DmsArea, int]]:
    """Bereiche in Baumreihenfolge mit Einrückungstiefe."""
    all_areas = areas(db)
    children: dict[int | None, list[DmsArea]] = {}
    for a in all_areas:
        children.setdefault(a.parent_id, []).append(a)
    out: list[tuple[DmsArea, int]] = []

    def walk(parent, depth):
        for a in children.get(parent, []):
            out.append((a, depth))
            if depth < 12:
                walk(a.id, depth + 1)
    walk(None, 0)
    return out


def path(area: DmsArea | None, by_id: dict[int, DmsArea]) -> list[DmsArea]:
    chain, seen = [], set()
    while area is not None and area.id not in seen:
        chain.insert(0, area)
        seen.add(area.id)
        area = by_id.get(area.parent_id) if area.parent_id else None
    return chain


def label(area: DmsArea, by_id: dict[int, DmsArea]) -> str:
    return " › ".join(f"{a.code} {a.name}".strip() for a in path(area, by_id))


UNSORTED = "unsorted"


def unsorted(db) -> DmsArea:
    """Bereich „Nicht einsortiert“ (wird bei Bedarf angelegt, lässt sich nicht löschen)."""
    area = db.scalar(select(DmsArea).where(DmsArea.system_key == UNSORTED))
    if area is None:
        area = DmsArea(name="Nicht einsortiert", code="", system_key=UNSORTED, position=10_000,
                       description="Vorgänge, deren Prozess und Formular keinen Ablagebereich festlegen. "
                                   "Von hier aus in den passenden Bereich verschieben.")
        db.add(area)
        db.flush()
    return area


def target_area_id(db, resp: FormResponse) -> int:
    """Ablagebereich eines Antrags: Prozess → Formular → „Nicht einsortiert“."""
    process = resp.process_version.process if resp.process_version is not None else resp.form.process
    for aid in ((process.dms_area_id if process is not None else None), resp.form.dms_area_id):
        if aid and db.get(DmsArea, aid) is not None:
            return aid
    return unsorted(db).id


def levels(db, user: User) -> dict[int, int]:
    """Bereich → Rechtestufe der Person (vererbt an Unterbereiche; Admins: alles schreibend).
    Wer den Aktenplan verwaltet, darf „Nicht einsortiert“ bearbeiten, um Vorgänge einzusortieren."""
    all_areas = areas(db)
    if user.is_admin:
        return {a.id: WRITE for a in all_areas}
    groups = set(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user.id)))
    own: dict[int, int] = {}
    for acc in db.scalars(select(DmsAccess).where(or_(DmsAccess.user_id == user.id,
                                                      DmsAccess.group_id.in_(groups or [-1])))):
        own[acc.area_id] = max(own.get(acc.area_id, 0), acc.level)
    if user.can("dms_admin"):
        for a in all_areas:
            if a.system_key == UNSORTED:
                own[a.id] = WRITE
    by_id = {a.id: a for a in all_areas}
    result = {}
    for a in all_areas:
        lvl = max((own.get(x.id, 0) for x in path(a, by_id)), default=0)
        if lvl:
            result[a.id] = lvl
    return result


def can_use(db, user: User) -> bool:
    return user.is_admin or user.can("dms_admin") or bool(levels(db, user))


def subtree_ids(db, area_id: int) -> set[int]:
    ids, frontier = {area_id}, [area_id]
    all_areas = areas(db)
    while frontier:
        nxt = [a.id for a in all_areas if a.parent_id in frontier and a.id not in ids]
        ids.update(nxt)
        frontier = nxt
    return ids


def retention_years(area: DmsArea, by_id: dict[int, DmsArea]) -> int:
    """Frist des Bereichs oder des nächsten übergeordneten Bereichs mit Frist."""
    for a in reversed(path(area, by_id)):
        if a.retention_years:
            return a.retention_years
    return 0


def retention_date(closed: datetime | None, years: int) -> datetime | None:
    if not closed or not years:
        return None
    from datetime import timezone
    from .db import LOCAL_TZ
    local = to_local(closed)
    end = datetime(local.year + years, 12, 31, 23, 59, tzinfo=LOCAL_TZ)   # Ende des Abschlussjahres + Frist
    return end.astimezone(timezone.utc).replace(tzinfo=None)


# --- Index der Anträge -----------------------------------------------------------------------

def _place(resp: FormResponse, items: list[dict]) -> dict:
    """Ort des Antrags: erstes Adressfeld, sonst Mittelpunkt einer Kartenangabe."""
    answers = resp.answers
    for q in fm.questions(items):
        if q["type"] == "address" and isinstance(answers.get(q["id"]), dict):
            a = answers[q["id"]]
            return {"street": " ".join(x for x in (a.get("street"), a.get("house_no")) if x), "zip": a.get("zip", ""),
                    "city": a.get("city", ""), "district": a.get("district", ""), "lat": a.get("lat"), "lon": a.get("lon")}
    for q in fm.questions(items):
        if q["type"] == "geo":
            c = fm.geo_center(answers.get(q["id"]))
            if c:
                return {"street": "", "zip": "", "city": "", "district": "", "lat": c[1], "lon": c[0]}
    return {}


def _fulltext(resp: FormResponse, items: list[dict]) -> str:
    from . import workflow
    parts = [resp.ref_no or "", resp.name, resp.email, resp.form.title]
    answers = workflow.current_answers(resp)
    for q in fm.questions(items):
        parts.append(fm.display(q, answers.get(q["id"])))
    for req in resp.requests:
        parts.append(req.title)
        for item in req.items:
            parts.append(fm.display(item, req.answers.get(item["id"])))
    for ev in resp.events:
        parts.append(ev.text)
    parts += [f"{k} {v}" for k, v in resp.fields.items()]
    parts += [d.name for d in resp.documents]
    return " ".join(p for p in parts if p).lower()[:200000]


def enabled(db) -> bool:
    return get_settings(db).get("module_dms", "1") == "1"


def sync(db, resp: FormResponse) -> DmsRecord | None:
    """Ablage-Eintrag eines Online-Antrags anlegen bzw. aktualisieren – ab Eingang, auch laufende Vorgänge."""
    form = resp.form
    record = db.scalar(select(DmsRecord).where(DmsRecord.response_id == resp.id))
    if record is None:
        if not resp.ref_no or not enabled(db):
            return None
        record = DmsRecord(area_id=target_area_id(db, resp), response_id=resp.id, kind="antrag",
                           received_at=resp.created_at, created_by="Online-Antrag")
        db.add(record)
    elif not record.area_manual:
        target = target_area_id(db, resp)
        if target != record.area_id:
            old = record.area.name if record.area else "?"
            record.area_id = target
            db.flush()
            db.refresh(record, ["area"])
            log(db, None, "einsortiert", f"{record.ref_no} automatisch von „{old}“ nach „{record.area.name}“ (Prozess/Formular)")
    items = fm.schema(form)
    record.title = form.title
    record.ref_no = resp.ref_no or ""
    record.form_title = form.title
    record.applicant = resp.name or ""
    record.applicant_email = apps.applicant_email(form, resp)
    record.status = resp.status
    record.assignee = apps._common(form, resp)["zustaendig"]
    place = _place(resp, items)
    for key in ("street", "zip", "city", "district"):
        setattr(record, key, str(place.get(key) or "")[:200])
    record.lat, record.lon = place.get("lat"), place.get("lon")
    if record.person_id is None:
        record.person = match_person(db, record.applicant, record.applicant_email, record.street, record.zip, record.city,
                                     phone=_phone(resp, items))
    record.text = _fulltext(resp, items) + " " + " ".join(f.name.lower() for f in record.files)
    was_closed = record.closed_at
    record.closed_at = resp.closed_at
    if resp.closed_at and not was_closed:
        db.flush()
        archive(db, record, resp)
    if record.closed_at:
        by_id = {a.id: a for a in areas(db)}
        area = by_id.get(record.area_id)
        record.retention_until = retention_date(record.closed_at, retention_years(area, by_id)) if area else None
    else:
        record.retention_until = None
    record.updated_at = utcnow()
    return record


def _store(record: DmsRecord, name: str, data: bytes, kind: str, by: str, note: str = "", mime: str = "") -> DmsFile:
    target = files_dir(record.id)
    target.mkdir(parents=True, exist_ok=True)
    ext = re.sub(r"[^a-z0-9.]", "", ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else "")[:11]
    stored = secrets.token_hex(10) + ext
    (target / stored).write_bytes(data)
    f = DmsFile(name=name[:255], file=stored, size=len(data), kind=kind, uploaded_by=by[:255], note=note[:500],
                mime=(mime or mimetypes.guess_type(name)[0] or "application/octet-stream")[:100],
                sha256=hashlib.sha256(data).hexdigest())
    record.files.append(f)
    return f


def archive(db, record: DmsRecord, resp: FormResponse) -> None:
    """Abschlussstand ablegen: Antrags-PDF mit Anlagen und Kopien aller erzeugten Dokumente."""
    from . import workflow
    try:
        data = apps.pdf(resp.form, resp)
        _store(record, f"{resp.ref_no} Antrag (Abschlussstand).pdf", data, "abschluss", "Ablage",
               f"Stand bei Abschluss am {to_local(resp.closed_at).strftime('%d.%m.%Y %H:%M')} – {apps.status_label(resp.status)}",
               "application/pdf")
    except Exception:  # noqa: BLE001  (Ablage darf den Abschluss nicht verhindern)
        pass
    for doc in resp.documents:
        src = workflow.documents_dir(resp) / doc.file
        if src.is_file():
            _store(record, f"{doc.name}.pdf", src.read_bytes(), "dokument", "Ablage", "erzeugt im Vorgang", "application/pdf")


def store_request(db, resp: FormResponse, req) -> None:
    """Nachgereichte Angaben sofort als eigenes PDF in die Ablage legen (das Antrags-PDF enthält sie ohnehin)."""
    from . import workflow
    record = sync(db, resp)
    if record is None:
        return
    sec = next((x for x in apps.request_sections(resp.form, resp) if x["id"] == req.id), None)
    if sec is None:
        return
    body = (f"Nachforderung vom {to_local(sec['requested_at']).strftime('%d.%m.%Y')}" + (f": {sec['message']}" if sec["message"] else "")
            + "\n\n" + "\n\n".join(f"{q}:\n{v or '–'}" + (f"\n({note})" if note else "") for q, v, note in sec["rows"]))
    try:
        data = workflow.document_pdf(resp, f"Nachgereichte Angaben – {sec['title']}", body)
    except Exception:  # noqa: BLE001  (Ablage darf die Antwort nicht verhindern)
        return
    when = to_local(sec["answered_at"]).strftime("%d.%m.%Y %H:%M")
    _store(record, f"{resp.ref_no} Nachreichung {sec['title']}.pdf"[:200], data, "nachreichung", "Ablage",
           f"nachgereicht am {when}", "application/pdf")


def reconcile() -> int:
    """Hintergrunddienst: Einträge mit neueren Ereignissen im Vorgang aktualisieren (z. B. Nachgereichtes)."""
    n = 0
    with SessionLocal() as db:
        rows = db.execute(select(DmsRecord, ApplicationEvent.at).join(FormResponse, FormResponse.id == DmsRecord.response_id)
                          .join(ApplicationEvent, ApplicationEvent.response_id == FormResponse.id)
                          .where(ApplicationEvent.at > DmsRecord.updated_at)).all()
        for record, _at in {r[0].id: r for r in rows}.values():
            if record.response is not None:
                sync(db, record.response)
                n += 1
        if not enabled(db):
            db.commit()
            return n
        # Anträge, die noch fehlen (z. B. aus der Zeit vor der Ablage), aufnehmen
        missing = db.scalars(select(FormResponse).where(FormResponse.ref_no.is_not(None),
                                                        ~FormResponse.id.in_(select(DmsRecord.response_id).where(DmsRecord.response_id.is_not(None))))).all()
        for resp in missing:
            sync(db, resp)
            n += 1
        # Automatisch abgelegte Einträge umsortieren, wenn Prozess oder Formular einen anderen Bereich bekommen haben
        for record in db.scalars(select(DmsRecord).where(DmsRecord.response_id.is_not(None), DmsRecord.area_manual.is_(False))):
            if record.response is not None and target_area_id(db, record.response) != record.area_id:
                sync(db, record.response)
                n += 1
        db.commit()
    return n


# --- Recherche ---------------------------------------------------------------------------------

FILTERS = ("q", "applicant", "ref", "area", "form", "status", "from", "to", "place", "kind", "sort", "person")


def search(db, user: User, f: dict, limit: int = 50, offset: int = 0) -> tuple[list[DmsRecord], int]:
    lv = levels(db, user)
    q = select(DmsRecord)
    if not user.is_admin:
        q = q.where(DmsRecord.area_id.in_(list(lv) or [-1]))
    if f.get("area", "").isdigit():
        q = q.where(DmsRecord.area_id.in_(subtree_ids(db, int(f["area"]))))
    for term in (f.get("q") or "").lower().split()[:8]:
        q = q.where(DmsRecord.text.contains(term))
    if f.get("applicant"):
        like = f"%{f['applicant'].strip()}%"
        q = q.where(or_(DmsRecord.applicant.ilike(like), DmsRecord.applicant_email.ilike(like)))
    if f.get("person", "").isdigit():
        q = q.where(DmsRecord.person_id == int(f["person"]))
    if f.get("ref"):
        q = q.where(DmsRecord.ref_no.ilike(f"%{f['ref'].strip()}%"))
    if f.get("form"):
        q = q.where(DmsRecord.form_title == f["form"])
    if f.get("kind") in ("antrag", "manuell", "buchung"):
        q = q.where(DmsRecord.kind == f["kind"])
    status = f.get("status", "")
    if status == "open":
        q = q.where(DmsRecord.closed_at.is_(None), DmsRecord.kind == "antrag")
    elif status == "closed":
        q = q.where(or_(DmsRecord.closed_at.is_not(None), DmsRecord.kind == "manuell"))
    elif status in apps.STATUSES:
        q = q.where(DmsRecord.status == status)
    if f.get("place"):
        like = f"%{f['place'].strip()}%"
        q = q.where(or_(DmsRecord.zip.ilike(like), DmsRecord.city.ilike(like), DmsRecord.street.ilike(like),
                        DmsRecord.district.ilike(like)))
    for key, op in (("from", "ge"), ("to", "le")):
        try:
            d = datetime.fromisoformat(f.get(key, ""))
        except ValueError:
            continue
        if op == "ge":
            q = q.where(DmsRecord.received_at >= d - timedelta(hours=2))
        else:
            q = q.where(DmsRecord.received_at <= d + timedelta(days=1))
    order = {"old": DmsRecord.received_at.asc(), "ref": DmsRecord.ref_no.asc(), "applicant": DmsRecord.applicant.asc()}
    q = q.order_by(order.get(f.get("sort", ""), DmsRecord.received_at.desc()))
    total = len(db.scalars(q.with_only_columns(DmsRecord.id)).all())
    return db.scalars(q.limit(limit).offset(offset)).all(), total


def record_level(db, user: User, record: DmsRecord) -> int:
    return levels(db, user).get(record.area_id, 0)


def log(db, user: User | None, action: str, text: str) -> None:
    db.add(DmsLog(user_name=user.name if user else "Portal", action=action, text=text[:5000]))


def move_record(db, record: DmsRecord, area: DmsArea, user: User) -> bool:
    """Eintrag in einen anderen Bereich verschieben (bleibt danach dort, auch wenn der Prozess anders ablegt)."""
    if area.id == record.area_id:
        return False
    old = record.area.name if record.area else "?"
    record.area_id, record.area_manual, record.updated_at = area.id, True, utcnow()
    db.flush()
    db.refresh(record, ["area"])
    if record.closed_at:
        by_id = {a.id: a for a in areas(db)}
        record.retention_until = retention_date(record.closed_at, retention_years(area, by_id))
    log(db, user, "verschoben", f"{record.ref_no or '#' + str(record.id)} „{record.title}“ von „{old}“ nach „{area.name}“")
    return True


# --- Personen (Bürger:innen / Antragsteller:innen) ------------------------------------------------

def _phone(resp: FormResponse, items: list[dict]) -> str:
    for q in fm.questions(items):
        if q["type"] == "short" and q.get("subtype") in ("phone", "tel"):
            v = resp.answers.get(q["id"])
            if isinstance(v, str) and v.strip():
                return v.strip()[:60]
    return ""


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def match_person(db, name: str, email: str, street: str = "", zip_code: str = "", city: str = "",
                 phone: str = "") -> Person | None:
    """Person zu einem Vorgang finden oder anlegen: gleiche E-Mail-Adresse, sonst gleicher Name und gleiche PLZ."""
    name, email = " ".join(str(name or "").split())[:255], str(email or "").strip().lower()[:255]
    if not name and not email:
        return None
    person = None
    if email:
        person = db.scalar(select(Person).where(Person.email == email).order_by(Person.id))
    if person is None and name and zip_code:
        for cand in db.scalars(select(Person).where(Person.zip == zip_code[:10])):
            if _norm(cand.name) == _norm(name) and (not cand.email or not email):
                person = cand
                break
    if person is None:
        person = Person(name=name, email=email)
        db.add(person)
    # Fehlende Angaben ergänzen, vorhandene nicht überschreiben (die Verwaltung pflegt sie von Hand)
    for attr, value in (("name", name), ("email", email), ("street", street), ("zip", zip_code), ("city", city),
                        ("phone", phone)):
        if value and not getattr(person, attr):
            setattr(person, attr, str(value)[:255 if attr != "zip" else 10])
    person.updated_at = utcnow()
    db.flush()
    return person


def visible_persons_query(db, user: User):
    """Personen, zu denen die Person mindestens einen lesbaren Eintrag hat (Admins und Aktenplan-Verwaltung: alle)."""
    q = select(Person)
    if user.is_admin or user.can("dms_admin"):
        return q
    readable = list(levels(db, user))
    return q.where(Person.id.in_(select(DmsRecord.person_id).where(DmsRecord.area_id.in_(readable or [-1]))))


def merge_persons(db, keep: Person, drop: Person, user: User) -> int:
    """Doppelte Person zusammenführen: alle Einträge wandern zu keep, fehlende Angaben werden ergänzt."""
    n = 0
    for record in db.scalars(select(DmsRecord).where(DmsRecord.person_id == drop.id)):
        record.person_id = keep.id
        n += 1
    for attr in ("name", "email", "phone", "street", "zip", "city"):
        if not getattr(keep, attr) and getattr(drop, attr):
            setattr(keep, attr, getattr(drop, attr))
    if drop.note:
        keep.note = (keep.note + "\n" + drop.note).strip()
    log(db, user, "zusammengeführt", f"Person #{drop.id} „{drop.name}“ in #{keep.id} „{keep.name}“ ({n} Einträge)")
    db.delete(drop)
    return n


def expired(db) -> list[DmsRecord]:
    return db.scalars(select(DmsRecord).where(DmsRecord.retention_until.is_not(None),
                                              DmsRecord.retention_until < utcnow())
                      .order_by(DmsRecord.retention_until)).all()


def delete_record(db, record: DmsRecord, user: User, reason: str) -> None:
    """Eintrag samt Dateien löschen – bei Anträgen auch den Vorgang mit allen Angaben und Uploads."""
    desc = f"{record.ref_no or '#' + str(record.id)} „{record.title}“ ({record.applicant or 'ohne Name'}), Bereich {record.area.name}"
    resp = record.response
    shutil.rmtree(files_dir(record.id), ignore_errors=True)
    if resp is not None:
        fm.delete_files(resp.form_id, resp.id)
        db.delete(resp)
    db.delete(record)
    log(db, user, "gelöscht", f"{desc} – {reason}")
