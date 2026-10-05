"""Update-Hinweis: Versionsvergleich, Abruf, Anzeige nur für Admins."""

import httpx

from app import updates

from conftest import login, settings


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_version_compare_and_hint(monkeypatch):
    assert updates.parse("2026.10.1") > updates.parse("2026.10.0") > updates.parse("2026.9.9")
    settings(update_check="1", update_checked_at="", update_latest="")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp("9999.1.0\n"))
    assert updates.check(force=True) == "9999.1.0"
    admin = login("admin@example.org", "admin-passwort-123")
    assert "9999.1.0" in admin.get("/").text
    assert "9999.1.0" in admin.get("/about").text
    settings(update_check="0")
    assert "9999.1.0" not in admin.get("/").text
    assert updates.check(force=True) is None
    settings(update_check="1", update_latest="")


def test_bad_answer_ignored(monkeypatch):
    settings(update_check="1", update_latest="")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp("<html>nope</html>"))
    assert updates.check(force=True) is None
