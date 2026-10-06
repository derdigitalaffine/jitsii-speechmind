"""Kartenproxy: begrenzte Abrufe beim Anbieter, damit Herauszoomen den Server nicht blockiert."""

import threading
import time

import httpx
from sqlalchemy import select

from app import maps
from app.db import MapLayer, SessionLocal

from conftest import client


def _layer(**kw) -> int:
    with SessionLocal() as db:
        layer = MapLayer(name="Test-Kacheln", kind="xyz", role="overlay", url="https://tiles.example.org/{z}/{x}/{y}.png",
                         proxy=True, public=True, enabled=True, cache_hours=1, **kw)
        db.add(layer)
        db.commit()
        return layer.id


def test_busy_returns_empty_tile_fast(monkeypatch):
    lid = _layer()
    release = threading.Event()
    calls = []

    def slow(url, **kw):
        calls.append(url)
        release.wait(5)
        return 200, b"\x89PNG", "image/png"

    monkeypatch.setattr(maps, "fetch", slow)
    monkeypatch.setattr(maps, "MAX_QUEUE", 1)
    with client() as c:   # ein Ereignis-Loop für alle Anfragen wie im Betrieb
        holder = threading.Thread(target=lambda: c.get(f"/map/l/{lid}/5/1/1"))
        holder.start()
        for _ in range(100):
            if calls:
                break
            time.sleep(0.01)
        started = time.monotonic()
        r = c.get(f"/map/l/{lid}/5/2/2")
        assert time.monotonic() - started < 1
        assert r.status_code == 200 and r.content == maps.TRANSPARENT_PNG and r.headers["cache-control"] == "no-store"
        # andere Seiten bleiben erreichbar, während der Kartendienst hängt
        started = time.monotonic()
        assert c.get("/login").status_code == 200
        assert time.monotonic() - started < 1
        release.set()
        holder.join(5)
    assert len(calls) == 1


def test_stale_queue_entries_are_skipped(monkeypatch):
    monkeypatch.setattr(maps, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht abrufen")))
    try:
        maps._fetch_if_fresh(time.monotonic() - maps.QUEUE_WAIT - 1, "https://x.example.org/", False, maps.TIMEOUT)
    except maps.Busy:
        pass
    else:
        raise AssertionError("Busy erwartet")


def test_failures_are_remembered(monkeypatch):
    lid = _layer()
    calls = []

    def broken(url, **kw):
        calls.append(url)
        raise httpx.ConnectTimeout("zu langsam")

    monkeypatch.setattr(maps, "fetch", broken)
    c = client()
    for _ in range(3):
        r = c.get(f"/map/l/{lid}/6/3/3")
        assert r.status_code == 200 and r.content == maps.TRANSPARENT_PNG
    assert len(calls) == 1


def test_outside_zoom_range_not_fetched(monkeypatch):
    lid = _layer(min_zoom=8, max_zoom=12)
    monkeypatch.setattr(maps, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht abrufen")))
    c = client()
    assert c.get(f"/map/l/{lid}/3/1/1").content == maps.TRANSPARENT_PNG
    assert c.get(f"/map/l/{lid}/14/1/1").content == maps.TRANSPARENT_PNG


def test_same_tile_fetched_once(monkeypatch):
    lid = _layer()
    calls = []

    def slow(url, **kw):
        calls.append(url)
        time.sleep(0.3)
        return 200, b"\x89PNG-tile", "image/png"

    monkeypatch.setattr(maps, "fetch", slow)
    results, errors = [], []
    with client() as c:
        def get():
            try:
                results.append(c.get(f"/map/l/{lid}/7/4/4").content)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
    assert not errors, errors
    assert len(calls) == 1 and results == [b"\x89PNG-tile"] * 4


def test_wfs_large_extent_is_empty(monkeypatch):
    with SessionLocal() as db:
        layer = MapLayer(name="Objekte", kind="wfs", role="overlay", url="https://wfs.example.org/wfs", layers="a:b",
                         proxy=True, public=True, enabled=True)
        db.add(layer)
        db.commit()
        lid = layer.id
    monkeypatch.setattr(maps, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht abrufen")))
    r = client().get(f"/map/l/{lid}/wfs", params={"bbox": "0,5000000,2000000,7000000"})
    assert r.status_code == 200 and r.json()["features"] == [] and r.json()["tooLarge"]


def test_prune_runs_outside_request(monkeypatch):
    ran = threading.Event()
    monkeypatch.setattr(maps, "prune", lambda limit: ran.set() or 0)
    monkeypatch.setattr(maps, "_last_prune", {"at": 0.0})
    maps.cache_put("t-" + "0" * 64, b"x", "image/png", 1)
    assert ran.wait(2)
    with SessionLocal() as db:
        assert db.scalar(select(MapLayer.id).limit(1))


def test_empty_tile_is_valid_png():
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(maps.TRANSPARENT_PNG))
    img.load()
    assert img.size == (1, 1) and img.getpixel((0, 0))[3] == 0
