"""QR-Codes zu öffentlichen Links des Portals: einheitlicher Dialog (Vorschau, SVG/PNG/JPG, Größe, Farben) und
Aushang zum Ausdrucken (A4 mit Titel, Hinweistext, großem QR-Code und Adresse). Nur für Angemeldete und nur
für Adressen dieses Portals (Portal-Domain, Modul-Domains, Kurzlink-Domain) – kein offener QR-Generator."""

import base64
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from . import branding, links, shortlinks as sl
from .config import settings
from .db import User
from .main import MODULES, app, current_user, render


def allowed_hosts() -> set[str]:
    cfg = links._cfg()
    hosts = {urlparse(settings.portal_base_url).netloc.lower()}
    hosts |= {links.domain_of(cfg, key) for key in MODULES}
    hosts.add((cfg.get("short_domain") or "").strip().lower())
    return {h for h in hosts if h}


def checked_url(u: str) -> str:
    """Absolute Adresse dieses Portals – relative Pfade werden an die Portal-Adresse gehängt."""
    u = (u or "").strip()[:1500]
    if u.startswith("/") and not u.startswith("//"):
        u = settings.portal_base_url.rstrip("/") + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or p.netloc.lower() not in allowed_hosts():
        raise HTTPException(400, "QR-Codes gibt es hier nur für Adressen dieses Portals.")
    return u


@app.get("/qr/link.{fmt}")
def qr_link(fmt: str, u: str = "", size: int = 10, dark: str = "#000000", light: str = "#ffffff", error: str = "m",
            border: int = 2, download: str = "", name: str = "", user: User = Depends(current_user)):
    url = checked_url(u)
    opts = sl.qr_options(fmt, size, dark, light, error, border)
    data, media = sl.qr_image(url, opts)
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        safe = "".join(ch for ch in (name or "qr-code") if (ch.isascii() and ch.isalnum()) or ch in "-_")[:60] or "qr-code"
        headers["Content-Disposition"] = f'attachment; filename="{safe}.{opts["fmt"]}"'
    return Response(data, media_type=media, headers=headers)


@app.get("/qr/aushang")
def qr_poster(request: Request, u: str = "", title: str = "", text: str = "", dark: str = "#000000",
              user: User = Depends(current_user)):
    """Druckansicht A4: Titel, Hinweis, großer QR-Code, Adresse, Logo und Name der Organisation."""
    url = checked_url(u)
    opts = sl.qr_options("svg", 10, dark, "#ffffff", "q", 2)
    svg, _ = sl.qr_image(url, opts)
    qr = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
    return render(request, "qr_poster.html", user, url=url, qr=qr, title=title.strip()[:120] or "Jetzt online",
                  text=text.strip()[:300] or "QR-Code mit der Handykamera scannen", brand=branding.load(),
                  short=url.split("://", 1)[-1])
