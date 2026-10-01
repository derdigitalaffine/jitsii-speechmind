"""Kurzlinks (Funktionsumfang angelehnt an Shlink).

Ein Kurzlink leitet von <Kurz-Adresse>/<code> auf eine lange Adresse weiter. Kurz-Adresse ist
entweder <Portal>/s/ oder eine eigene Kurz-Domain (Admin › Kurzlinks), die Caddy auf /s/ umschreibt.

Optional: Gültigkeitszeitraum, maximale Anzahl Aufrufe, Weitergabe von Query-Parametern,
Art der Weiterleitung. Aufrufe werden datensparsam gezählt: ohne IP-Adresse, vom User-Agent werden
nur Browser, Betriebssystem und Gerätetyp gespeichert, vom Referer nur der Hostname.
"""

import io
import re
import secrets
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import segno
from sqlalchemy import func, select

from .config import settings
from .db import ShortLink, ShortVisit, to_local, utcnow

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # ohne leicht verwechselbare Zeichen (l, 1, o, 0, i)
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TAG_RE = re.compile(r"[^\w äöüÄÖÜß.-]+")
REDIRECT_CODES = {302: "302 – vorübergehend (Standard, Aufrufe werden immer gezählt)",
                  301: "301 – dauerhaft (Browser merken sich das Ziel, spätere Aufrufe fehlen in der Statistik)",
                  307: "307 – vorübergehend, Methode bleibt erhalten",
                  308: "308 – dauerhaft, Methode bleibt erhalten"}

_BOTS = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|skypeuripreview|"
                   r"curl|wget|python-requests|httpx|go-http|java/|okhttp|headless|lighthouse|"
                   r"safelinks|proofpoint|mimecast|barracuda|microsoft office|ms-office|outlook", re.I)


def short_base(cfg: dict[str, str]) -> str:
    domain = (cfg.get("short_domain") or "").strip().lower()
    if domain:
        scheme = urlparse(settings.portal_base_url).scheme or "https"
        return f"{scheme}://{domain}/"
    return f"{settings.portal_base_url}/s/"


def short_url(cfg: dict[str, str], link: ShortLink) -> str:
    return short_base(cfg) + link.code


def normalize_code(code: str) -> str:
    return (code or "").strip().lower()


def valid_code(code: str) -> bool:
    return bool(CODE_RE.match(code))


def code_taken(db, code: str, exclude_id: int | None = None) -> bool:
    q = select(ShortLink.id).where(ShortLink.code == code)
    if exclude_id:
        q = q.where(ShortLink.id != exclude_id)
    return db.scalar(q) is not None


def new_code(db, length: int = 6) -> str:
    length = min(max(length, 4), 20)
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if not code_taken(db, code):
            return code


def clean_url(url: str) -> str | None:
    """Nur http(s)-Ziele mit Hostname (keine javascript:- oder data:-Links)."""
    url = (url or "").strip()
    if url and "://" not in url and re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c in url for c in "\r\n\t "):
        return None
    return url[:4000]


def clean_tags(text: str) -> str:
    tags = []
    for raw in re.split(r"[,;]", text or ""):
        tag = " ".join(TAG_RE.sub(" ", raw).split()).lower()[:40]
        if tag and tag not in tags:
            tags.append(tag)
    return ",".join(tags[:20])


# --- Weiterleitung -----------------------------------------------------------

def usable(link: ShortLink, now: datetime | None = None) -> str:
    """'' wenn der Link weiterleitet, sonst der Grund."""
    now = now or utcnow()
    if not link.active:
        return "deaktiviert"
    if link.valid_from and now < link.valid_from:
        return "noch nicht gültig"
    if link.valid_until and now > link.valid_until:
        return "abgelaufen"
    if link.max_visits and link.visit_count >= link.max_visits:
        return "Aufruf-Limit erreicht"
    return ""


def target_for(link: ShortLink, query: str) -> str:
    """Zieladresse; Query-Parameter des Aufrufs werden auf Wunsch angehängt (Ziel hat Vorrang nicht)."""
    if not query or not link.forward_query:
        return link.target_url
    parsed = urlparse(link.target_url)
    params = parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(query, keep_blank_values=True)
    return urlunparse(parsed._replace(query=urlencode(params)))


