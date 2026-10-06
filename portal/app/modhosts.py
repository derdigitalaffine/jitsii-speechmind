"""Eigene Domains je Modul (Verwaltung › Domains).

Ein Modul mit eigener Domain (z. B. krank.example.de) bleibt zusätzlich unter der Portal-Domain erreichbar
(https://portal.example.de/krank). Unter der Modul-Domain liefert das Portal nur die öffentlichen Seiten dieses
Moduls und die gemeinsam genutzten Hilfspfade (Stile, Skripte, Kartenkacheln, Adresssuche, Bezahlseite).
Die Startseite „/“ führt zur öffentlichen Einstiegsseite des Moduls; alle anderen Pfade (Anmeldung, Verwaltung,
andere Module) werden auf dieselbe Adresse unter der Portal-Domain umgeleitet – dort gilt die Anmeldung.

Caddy holt für jede eingetragene Domain selbst ein Zertifikat (Let's Encrypt, sobald unter „HTTPS & Zertifikat“
eingeschaltet; sonst selbst signiert) und erneuert es automatisch. Kurzlinks behalten ihre eigene Einstellung
(short_domain, siehe shortlinks.py) mit eigener Weiterleitungslogik.
"""

import re

# Modul: (Bezeichnung, Einstiegsseite oder "" = keine öffentliche Startseite, öffentliche Pfade)
MODULE_PUBLIC = {
    "forms": ("Formulare", "", ("/f",)),
    "applications": ("Online-Anträge", "/antraege", ("/antraege", "/antraege-embed", "/a")),
    "polls": ("Terminumfragen & Abstimmungen", "", ("/t", "/v")),
    "bookings": ("Terminbuchung", "/b", ("/b",)),
    "resources": ("Ressourcenbuchung", "/r", ("/r", "/r-embed")),
    "laws": ("Rechtstexte", "/recht", ("/recht", "/recht-embed")),
    "maps": ("Kartenbrowser", "/karte", ("/karte", "/karte-embed")),
    "krank": ("BlueOtter Krankmelder", "/krank", ("/krank", "/krank-embed")),
}
# Hilfspfade, die öffentliche Seiten aller Module nachladen
SHARED = ("/static", "/healthz", "/branding", "/org", "/geo", "/map", "/pay", "/paypal/return", "/favicon.ico", "/robots.txt")
# Pfade, die in fremden Seiten (iframe) erscheinen dürfen – für den Proxy
EMBED_PATHS = ("/recht-embed", "/karte-embed", "/antraege-embed", "/r-embed", "/krank-embed")

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def domains(cfg: dict[str, str]) -> dict[str, str]:
    """Modul → eingetragene Domain (nur gesetzte)."""
    out = {}
    for key in MODULE_PUBLIC:
        domain = (cfg.get(f"domain_{key}") or "").strip().lower()
        if domain:
            out[key] = domain
    return out


def host_map(cfg: dict[str, str]) -> dict[str, str]:
    return {domain: key for key, domain in domains(cfg).items()}


def allowed(key: str, path: str) -> bool:
    """Darf dieser Pfad unter der Domain des Moduls ausgeliefert werden?"""
    if any(_under(path, p) for p in SHARED):
        return True
    return any(_under(path, p) for p in MODULE_PUBLIC[key][2])


def start_path(key: str) -> str:
    return MODULE_PUBLIC[key][1]


def clean(value: str) -> str:
    return (value or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")


def validate(new: dict[str, str], reserved: dict[str, str]) -> list[str]:
    """Prüft eingetragene Domains: gültig, nicht doppelt, nicht Konferenz-, Portal- oder Kurzlink-Domain."""
    errors, seen = [], {}
    taken = {v: k for k, v in reserved.items() if v}
    for key, domain in new.items():
        if not domain:
            continue
        label = MODULE_PUBLIC[key][0]
        if not DOMAIN_RE.match(domain):
            errors.append(f"{label}: „{domain}“ ist keine gültige Domain (z. B. krank.example.de).")
        elif domain in taken:
            errors.append(f"{label}: „{domain}“ ist bereits als {taken[domain]} vergeben.")
        elif domain in seen:
            errors.append(f"{label}: „{domain}“ ist schon für {MODULE_PUBLIC[seen[domain]][0]} eingetragen.")
        seen[domain] = key
    return errors
