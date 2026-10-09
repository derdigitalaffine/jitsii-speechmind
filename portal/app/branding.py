"""Design und Branding aus den Admin-Einstellungen.

Name, Impressum/Datenschutz-Links und Texte gelten immer. Farben, Logo, Farbschema,
Navigationsleiste und Rundungen greifen nur, wenn „Eigenes Design“ eingeschaltet ist.
Das Ergebnis wird kurz zwischengespeichert; Änderungen rufen invalidate() auf.
"""

import io
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
FAVICON_TYPES = {"png": b"\x89PNG", "ico": b"\x00\x00\x01\x00", "svg": b"", "jpg": b"\xff\xd8\xff", "webp": b"RIFF"}
# Uploads dürfen groß sein; Rastergrafiken verkleinert der Server auf eine sinnvolle Größe
MAX_UPLOAD = 40_000_000
MAX_SVG = 2_000_000
LOGO_BOX = (1600, 320)    # reicht für 80 px Logohöhe auch auf hochauflösenden Bildschirmen (4x)
FAVICON_SIZE = 64

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
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def shade(color: str, amount: float) -> str:
    """Farbe in Richtung Schwarz abdunkeln (amount 0..1)."""
    return _mix(color, "#000000", amount)


def on_color(bg: str) -> str:
    """Schriftfarbe mit gutem Kontrast auf bg."""
    return "#000000" if _luminance(bg) > 0.179 else "#ffffff"


def contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)))
    return (y + .05) / (x + .05)


def palette(primary: str, navbar: str, theme: str) -> dict:
    """The exact solid and composited colors used by CSS and editor checks."""
    dark = theme == "dark"
    body = "#212529" if dark else "#ffffff"
    link = _mix(primary, "#ffffff", .35) if dark and _luminance(primary) < .25 else primary
    nav = {"primary": primary, "dark": "#1b2430", "light": "#11161d" if dark else "#f8f9fa"}[navbar]
    focus = on_color(body)
    return dict(primary=primary, text=on_color(primary), hover=shade(primary, .12), active=shade(primary, .2),
                body=body, link=link, link_hover=_mix(link, "#ffffff" if dark else "#000000", .2 if dark else .25),
                selection=_mix(body, link, .14), nav=nav, nav_text=on_color(nav),
                nav_product=_mix(nav, on_color(nav), .75), focus=focus,
                nav_focus=focus if contrast(focus, nav) >= 3 else on_color(nav))


def contrast_report(primary: str, navbar: str) -> dict:
    rows = []
    for theme in ("light", "dark"):
        c = palette(primary, navbar, theme)
        combinations = [("Primärbutton / Badge / Auswahl", c["text"], primary, 4.5),
                        ("Button beim Darüberfahren", on_color(c["hover"]), c["hover"], 4.5),
                        ("Gedrückter Button", on_color(c["active"]), c["active"], 4.5),
                        ("Link", c["link"], c["body"], 4.5),
                        ("Link beim Darüberfahren", c["link_hover"], c["body"], 4.5),
                        ("Aktive Seitennavigation", c["link"], c["selection"], 4.5),
                        ("Kopfzeile", c["nav_text"], c["nav"], 4.5),
                        ("Produktbezeichnung in Kopfzeile", c["nav_product"], c["nav"], 4.5),
                        ("Fokus auf Seiteninhalt", c["focus"], c["body"], 3),
                        ("Fokus in Kopfzeile", c["nav_focus"], c["nav"], 3),
                        ("Fokus auf Karten / Nebenflächen", c["focus"], "#2b3035" if theme == "dark" else "#f8f9fa", 3),
                        ("Checkbox-/Radio-/Schalter-Markierung", c["text"], primary, 3)]
        for label, fg, bg, minimum in combinations:
            ratio = contrast(fg, bg)
            rows.append(dict(theme=theme, label=label, fg=fg, bg=bg, ratio=round(ratio, 2),
                             minimum=minimum, ok=ratio >= minimum,
                             rating="gut – AA für normalen Text" if ratio >= 4.5 else
                                    "gut – sichtbarer Fokus / Markierung" if minimum == 3 and ratio >= 3 else
                                    "nur große Schrift" if ratio >= 3 else "zu geringer Kontrast"))
    # One nearby candidate improving the actual warnings in both schemes.
    candidates = [_mix(primary, "#000000", i / 100) for i in range(1, 100)] + [_mix(primary, "#ffffff", i / 100) for i in range(1, 100)]
    def link_ok(color):
        return all(contrast(palette(color, navbar, t)["link"], palette(color, navbar, t)["selection"]) >= 4.5
                   and contrast(palette(color, navbar, t)["link_hover"], palette(color, navbar, t)["body"]) >= 4.5
                   and contrast(palette(color, navbar, t)["link"], palette(color, navbar, t)["body"]) >= 4.5
                   and contrast(palette(color, navbar, t)["nav_product"], palette(color, navbar, t)["nav"]) >= 4.5 for t in ("light", "dark"))
    valid = [c for c in candidates if link_ok(c)]
    suggestion = min(valid, key=lambda c: sum((x-y)**2 for x,y in zip(_rgb(c), _rgb(primary)))) if valid else None
    return dict(rows=rows, warnings=[r for r in rows if not r["ok"]], suggestion=suggestion)