def parse_agent(ua: str) -> dict:
    ua = ua or ""
    bot = not ua or bool(_BOTS.search(ua))
    browser = next((name for pat, name in (
        (r"Edg/|Edge/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung Internet"),
        (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"), (r"Safari/", "Safari"),
        (r"MSIE|Trident/", "Internet Explorer")) if re.search(pat, ua)), "Sonstige")
    os_name = next((name for pat, name in (
        (r"Windows", "Windows"), (r"iPhone|iPad|iPod", "iOS"), (r"Android", "Android"),
        (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux")) if re.search(pat, ua)), "Sonstige")
    device = "Tablet" if re.search(r"iPad|Tablet", ua) else "Mobil" if re.search(r"Mobi|iPhone|Android", ua) else "Desktop"
    return {"bot": bot, "browser": "Bot" if bot else browser, "os": "" if bot else os_name,
            "device": "" if bot else device}


def record_visit(db, link: ShortLink, user_agent: str, referer: str) -> None:
    info = parse_agent(user_agent)
    host = (urlparse(referer).hostname or "")[:255] if referer else ""
    db.add(ShortVisit(link_id=link.id, referer_host=host, browser=info["browser"], os=info["os"],
                      device=info["device"], bot=info["bot"]))
    if info["bot"]:
        link.bot_count = (link.bot_count or 0) + 1
    else:
        link.visit_count = (link.visit_count or 0) + 1
        link.last_visit_at = utcnow()


# --- Auswertung --------------------------------------------------------------

def stats(db, link: ShortLink, days: int = 30, include_bots: bool = False) -> dict:
    since = utcnow() - timedelta(days=days)
    q = select(ShortVisit).where(ShortVisit.link_id == link.id, ShortVisit.at >= since)
    if not include_bots:
        q = q.where(ShortVisit.bot.is_(False))
    visits = db.scalars(q).all()
    today = to_local(utcnow()).date()
    per_day = Counter(to_local(v.at).date() for v in visits)
    labels, values = [], []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%d.%m."))
        values.append(per_day.get(d, 0))
    top = lambda attr: Counter(getattr(v, attr) or "–" for v in visits).most_common(6)  # noqa: E731
    return {"labels": labels, "counts": values, "total": len(visits), "browsers": top("browser"),
            "os": top("os"), "devices": top("device"), "referers": top("referer_host")}


def totals(db, owner_id: int | None = None) -> dict:
    q = select(func.count(ShortLink.id), func.coalesce(func.sum(ShortLink.visit_count), 0))
    if owner_id is not None:
        q = q.where(ShortLink.owner_id == owner_id)
    count, visits = db.execute(q).one()
    return {"links": count, "visits": visits}


QR_FORMATS = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg"}
QR_ERRORS = {"l": "L – 7 %", "m": "M – 15 % (Standard)", "q": "Q – 25 %", "h": "H – 30 % (für Logos/Aufkleber)"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def qr_options(fmt: str = "svg", size: str | int = 8, dark: str = "#000000", light: str = "#ffffff",
               error: str = "m", border: str | int = 2) -> dict:
    """Prüft und begrenzt die Einstellungen des QR-Generators."""
    def num(value, lo, hi, default):
        try:
            return min(max(int(value), lo), hi)
        except (TypeError, ValueError):
            return default
    return {"fmt": fmt if fmt in QR_FORMATS else "svg", "scale": num(size, 1, 40, 8),
            "dark": dark if COLOR_RE.match(dark or "") else "#000000",
            "light": light if COLOR_RE.match(light or "") else "#ffffff",
            "error": error if error in QR_ERRORS else "m", "border": num(border, 0, 10, 2)}


def qr_image(data: str, opts: dict) -> tuple[bytes, str]:
    """QR-Code als SVG, PNG oder JPG. Gibt (Inhalt, Medientyp) zurück."""
    qr = segno.make(data, error=opts["error"], micro=False)
    buf = io.BytesIO()
    kw = {"scale": opts["scale"], "border": opts["border"], "dark": opts["dark"], "light": opts["light"]}
    if opts["fmt"] == "svg":
        qr.save(buf, kind="svg", xmldecl=True, **kw)
    else:
        qr.save(buf, kind="png", **kw)
        if opts["fmt"] == "jpg":
            from PIL import Image  # JPEG kann segno nicht selbst schreiben
            img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95, subsampling=0)
    return buf.getvalue(), QR_FORMATS[opts["fmt"]]
