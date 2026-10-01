"""Design und Branding aus den Admin-Einstellungen.

Name, Impressum/Datenschutz-Links und Texte gelten immer. Farben, Logo, Farbschema,
Navigationsleiste und Rundungen greifen nur, wenn „Eigenes Design“ eingeschaltet ist.
Das Ergebnis wird kurz zwischengespeichert; Änderungen rufen invalidate() auf.
"""

import re
import time
from pathlib import Path

from .config import settings
from .db import SessionLocal, get_settings

BRAND_DIR = settings.data_dir / "branding"
DEFAULT_PRIMARY = "#1f5fa8"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

NAVBARS = {"primary": "Primärfarbe", "dark": "Dunkel", "light": "Hell"}
THEMES = {"auto": "Automatisch (nach Geräteeinstellung)", "light": "Immer hell", "dark": "Immer dunkel"}
RADII = {"0": "Eckig", "0.375rem": "Standard", "0.75rem": "Stark gerundet"}

LOGO_TYPES = {"png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "webp": b"RIFF", "svg": b"", }
FAVICON_TYPES = {"png": b"\x89PNG", "ico": b"\x00\x00\x01\x00", "svg": b""}

_cache: tuple[float, dict] | None = None


# --- Farbrechnung ------------------------------------------------------------

def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _hex(c: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ca, cb)))


