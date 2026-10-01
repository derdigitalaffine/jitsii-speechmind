import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    portal_base_url = _env("PORTAL_BASE_URL", "http://localhost:8000").rstrip("/")
    meet_base_url = _env("MEET_BASE_URL", "http://localhost:8080").rstrip("/")

    secret_key = _env("PORTAL_SECRET_KEY")
    admin_email = _env("PORTAL_ADMIN_EMAIL").lower()
    admin_password = _env("PORTAL_ADMIN_PASSWORD")

    jwt_app_id = _env("JWT_APP_ID", "jitsi-speechmind")
    jwt_app_secret = _env("JWT_APP_SECRET")
    jwt_audience = _env("JWT_ACCEPTED_AUDIENCES", "jitsi").split(",")[0].strip()
    jwt_ttl_minutes = int(_env("JWT_TOKEN_TTL_MINUTES", "240") or 240)

    data_dir = Path(_env("DATA_DIR", "./data"))
    recordings_dir = Path(_env("RECORDINGS_DIR", "./recordings"))

    watch_interval_seconds = int(_env("WATCH_INTERVAL_SECONDS", "15") or 15)
    poll_interval_seconds = int(_env("SPEECHMIND_POLL_SECONDS", "45") or 45)
    # Wie lange auf SpeechMind gewartet wird, bevor ein Auftrag als Fehler gilt
    poll_timeout_hours = int(_env("SPEECHMIND_POLL_TIMEOUT_HOURS", "12") or 12)

    secure_cookies = portal_base_url.startswith("https://")


settings = Settings()

if not settings.secret_key or settings.secret_key == "CHANGE_ME":
    raise RuntimeError("PORTAL_SECRET_KEY ist nicht gesetzt (scripts/setup.sh ausführen).")
if not settings.jwt_app_secret or settings.jwt_app_secret == "CHANGE_ME":
    raise RuntimeError("JWT_APP_SECRET ist nicht gesetzt (scripts/setup.sh ausführen).")

settings.data_dir.mkdir(parents=True, exist_ok=True)
