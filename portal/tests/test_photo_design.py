"""Fotogröße der Räume & Plätze im Menü Design einstellbar."""

from app import branding

from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def test_photo_sizes_saved_and_applied():
    c = login(*ADMIN)
    page = c.get("/admin/design")
    assert page.status_code == 200 and 'name="ui_gallery_h"' in page.text
    r = c.post("/admin/design", data={"csrf": csrf_of(page.text), "ui_gallery_h": "240", "ui_gallery_h_mobile": "9999",
                                      "ui_thumb_ratio": "3 / 1", "ui_photo_fit": "contain", "ui_navbar": "dark",
                                      "ui_theme": "auto", "ui_radius": "0.375rem", "ui_logo_height": "32"})
    assert r.status_code == 303
    branding.invalidate()
    css = client().get("/login").text
    assert "--res-gallery-h: 240px" in css and "--res-gallery-h-sm: 480px" in css
    assert "--res-thumb-ratio: 3 / 1" in css and "--res-photo-fit: contain" in css
    assert branding.photo_sizes({"ui_gallery_h": "abc", "ui_thumb_ratio": "x"}) == {
        "gallery": 360, "gallery_mobile": 240, "ratio": "16 / 9", "fit": "cover"}
    settings(ui_gallery_h="360", ui_gallery_h_mobile="240", ui_thumb_ratio="16 / 9", ui_photo_fit="cover")
    branding.invalidate()
