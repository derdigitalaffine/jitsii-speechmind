"""E-Mails im Erscheinungsbild der Organisation (HTML-Rahmen mit Farbe, Logo, Fußzeile)."""

import io

from PIL import Image

from app import branding, notify

from conftest import login

ADMIN = ("admin@example.org", "admin-passwort-123")
CFG = {"mail_from": "portal@example.org", "smtp_host": "smtp.example.org"}


def _logo() -> str:
    branding.BRAND_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (120, 40), (10, 80, 160)).save(buf, "PNG")
    (branding.BRAND_DIR / "logo-test.png").write_bytes(buf.getvalue())
    return "logo-test.png"


def test_framed_mail_with_inline_logo():
    cfg = {**CFG, "ui_custom": "1", "ui_primary": "#16a34a", "ui_logo": _logo(), "ui_brand_name": "VG Musterdorf",
           "ui_footer_text": "Verbandsgemeinde Musterdorf, Rathausplatz 1", "ui_imprint_url": "/impressum"}
    msg = notify._build(cfg, "a@example.org", "Betreff", "Hallo,\n\nsiehe https://portal.example.org/x\n\nGruß")
    html_part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    html = html_part.get_content()
    assert "background:#16a34a" in html and "VG Musterdorf" in html and 'src="cid:logo@portal"' in html
    assert "Rathausplatz 1" in html and "https://portal.example.org/impressum" in html
    assert any(p.get_content_type() == "image/png" and p["Content-ID"] == "<logo@portal>" for p in msg.walk())
    plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain").get_content()
    assert plain.startswith("Hallo,") and "<" not in plain


def test_plain_when_switched_off_and_preview():
    msg = notify._build({**CFG, "ui_mail_frame": "0"}, "a@example.org", "x", "Text")
    html = next(p for p in msg.walk() if p.get_content_type() == "text/html").get_content()
    assert "<table" not in html and "<p" in html
    c = login(*ADMIN)
    r = c.get("/admin/design/mail-vorschau")
    assert r.status_code == 200 and "<table" in r.text and "img-src data:" in r.headers["content-security-policy"]
