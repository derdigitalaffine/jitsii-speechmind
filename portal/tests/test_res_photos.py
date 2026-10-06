"""Fotos von Ressourcen: verkleinern, EXIF/GPS entfernen, Vorschaubild, Reihenfolge, Titelbild, Bildunterschrift."""

import io

from PIL import Image

from app.db import Resource, ResourcePhoto, SessionLocal
from app.routes_resources import files_dir

from conftest import client, csrf_of, login
from test_resources import ADMIN, make_resource, module_on, slug_of  # noqa: F401  (Fixture)

JSON = {"Accept": "application/json"}


def _jpeg(w=3000, h=2000, gps=True) -> bytes:
    img = Image.new("RGB", (w, h), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Kamera AG"                  # Hersteller
    if gps:
        exif[0x8825] = {1: "N", 2: (49.0, 30.0, 0.0), 3: "E", 4: (7.0, 46.0, 0.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def _editor(rid):
    c = login(*ADMIN)
    page = c.get(f"/resources/{rid}/edit")
    assert page.status_code == 200 and 'id="res-photos"' in page.text
    return c, csrf_of(page.text)


def test_upload_scales_strips_exif_and_makes_thumb():
    rid = make_resource("Fotohalle")
    c, token = _editor(rid)
    png = io.BytesIO()
    Image.new("RGBA", (800, 600), (0, 0, 255, 128)).save(png, "PNG")
    r = c.post(f"/resources/{rid}/photos", data={"csrf": token}, headers=JSON,
               files=[("photos", ("urlaub.jpg", _jpeg(), "image/jpeg")), ("photos", ("plan.png", png.getvalue(), "image/png")),
                      ("photos", ("kaputt.jpg", b"\xff\xd8\xff kein Bild", "image/jpeg"))])
    data = r.json()
    assert r.status_code == 200 and data["added"] == 2 and len(data["skipped"]) == 1 and len(data["photos"]) == 2
    with SessionLocal() as db:
        photos = db.get(Resource, rid).photos
        folder = files_dir(rid)
        big = Image.open(folder / photos[0].file)
        assert big.format == "JPEG" and max(big.size) == 1600 and big.size == (1600, 1067)
        assert not big.getexif() and "exif" not in big.info
        thumb = Image.open(folder / photos[0].thumb)
        assert max(thumb.size) == 480
        assert Image.open(folder / photos[1].file).mode == "RGB"   # Transparenz auf Weiß
    slug = slug_of(rid)
    pub = client()
    assert pub.get(f"/r/{slug}/photo/{photos[0].id}?s=thumb").content == (folder / photos[0].thumb).read_bytes()
    assert pub.get(f"/r/{slug}/photo/{photos[0].id}").content == (folder / photos[0].file).read_bytes()


def test_order_cover_caption_delete():
    rid = make_resource("Fotohalle 2")
    c, token = _editor(rid)
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        r = c.post(f"/resources/{rid}/photos", data={"csrf": token}, headers=JSON,
                   files=[("photos", (name, _jpeg(400, 300, gps=False), "image/jpeg"))])
    ids = [p["id"] for p in r.json()["photos"]]
    assert len(ids) == 3
    r = c.post(f"/resources/{rid}/photos/order", data={"csrf": token, "ids": f"{ids[2]},{ids[0]},{ids[1]}"}, headers=JSON)
    assert [p["id"] for p in r.json()["photos"]] == [ids[2], ids[0], ids[1]]
    r = c.post(f"/resources/{rid}/photos/{ids[0]}/caption", data={"csrf": token, "caption": "  Saal  mit <Bühne> "}, headers=JSON)
    assert next(p for p in r.json()["photos"] if p["id"] == ids[0])["caption"] == "Saal mit <Bühne>"
    page = client().get(f"/r/{slug_of(rid)}")
    assert "Saal mit &lt;Bühne&gt;" in page.text and f"/photo/{ids[2]}\"" in page.text   # Titelbild in voller Größe
    r = c.post(f"/resources/{rid}/photos/{ids[2]}/delete", data={"csrf": token}, headers=JSON)
    assert [p["id"] for p in r.json()["photos"]] == [ids[0], ids[1]]
    with SessionLocal() as db:
        assert [p.position for p in db.get(Resource, rid).photos] == [0, 1]
    # fremdes Foto: nicht änderbar
    other = make_resource("Fotohalle 3")
    assert c.post(f"/resources/{other}/photos/{ids[0]}/caption", data={"csrf": token, "caption": "x"}).status_code == 404


def test_thumb_for_old_photo_is_created_on_demand():
    rid = make_resource("Fotohalle alt")
    folder = files_dir(rid)
    folder.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900)).save(buf, "PNG")
    (folder / "alt.png").write_bytes(buf.getvalue())
    with SessionLocal() as db:
        db.add(ResourcePhoto(resource_id=rid, file="alt.png", name="alt.png"))
        db.commit()
        pid = db.get(Resource, rid).photos[0].id
    r = client().get(f"/r/{slug_of(rid)}/photo/{pid}?s=thumb")
    assert r.status_code == 200 and max(Image.open(io.BytesIO(r.content)).size) == 480 and len(r.content) < len(buf.getvalue())
    with SessionLocal() as db:
        assert db.get(ResourcePhoto, pid).thumb == "alt-t.jpg"
