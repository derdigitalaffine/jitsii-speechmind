"""Regressionstests zum Security-Audit."""

import ipaddress
import re
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import select

from app import csvsafe, forms as fm, krank, main, maps, notify, proxy
from app.db import Meeting, Notification, SessionLocal, User, get_settings
from app.security import hash_password
from conftest import client, csrf_of, login, settings

ADMIN = ("admin@example.org", "admin-passwort-123")


def _user(email: str, perms: str = "", admin: bool = False) -> int:
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, name=email.split("@")[0], password_hash=hash_password("passwort-123"),
                     permissions=perms, is_admin=admin)
            db.add(u)
        u.permissions, u.is_admin, u.active = perms, admin, True
        db.commit()
        return u.id


# --- Rate-Limit ---------------------------------------------------------------------

def _req(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={"x-forwarded-for": "1.2.3.4"})


def test_client_ip_ignores_forwarded_header_and_groups_ipv6():
    assert main.client_ip(_req("203.0.113.7")) == "203.0.113.7"
    assert main.client_ip(_req("2001:db8:1:2:aaaa::1")) == main.client_ip(_req("2001:db8:1:2:bbbb::2")) == "2001:db8:1:2::/64"
    assert main.client_ip(_req("::ffff:198.51.100.3")) == "198.51.100.3"


def test_rate_limit_not_reset_by_flooding():
    req = _req("198.51.100.9")
    for _ in range(3):
        main.rate_limit(req, "t", limit=3)
    for i in range(main._ATTEMPTS_MAX + 10):   # viele fremde Schlüssel dürfen den Zähler nicht leeren
        main._attempts[f"x:{i}"] = []
    with pytest.raises(main.HTTPException):
        main.rate_limit(req, "t", limit=3)


# --- Rechte, Jitsi, Krankmelder --------------------------------------------------------

def test_user_manager_cannot_grant_permissions_they_lack():
    _user("manager@example.org", "users,video")
    target = _user("kollegin@example.org", "video")
    c = login("manager@example.org", "passwort-123")
    page = c.get("/admin/users")
    c.post(f"/admin/users/{target}", data={"csrf": csrf_of(page.text), "action": "edit", "name": "Kollegin",
                                            "perm": ["video", "forms", "users"]})
    with SessionLocal() as db:
        assert db.get(User, target).perms == {"video", "users"}   # „forms“ hat die Verwaltung selbst nicht
    me = _user("manager@example.org", "users,video")
    c.post(f"/admin/users/{me}", data={"csrf": csrf_of(page.text), "action": "edit", "name": "Ich", "perm": ["users", "dms"]})
    with SessionLocal() as db:
        assert "dms" not in db.get(User, me).perms
    # Konto mit weitergehenden Rechten: kein Zurücksetzen-Link durch die Benutzerverwaltung
    boss = _user("chefin@example.org", "video,forms")
    c.post(f"/admin/users/{boss}", data={"csrf": csrf_of(page.text), "action": "reset_password"})
    with SessionLocal() as db:
        assert not db.scalar(select(Notification).where(Notification.to_addr == "chefin@example.org"))


def test_jitsi_moderator_only_for_host():
    owner = _user("gastgeber@example.org", "video")
    _user("kollege@example.org", "video")
    with SessionLocal() as db:
        db.add(Meeting(owner_id=owner, title="Runde", room="runde-abc123"))
        db.commit()
    c = login("kollege@example.org", "passwort-123")
    r = c.get("/jitsi/auth?room=runde-abc123")
    token = re.search(r"jwt=([^&#]+)", r.headers["location"]).group(1)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["context"]["user"]["moderator"] is False and claims["context"]["features"]["recording"] is False
    c = login("gastgeber@example.org", "passwort-123")
    token = re.search(r"jwt=([^&#]+)", c.get("/jitsi/auth?room=runde-abc123").headers["location"]).group(1)
    assert jwt.decode(token, options={"verify_signature": False})["context"]["user"]["moderator"] is True


def test_krank_ticket_revoked_when_password_changes():
    with SessionLocal() as db:
        krank.set_password(db, "erstes-passwort")
        db.commit()
        ticket = krank.make_ticket(get_settings(db))
        assert krank.ticket_valid(ticket, get_settings(db))
        krank.set_password(db, "zweites-passwort")
        db.commit()
        assert not krank.ticket_valid(ticket, get_settings(db))


def test_secrets_not_in_session_cookie():
    c = login(*ADMIN)
    c.get("/profile/security?setup=totp")
    import base64
    import json
    raw = c.cookies.get("jsm_session").split(".")[0]
    data = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    assert "totp_setup" not in data and "_stash" in data


# --- Eingaben ---------------------------------------------------------------------------

def test_csv_cells_cannot_start_formulas():
    assert csvsafe.cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert csvsafe.cell("@SUM(A1)") == "'@SUM(A1)"
    assert csvsafe.cell("-12,50") == "-12,50" and csvsafe.cell(-3) == -3 and csvsafe.cell("Text") == "Text"


def test_form_pattern_with_catastrophic_backtracking_times_out():
    import time
    from starlette.datastructures import FormData
    items = fm.clean_schema([{"id": "q1", "type": "short", "subtype": "regex", "pattern": "(a|aa)+$", "title": "Code"}])
    start = time.monotonic()
    _answers, errors, _files = fm.validate(items, FormData([("q_q1", "a" * 30 + "x" * 30 + "!")]), {})
    assert time.monotonic() - start < 3 and "q1" in errors


def test_internal_addresses_blocked():
    for ip in ("127.0.0.1", "10.1.2.3", "100.64.0.1", "169.254.169.254", "::1", "::ffff:192.168.0.1", "fd00::1"):
        assert maps._internal(ipaddress.ip_address(ip)), ip
    assert not maps._internal(ipaddress.ip_address("93.184.216.34"))


def test_confirmation_mails_limited_per_address():
    settings(smtp_host="smtp.example.org", mail_from="portal@example.org")
    with SessionLocal() as db:
        results = [notify.enqueue(db, "opfer@example.org", "Betreff", "Text", "form_confirmation", per_hour=5)
                   for _ in range(8)]
        db.commit()
    assert results.count(True) == 5


# --- Header -----------------------------------------------------------------------------

def test_csp_uses_nonce_instead_of_unsafe_inline():
    r = client().get("/login")
    csp = r.headers["content-security-policy"]
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert "'unsafe-inline'" not in script_src
    nonce = re.search(r"'nonce-([^']+)'", script_src).group(1)
    inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", r.text)
    assert inline and all(f'nonce="{nonce}"' in attrs for attrs in inline if "application/json" not in attrs)
    assert client().get("/login").headers["content-security-policy"] != csp   # je Antwort neu


def test_logged_in_pages_not_cached():
    c = login(*ADMIN)
    assert c.get("/").headers.get("cache-control") == "no-store"


def test_hsts_for_all_domains_with_letsencrypt():
    text = proxy.render({"tls_mode": "letsencrypt", "tls_email": "it@example.org", "short_domain": "k.example.org"})
    for host in ("meet.example.org", "portal.example.org", "k.example.org"):
        block = text.split(f"\n{host} {{", 1)[1].split("\n}", 1)[0]
        assert "Strict-Transport-Security" in block, host
    assert "Strict-Transport-Security" not in proxy.render({"tls_mode": "internal"})
