"""Testumgebung: eigenes Datenverzeichnis, kein Hintergrunddienst, kein Mailversand."""

import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="portal-tests-")
os.environ.update({
    "PORTAL_SECRET_KEY": "test-secret-key-for-pytest-only-0123456789",
    "JWT_APP_SECRET": "test-jwt-secret",
    "DATA_DIR": str(Path(_TMP) / "data"),
    "RECORDINGS_DIR": str(Path(_TMP) / "recordings"),
    "CADDY_CONF_DIR": str(Path(_TMP) / "caddy"),
    "PORTAL_BASE_URL": "https://portal.example.org",
    "MEET_BASE_URL": "https://meet.example.org",
    "PORTAL_ADMIN_EMAIL": "admin@example.org",
    "PORTAL_ADMIN_PASSWORD": "admin-passwort-123",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.db import SessionLocal, init_db, set_setting  # noqa: E402

init_db()
main.bootstrap_admin()
with SessionLocal() as _db:
    from sqlalchemy import select as _select
    from app.db import User as _User
    for _u in _db.scalars(_select(_User)):
        _u.must_change_password = False
    _db.commit()


@pytest.fixture(autouse=True)
def _reset_limits():
    main._attempts.clear()
    main._module_cache["at"] = 0.0
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def settings(**values):
    with SessionLocal() as session:
        for k, v in values.items():
            set_setting(session, k, v)
        session.commit()
    main._module_cache["at"] = 0.0


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf" content="([^"]+)"', html).group(1)


def client() -> TestClient:
    return TestClient(main.app, base_url="https://portal.example.org", follow_redirects=False)


def login(email: str, password: str) -> TestClient:
    c = client()
    token = csrf_of(c.get("/login").text)
    r = c.post("/login", data={"email": email, "password": password, "next": "/", "csrf": token})
    assert r.status_code == 303 and "/login" not in r.headers["location"], r.headers.get("location")
    return c
