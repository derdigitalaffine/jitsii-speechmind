"""QR-Codes zu öffentlichen Links: nur eigene Adressen, Formate, Aushang, Knöpfe auf den Seiten."""

from conftest import client, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def test_qr_link_only_own_hosts_and_formats():
    c = login(*ADMIN)
    r = c.get("/qr/link.svg", params={"u": "https://portal.example.org/r"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    r = c.get("/qr/link.png", params={"u": "/antraege", "download": "1", "name": "qr-anträge"})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG" and 'filename="qr-antrge.png"' in r.headers["content-disposition"]
    assert c.get("/qr/link.jpg", params={"u": "/r", "size": "4"}).content[:3] == b"\xff\xd8\xff"
    assert c.get("/qr/link.svg", params={"u": "https://evil.example.com/x"}).status_code == 400
    assert c.get("/qr/link.svg", params={"u": "//evil.example.com/x"}).status_code == 400
    assert c.get("/qr/link.svg", params={"u": "javascript:alert(1)"}).status_code == 400
    # eigene Modul-Domain ist erlaubt
    settings(domain_resources="raeume.example.org")
    try:
        from app import links
        links.invalidate()
        assert c.get("/qr/link.svg", params={"u": "https://raeume.example.org/r"}).status_code == 200
    finally:
        settings(domain_resources="")
        links.invalidate()
    # nur angemeldet
    assert client().get("/qr/link.svg", params={"u": "/r"}).status_code in (302, 303, 401, 403)


def test_poster_and_buttons():
    settings(module_resources="1", module_applications="1", module_forms="1")
    c = login(*ADMIN)
    page = c.get("/qr/aushang", params={"u": "/r", "title": "Räume buchen", "text": "Grillhütte & Saal"})
    assert page.status_code == 200 and "Räume buchen" in page.text and "Grillhütte &amp; Saal" in page.text
    assert "data:image/svg+xml;base64," in page.text and "portal.example.org/r" in page.text
    res = c.get("/resources")
    assert 'class="btn btn-outline-secondary js-qr-open" data-qr-link="https://portal.example.org/r"' in res.text
    assert 'id="qr-modal"' in res.text and 'id="qrm-size"' in res.text
    assert 'data-qr-link="https://portal.example.org/antraege"' in c.get("/forms/applications").text
