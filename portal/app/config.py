import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    portal_base_url = _env("PORTAL_BASE_URL", "http://localhost:8000").rstrip("/")
    meet_base_url = _env("MEET_BASE_URL", "http://localhost:8080").rstrip("/")

    brand_name = _env("BRAND_NAME", "Verbandsgemeinde Otterbach-Otterberg")
    brand_product = _env("BRAND_PRODUCT", "Videokonferenzserver")

    secret_key = _env("PORTAL_SECRET_KEY")
    # Standard-Administrator, wird nur angelegt, solange es noch keinen Benutzer gibt.
    # Ohne PORTAL_ADMIN_PASSWORD wird ein Zufallspasswort erzeugt und einmalig ins Log geschrieben.
    admin_email = (_env("PORTAL_ADMIN_EMAIL") or "admin@portal.local").lower()
    admin_password = _env("PORTAL_ADMIN_PASSWORD")
    if admin_password == "CHANGE_ME":
        admin_password = ""

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

    # Reverse Proxy (Caddy): Konfigurationsordner und Zertifikatsspeicher des Caddy-Containers
    caddy_conf_dir = Path(_env("CADDY_CONF_DIR", "/caddyconf"))
    caddy_data_dir = Path(_env("CADDY_DATA_DIR", "/caddydata"))
    proxy_host = _env("PROXY_HOST", "caddy")
    public_ips = [ip.strip() for ip in _env("PUBLIC_IP").split(",") if ip.strip()]
    acme_email = _env("ACME_EMAIL").lower()

    invite_ttl_hours = int(_env("INVITE_TTL_HOURS", "72") or 72)
    reset_ttl_hours = int(_env("RESET_TTL_HOURS", "2") or 2)

    secure_cookies = portal_base_url.startswith("https://")


settings = Settings()

if not settings.secret_key or settings.secret_key == "CHANGE_ME":
    raise RuntimeError("PORTAL_SECRET_KEY ist nicht gesetzt (scripts/setup.sh ausführen).")
if not settings.jwt_app_secret or settings.jwt_app_secret == "CHANGE_ME":
    raise RuntimeError("JWT_APP_SECRET ist nicht gesetzt (scripts/setup.sh ausführen).")

settings.data_dir.mkdir(parents=True, exist_ok=True)