def _luminance(h: str) -> float:
    def lin(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def shade(color: str, amount: float) -> str:
    """Farbe in Richtung Schwarz abdunkeln (amount 0..1)."""
    return _mix(color, "#000000", amount)


def on_color(bg: str) -> str:
    """Schriftfarbe mit gutem Kontrast auf bg."""
    return "#000000" if _luminance(bg) > 0.33 else "#ffffff"


def theme_css(b: dict) -> str:
    p = b["primary"]
    rgb = ",".join(map(str, _rgb(p)))
    txt = on_color(p)
    hover, active = _mix(p, "#000000", .12), _mix(p, "#000000", .2)
    dark_p = _mix(p, "#ffffff", .35) if _luminance(p) < .25 else p
    dark_rgb = ",".join(map(str, _rgb(dark_p)))
    link_hover = _mix(p, "#000000", .25)
    nav_bg = {"primary": p, "dark": "#1b2430", "light": ""}[b["navbar"]]
    nav_fg = on_color(nav_bg) if nav_bg else ""
    return f"""
:root, [data-bs-theme=light] {{
  --app-primary: {p}; --app-primary-text: {txt};
  --bs-primary: {p}; --bs-primary-rgb: {rgb};
  --bs-link-color: {p}; --bs-link-color-rgb: {rgb};
  --bs-link-hover-color: {link_hover}; --bs-link-hover-color-rgb: {",".join(map(str, _rgb(link_hover)))};
  --bs-border-radius: {b["radius"]}; --bs-border-radius-lg: calc({b["radius"]} * 1.35);
  --bs-border-radius-sm: calc({b["radius"]} * .7);
  --app-nav-bg: {nav_bg or "var(--bs-tertiary-bg)"}; --app-nav-fg: {nav_fg or "var(--bs-body-color)"};
}}
[data-bs-theme=dark] {{
  --bs-primary: {dark_p}; --bs-primary-rgb: {dark_rgb};
  --bs-link-color: {dark_p}; --bs-link-color-rgb: {dark_rgb};
  --bs-link-hover-color: {_mix(dark_p, "#ffffff", .2)};
  --bs-link-hover-color-rgb: {",".join(map(str, _rgb(_mix(dark_p, "#ffffff", .2))))};
  {"--app-nav-bg: #11161d;" if b["navbar"] == "light" else ""}
}}
.btn-primary {{
  --bs-btn-bg: {p}; --bs-btn-border-color: {p}; --bs-btn-color: {txt};
  --bs-btn-hover-bg: {hover}; --bs-btn-hover-border-color: {hover}; --bs-btn-hover-color: {on_color(hover)};
  --bs-btn-active-bg: {active}; --bs-btn-active-border-color: {active}; --bs-btn-active-color: {on_color(active)};
  --bs-btn-disabled-bg: {p}; --bs-btn-disabled-border-color: {p}; --bs-btn-disabled-color: {txt};
  --bs-btn-focus-shadow-rgb: {rgb};
}}
.btn-outline-primary {{
  --bs-btn-color: {p}; --bs-btn-border-color: {p};
  --bs-btn-hover-bg: {p}; --bs-btn-hover-border-color: {p}; --bs-btn-hover-color: {txt};
  --bs-btn-active-bg: {hover}; --bs-btn-active-border-color: {hover}; --bs-btn-active-color: {txt};
  --bs-btn-disabled-color: {p}; --bs-btn-disabled-border-color: {p};
  --bs-btn-focus-shadow-rgb: {rgb};
}}
[data-bs-theme=dark] .btn-outline-primary {{ --bs-btn-color: {dark_p}; --bs-btn-border-color: {dark_p}; }}
.text-bg-primary {{ color: {txt} !important; }}
.form-check-input:checked, .form-check-input[type=checkbox]:indeterminate {{
  background-color: {p}; border-color: {p};
}}
.form-control:focus, .form-select:focus, .form-check-input:focus {{
  border-color: rgba({rgb}, .6); box-shadow: 0 0 0 .25rem rgba({rgb}, .22);
}}
.nav-pills {{ --bs-nav-pills-link-active-bg: {p}; --bs-nav-pills-link-active-color: {txt}; }}
.page-link {{ --bs-pagination-color: {p}; --bs-pagination-active-bg: {p}; --bs-pagination-active-border-color: {p}; --bs-pagination-active-color: {txt}; }}
.progress-bar {{ background-color: {p}; }}
"""


# --- Laden -------------------------------------------------------------------

def _url(value: str) -> str:
    value = (value or "").strip()
    return value if value.startswith(("https://", "http://", "/")) and not value.startswith("//") else ""


def _file(cfg: dict, key: str) -> tuple[str | None, str]:
    name = cfg.get(key) or ""
    path = BRAND_DIR / name
    if name and "/" not in name and path.exists():
        return name, f"/branding/{key.removeprefix('ui_')}?v={name}"
    return None, ""


def build(cfg: dict) -> dict:
    custom = cfg.get("ui_custom") == "1"
    b = {
        "custom": custom,
        "name": cfg.get("ui_brand_name", "").strip() or settings.brand_name,
        "product": cfg.get("ui_product", "").strip() or settings.brand_product,
        "primary": DEFAULT_PRIMARY, "navbar": "dark", "theme": "auto", "radius": "0.375rem",
        "logo": "", "favicon": "", "logo_height": 32, "show_name": True,
        "login_text": cfg.get("ui_login_text", "").strip(),
        "footer_text": cfg.get("ui_footer_text", "").strip(),
        "imprint_url": _url(cfg.get("ui_imprint_url", "")),
        "privacy_url": _url(cfg.get("ui_privacy_url", "")),
    }
    if custom:
        if HEX.match(cfg.get("ui_primary", "")):
            b["primary"] = cfg["ui_primary"].lower()
        if cfg.get("ui_navbar") in NAVBARS:
            b["navbar"] = cfg["ui_navbar"]
        if cfg.get("ui_theme") in THEMES:
            b["theme"] = cfg["ui_theme"]
        if cfg.get("ui_radius") in RADII:
            b["radius"] = cfg["ui_radius"]
        try:
            b["logo_height"] = max(20, min(80, int(cfg.get("ui_logo_height", "32"))))
        except ValueError:
            pass
        b["show_name"] = cfg.get("ui_show_name", "1") == "1"
        b["logo"] = _file(cfg, "ui_logo")[1]
        b["favicon"] = _file(cfg, "ui_favicon")[1]
    nav_bg = {"primary": b["primary"], "dark": "#1b2430"}.get(b["navbar"], "")
    b["navbar_dark"] = (on_color(nav_bg) == "#ffffff") if nav_bg else False
    b["css"] = theme_css(b)
    return b


def load() -> dict:
    global _cache
    if _cache and time.monotonic() - _cache[0] < 10:
        return _cache[1]
    with SessionLocal() as db:
        b = build(get_settings(db))
    _cache = (time.monotonic(), b)
    return b


def invalidate() -> None:
    global _cache
    _cache = None


def file_path(kind: str) -> Path | None:
    with SessionLocal() as db:
        name = get_settings(db).get(f"ui_{kind}") or ""
    path = BRAND_DIR / name
    return path if name and "/" not in name and path.exists() else None


# --- Upload ------------------------------------------------------------------

def check_upload(data: bytes, filename: str, allowed: dict[str, bytes], max_bytes: int) -> str:
    """Prüft Größe und Dateityp, gibt die Endung zurück oder wirft ValueError (deutsche Meldung)."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    ext = "jpg" if ext == "jpeg" else ext
    if ext not in allowed:
        raise ValueError("Erlaubt sind: " + ", ".join(sorted(allowed)).upper() + ".")
    if len(data) > max_bytes:
        raise ValueError(f"Die Datei ist größer als {max_bytes // 1024} kB.")
    if ext == "svg":
        text = data.decode("utf-8", errors="ignore").lower()
        if "<svg" not in text or any(x in text for x in ("<script", "javascript:", "onload=", "onerror=", "<foreignobject")):
            raise ValueError("Die SVG-Datei ist ungültig oder enthält aktive Inhalte.")
    elif not data.startswith(allowed[ext]):
        raise ValueError("Der Dateiinhalt passt nicht zur Endung.")
    return ext