def theme_css(b: dict) -> str:
    p = b["primary"]
    c = palette(p, b["navbar"], "light")
    d = palette(p, b["navbar"], "dark")
    rgb = ",".join(map(str, _rgb(p)))
    def variables(x):
        return f"--bs-link-color: {x['link']}; --bs-link-color-rgb: {','.join(map(str,_rgb(x['link'])))}; --bs-link-hover-color: {x['link_hover']}; --bs-link-hover-color-rgb: {','.join(map(str,_rgb(x['link_hover'])))}; --app-nav-bg: {x['nav']}; --app-nav-fg: {x['nav_text']}; --app-focus: {x['focus']}; --app-nav-focus: {x['nav_focus']}; --app-selection: {x['selection']};"
    # Bootstrap indicators otherwise remain white on a bright custom primary.
    stroke = c['text'].replace('#', '%23')
    check = f"url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3e%3cpath fill='none' stroke='{stroke}' stroke-linecap='round' stroke-linejoin='round' stroke-width='3' d='m6 10 3 3 6-6'/%3e%3c/svg%3e\")"
    radio = f"url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='-4 -4 8 8'%3e%3ccircle r='2' fill='{stroke}'/%3e%3c/svg%3e\")"
    dash = f"url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3e%3cpath fill='none' stroke='{stroke}' stroke-linecap='round' stroke-width='3' d='M6 10h8'/%3e%3c/svg%3e\")"
    return f"""
:root, [data-bs-theme=light] {{
 --app-primary: {p}; --app-primary-text: {c['text']}; --bs-primary: {p}; --bs-primary-rgb: {rgb};
 --bs-border-radius: {b['radius']}; --bs-border-radius-lg: calc({b['radius']} * 1.35); --bs-border-radius-sm: calc({b['radius']} * .7);
 {variables(c)}
}}
[data-bs-theme=dark] {{ --bs-primary: {d["link"]}; --bs-primary-rgb: {",".join(map(str,_rgb(d["link"])))}; {variables(d)} }}
.btn-primary {{ --bs-btn-bg: {p}; --bs-btn-border-color: {p}; --bs-btn-color: {c['text']};
 --bs-btn-hover-bg: {c['hover']}; --bs-btn-hover-border-color: {c['hover']}; --bs-btn-hover-color: {on_color(c['hover'])};
 --bs-btn-active-bg: {c['active']}; --bs-btn-active-border-color: {c['active']}; --bs-btn-active-color: {on_color(c['active'])};
 --bs-btn-disabled-bg: {p}; --bs-btn-disabled-border-color: {p}; --bs-btn-disabled-color: {c['text']}; }}
.btn-outline-primary {{ --bs-btn-color: var(--bs-link-color); --bs-btn-border-color: var(--bs-link-color);
 --bs-btn-hover-bg: {p}; --bs-btn-hover-border-color: {p}; --bs-btn-hover-color: {c['text']};
 --bs-btn-active-bg: {c['hover']}; --bs-btn-active-border-color: {c['hover']}; --bs-btn-active-color: {on_color(c['hover'])};
 --bs-btn-disabled-color: var(--bs-link-color); --bs-btn-disabled-border-color: var(--bs-link-color); }}
.text-bg-primary {{ background-color: {p} !important; color: {c['text']} !important; }}
.form-check-input:checked, .form-check-input[type=checkbox]:indeterminate {{ background-color: {p}; border-color: {p}; }}
.form-check-input[type=checkbox]:checked {{ --bs-form-check-bg-image: {check}; }}
.form-check-input[type=radio]:checked, .form-switch .form-check-input:checked {{ --bs-form-check-bg-image: {radio}; }}
.form-check-input[type=checkbox]:indeterminate {{ --bs-form-check-bg-image: {dash}; }}
.nav-pills {{ --bs-nav-pills-link-active-bg: {p}; --bs-nav-pills-link-active-color: {c['text']}; }}
.page-link {{ --bs-pagination-color: var(--bs-link-color); --bs-pagination-active-bg: {p}; --bs-pagination-active-border-color: {p}; --bs-pagination-active-color: {c['text']}; }}
.progress-bar {{ background-color: {p}; }}
.app-sidebar .nav-link.active {{ background: var(--app-selection); color: var(--bs-link-color); }}
:where(a,button,input,select,textarea,summary,[tabindex]):focus-visible {{ outline: 3px solid var(--app-focus) !important; outline-offset: 3px !important; box-shadow: none !important; }}
.app-navbar :where(a,button,input,select,textarea,[tabindex]):focus-visible {{ outline-color: var(--app-nav-focus) !important; }}
.fill-choice > input:focus-visible + .fill-choice-label {{ outline: 3px solid var(--app-focus); outline-offset: 3px; }}
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
        # Ohne eigenes Favicon: automatisch aus dem Logo erzeugte Fassung
        b["favicon"] = _file(cfg, "ui_favicon")[1] or (_file(cfg, "ui_favicon_auto")[1] if b["logo"] else "")
    nav_bg = {"primary": b["primary"], "dark": "#1b2430"}.get(b["navbar"], "")
    b["navbar_dark"] = (on_color(nav_bg) == "#ffffff") if nav_bg else False
    b["photos"] = photo_sizes(cfg)
    b["css"] = theme_css(b) + photo_css(b["photos"])
    return b


# Fotos der Räume & Plätze (gilt immer, auch ohne eigenes Design)
THUMB_RATIOS = {"16 / 9": "breit (16:9)", "4 / 3": "normal (4:3)", "21 / 9": "flach (21:9)", "3 / 1": "sehr flach (3:1)"}
PHOTO_DEFAULTS = {"gallery": 360, "gallery_mobile": 240, "ratio": "16 / 9", "fit": "cover"}


def _bounded(cfg: dict, key: str, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(cfg.get(key) or default)))
    except ValueError:
        return default


def photo_sizes(cfg: dict) -> dict:
    return {"gallery": _bounded(cfg, "ui_gallery_h", 120, 640, PHOTO_DEFAULTS["gallery"]),
            "gallery_mobile": _bounded(cfg, "ui_gallery_h_mobile", 100, 480, PHOTO_DEFAULTS["gallery_mobile"]),
            "ratio": cfg.get("ui_thumb_ratio") if cfg.get("ui_thumb_ratio") in THUMB_RATIOS else PHOTO_DEFAULTS["ratio"],
            "fit": "contain" if cfg.get("ui_photo_fit") == "contain" else "cover"}


def photo_css(p: dict) -> str:
    return (f"\n:root {{ --res-gallery-h: {p['gallery']}px; --res-gallery-h-sm: {p['gallery_mobile']}px; "
            f"--res-thumb-ratio: {p['ratio']}; --res-photo-fit: {p['fit']}; }}\n")


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
        cfg = get_settings(db)
    name = cfg.get(f"ui_{kind}") or ""
    if kind == "favicon_auto" and not cfg.get("ui_logo"):
        name = ""
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
        raise ValueError(f"Die Datei ist größer als {max_bytes // 1_000_000} MB.")
    if ext == "svg" and len(data) > MAX_SVG:
        raise ValueError(f"SVG-Dateien dürfen höchstens {MAX_SVG // 1_000_000} MB groß sein.")
    if ext == "svg":
        text = data.decode("utf-8", errors="ignore").lower()
        if "<svg" not in text or any(x in text for x in ("<script", "javascript:", "onload=", "onerror=", "<foreignobject")):
            raise ValueError("Die SVG-Datei ist ungültig oder enthält aktive Inhalte.")
    elif not data.startswith(allowed[ext]):
        raise ValueError("Der Dateiinhalt passt nicht zur Endung.")
    return ext


# --- Verkleinern und Favicon ----------------------------------------------------

def _open(data: bytes):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 120_000_000  # Schutz vor „Dekompressionsbomben“
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001 – Pillow wirft je nach Format verschiedene Fehler
        raise ValueError("Das Bild lässt sich nicht lesen.") from exc
    return ImageOps.exif_transpose(img)


def _encode(img, ext: str) -> tuple[bytes, str]:
    buf = io.BytesIO()
    has_alpha = img.mode in ("RGBA", "LA", "P") and (img.mode != "P" or "transparency" in img.info)
    if ext == "jpg" and not has_alpha:
        img.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True, progressive=True)
        return buf.getvalue(), "jpg"
    if ext == "webp":
        img.save(buf, format="WEBP", quality=90, method=6)
        return buf.getvalue(), "webp"
    img.convert("RGBA" if has_alpha else "RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue(), "png"


def shrink_logo(data: bytes, ext: str) -> tuple[bytes, str, bool]:
    """Verkleinert große Rastergrafiken (SVG bleibt). Gibt (Daten, Endung, verkleinert?) zurück."""
    if ext == "svg":
        return data, ext, False
    img = _open(data)
    if img.width <= LOGO_BOX[0] and img.height <= LOGO_BOX[1] and len(data) <= 1_000_000:
        return data, ext, False
    from PIL import Image
    img.thumbnail(LOGO_BOX, Image.Resampling.LANCZOS)
    out, new_ext = _encode(img, ext)
    return out, new_ext, True


def make_favicon(data: bytes, ext: str, size: int = FAVICON_SIZE) -> tuple[bytes, str]:
    """Quadratisches Favicon (PNG, transparent aufgefüllt). SVG wird unverändert verwendet."""
    if ext in ("svg", "ico"):
        return data, ext
    from PIL import Image
    img = _open(data).convert("RGBA")
    # Ränder ohne Inhalt abschneiden, damit das Symbol im kleinen Format möglichst groß ist
    box = img.getbbox()
    if box:
        img = img.crop(box)
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), "png"
