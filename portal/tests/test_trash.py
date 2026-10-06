"""Löschen & Papierkorb: Kaskade sichern, Dateien verschieben, Wiederherstellen (inkl. gelöster Verweise),
Bereich leeren mit Vorschau und Bestätigungswort, Ablauf nach 30 Tagen, Protokoll."""

from datetime import timedelta

from sqlalchemy import select

from app import trash
from app.db import DeletionLog, Payment, Resource, ResourceBooking, ResourcePhoto, SessionLocal, TrashItem, utcnow
from app.routes_resources import files_dir

from conftest import client, csrf_of, login
from test_resources import ADMIN, _staff_booking, day, make_resource, module_on  # noqa: F401


def test_delete_resource_with_bookings_and_restore():
    rid = make_resource("Papierkorb-Halle", units="day", mode="instant", price_day=5000)
    bid = _staff_booking(rid, day(5))
    folder = files_dir(rid)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "foto.jpg").write_bytes(b"jpg")
    with SessionLocal() as db:
        db.add(ResourcePhoto(resource_id=rid, file="foto.jpg"))
        db.commit()
    c = login(*ADMIN)
    page = c.get("/admin/loeschen?kind=resource&q=Papierkorb-Halle")
    assert page.status_code == 200 and "Papierkorb-Halle" in page.text
    r = c.post("/admin/loeschen/eintrag", data={"csrf": csrf_of(page.text), "kind": "resource", "obj_id": str(rid)})
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Resource, rid) is None and db.get(ResourceBooking, bid) is None
        item = db.scalar(select(TrashItem).where(TrashItem.row_id == rid, TrashItem.kind == "resource"))
        assert item and not folder.exists() and (trash.trash_dir() / str(item.id) / "0" / "foto.jpg").exists()
        item_id = item.id
    page = c.get("/admin/loeschen")
    assert "Papierkorb-Halle" in page.text
    c.post(f"/admin/loeschen/papierkorb/{item_id}", data={"csrf": csrf_of(page.text), "action": "restore"})
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        assert res.name == "Papierkorb-Halle" and db.get(ResourceBooking, bid) is not None and len(res.photos) == 1
        assert (folder / "foto.jpg").read_bytes() == b"jpg" and db.get(TrashItem, item_id) is None
        actions = [lg.action for lg in db.scalars(select(DeletionLog).order_by(DeletionLog.id))]
        assert actions[-2:] == ["delete", "restore"]


def test_set_null_reference_restored():
    rid = make_resource("Papierkorb-Zahlung", units="day", mode="instant", price_day=5000)
    bid = _staff_booking(rid, day(6))
    with SessionLocal() as db:
        pid = db.get(ResourceBooking, bid).payment_id
        assert pid
        item = trash.delete_one(db, "payment", pid, "Test")
        db.commit()
        assert db.get(ResourceBooking, bid).payment_id is None
        assert trash.restore(db, item, "Test") is None
        db.commit()
        assert db.get(ResourceBooking, bid).payment_id == pid and db.get(Payment, pid) is not None


def test_bulk_needs_condition_preview_and_word():
    rid = make_resource("Papierkorb-Alt", units="day", mode="instant", price_day=5000)
    ids = [_staff_booking(rid, day(n)) for n in (3, 4)]
    with SessionLocal() as db:
        for i in ids:
            b = db.get(ResourceBooking, i)
            b.status = "cancelled"
            b.starts_at, b.ends_at = utcnow() - timedelta(days=400), utcnow() - timedelta(days=399)
        db.commit()
    c = login(*ADMIN)
    cutoff = (utcnow() - timedelta(days=200)).date().isoformat()
    page = c.get(f"/admin/loeschen?kind=booking&before={cutoff}&status=cancelled")
    with SessionLocal() as db:
        n = trash.bulk_count(db, "booking", (utcnow() - timedelta(days=200)).date(), "cancelled")
    assert n >= 2 and f"{n} Einträge würden" in page.text
    token = csrf_of(page.text)
    base = {"csrf": token, "kind": "booking", "before": cutoff, "status": "cancelled", "expected": str(n)}
    c.post("/admin/loeschen/bereich", data={**base, "confirm": "ja"})
    with SessionLocal() as db:
        assert db.get(ResourceBooking, ids[0]) is not None           # falsches Wort → nichts passiert
    c.post("/admin/loeschen/bereich", data={**base, "expected": str(n + 1), "confirm": "LÖSCHEN"})
    with SessionLocal() as db:
        assert db.get(ResourceBooking, ids[0]) is not None           # Anzahl geändert → nichts passiert
    c.post("/admin/loeschen/bereich", data={**base, "confirm": "löschen"})
    with SessionLocal() as db:
        assert all(db.get(ResourceBooking, i) is None for i in ids)
        items = db.scalars(select(TrashItem).where(TrashItem.kind == "booking", TrashItem.row_id.in_(ids))).all()
        assert len(items) == 2 and items[0].batch and items[0].batch == items[1].batch
        assert db.scalar(select(DeletionLog).where(DeletionLog.action == "bulk").order_by(DeletionLog.id.desc())).count >= 2
        assert trash.bulk_count(db, "booking", None, "") == 0        # ohne Bedingung: nie alles
        for it in items:
            it.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert trash.purge_expired() >= 2
    with SessionLocal() as db:
        assert not db.scalars(select(TrashItem).where(TrashItem.row_id.in_(ids), TrashItem.kind == "booking")).all()


def test_only_admin():
    assert client().get("/admin/loeschen").status_code in (302, 303, 401, 403)
