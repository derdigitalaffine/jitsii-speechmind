"""Reverse Proxy (Caddy): Konfiguration erzeugen, Zertifikate prüfen.

Das Portal schreibt die Caddyfile in einen gemeinsamen Ordner; der Caddy-Container läuft mit
`--watch` und lädt sie selbst neu. Schlägt das Laden fehl (z. B. wegen eines Fehlers), behält
Caddy die bisherige Konfiguration. Eine Verbindung zu Caddys Admin-Schnittstelle ist nicht nötig.

Modi:
  selfsigned   Standard. Caddy stellt Zertifikate aus seiner eigenen CA aus (`tls internal`).
               Der Browser warnt, solange das Root-Zertifikat nicht installiert ist.
  letsencrypt  Caddy holt und erneuert Zertifikate automatisch bei Let's Encrypt.
"""

import logging
import os
import re
import socket
import ssl
import tempfile
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from .config import settings

log = logging.getLogger("portal.proxy")

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$|^localhost$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
STAGING_CA = "https://acme-staging-v02.api.letsencrypt.org/directory"


def hosts() -> dict[str, str]:
    """Domains von Konferenz und Portal (aus den Basis-URLs der Konfiguration)."""
    return {
        "meet": (urlparse(settings.meet_base_url).hostname or "").lower(),
        "portal": (urlparse(settings.portal_base_url).hostname or "").lower(),
    }


def available() -> bool:
    return settings.caddy_conf_dir.is_dir()


# --- Caddyfile ---------------------------------------------------------------

def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def render(cfg: dict[str, str]) -> str:
    """Erzeugt die Caddyfile. Alle eingesetzten Werte sind vorher validiert (keine Injektion)."""
    h = hosts()
    for name, host in h.items():
        if not DOMAIN_RE.match(host):
            raise ValueError(f"Ungültige Domain für {name}: {host!r}")
    letsencrypt = cfg.get("tls_mode") == "letsencrypt"
    email = cfg.get("tls_email", "")
    if letsencrypt and not valid_email(email):
        raise ValueError("Für Let's Encrypt wird eine gültige E-Mail-Adresse benötigt.")

    glob = []
    if letsencrypt:
        glob.append(f"\temail {email}")
        if cfg.get("tls_staging") == "1":
            glob.append(f"\tacme_ca {STAGING_CA}")
    tls = "" if letsencrypt else "\ttls internal\n"
    # HSTS nur mit vertrauenswürdigem Zertifikat: bei einem selbst signierten wäre die
    # Browser-Warnung sonst nicht mehr wegklickbar.
    hsts = '\t\tStrict-Transport-Security "max-age=31536000"\n' if letsencrypt else ""
    mode_label = "Let's Encrypt" if letsencrypt else "selbst signiert"
    head = "{\n" + "\n".join(glob) + "\n}\n\n" if glob else ""
    return (
        "# Von der Portal-Oberfläche erzeugt (Admin › HTTPS / Zertifikat). Nicht von Hand ändern.\n"
        f"# Modus: {mode_label}\n"
        f"{head}"
        f"{h['meet']} {{\n{tls}\tencode gzip\n"
        "\t# Design der Konferenzoberfläche (dynamicBrandingUrl) und Logo kommen vom Portal\n"
        "\thandle /branding/* {\n\t\treverse_proxy portal:8000\n\t}\n"
        "\thandle {\n\t\treverse_proxy web:80\n\t}\n}\n\n"
        f"{h['portal']} {{\n{tls}\tencode gzip\n\trequest_body {{\n\t\tmax_size 10MB\n\t}}\n"
        "\theader {\n"
        f"{hsts}"
        '\t\tX-Content-Type-Options "nosniff"\n'
        '\t\tReferrer-Policy "same-origin"\n'
        '\t\tX-Frame-Options "DENY"\n'
        "\t}\n\treverse_proxy portal:8000\n}\n"
        f"{short_block(cfg, h, tls)}"
    )


def short_block(cfg: dict[str, str], h: dict[str, str], tls: str) -> str:
    """Optionale Kurz-Domain: jeder Pfad wird auf /s/... des Portals umgeschrieben."""
    domain = (cfg.get("short_domain") or "").strip().lower()
    if not domain:
        return ""
    if not DOMAIN_RE.match(domain) or domain in h.values():
        raise ValueError(f"Ungültige Kurz-Domain: {domain!r}")
    return (f"\n{domain} {{\n{tls}\tencode gzip\n"
            "\t# Kurzlinks (Portal › Kurzlinks): /abc -> Portal /s/abc\n"
            "\trewrite * /s{uri}\n\treverse_proxy portal:8000\n}\n")


def write(cfg: dict[str, str]) -> bool:
    """Schreibt die Caddyfile atomar. True, wenn sich der Inhalt geändert hat."""
    text = render(cfg)
    target = settings.caddy_conf_dir / "Caddyfile"
    try:
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=settings.caddy_conf_dir, prefix=".Caddyfile.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def sync(cfg: dict[str, str]) -> None:
    """Beim Start: gespeicherten Modus und Datei auf dem Datenträger in Einklang bringen."""
    if not available():
        return
    try:
        if write(cfg):
            log.info("Caddyfile aktualisiert (Modus %s)", cfg.get("tls_mode"))
    except (ValueError, OSError) as exc:
        log.warning("Caddyfile nicht geschrieben: %s", exc)


# --- Zertifikate prüfen ------------------------------------------------------

def _name(rdns, oid) -> str:
    attrs = rdns.get_attributes_for_oid(oid)
    return attrs[0].value if attrs else ""


def inspect(host: str, connect_host: str | None = None, port: int = 443) -> dict:
    """Liest das Zertifikat, das der Proxy für host ausliefert, und prüft die Vertrauenswürdigkeit."""
    target = connect_host or settings.proxy_host
    info: dict = {"host": host, "ok": False, "trusted": False, "error": ""}
    try:
        verified = ssl.create_default_context()
        trusted = True
        try:
            with socket.create_connection((target, port), timeout=5) as sock, \
                    verified.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        except ssl.SSLCertVerificationError:
            trusted = False
            loose = ssl.create_default_context()
            loose.check_hostname, loose.verify_mode = False, ssl.CERT_NONE
            with socket.create_connection((target, port), timeout=5) as sock, \
                    loose.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        cert = x509.load_der_x509_certificate(der)
        issuer = cert.issuer
        info.update(
            ok=True, trusted=trusted,
            issuer=_name(issuer, x509.NameOID.ORGANIZATION_NAME) or _name(issuer, x509.NameOID.COMMON_NAME),
            issuer_cn=_name(issuer, x509.NameOID.COMMON_NAME),
            subject=_name(cert.subject, x509.NameOID.COMMON_NAME),
            not_after=cert.not_valid_after_utc.astimezone(timezone.utc).replace(tzinfo=None),
            fingerprint=":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256())),
            self_signed=cert.issuer == cert.subject or "local" in _name(issuer, x509.NameOID.COMMON_NAME).lower(),
        )
    except (OSError, ssl.SSLError, ValueError) as exc:
        info["error"] = f"Der Proxy ist nicht erreichbar oder liefert kein Zertifikat ({exc})"
    return info


def dns_check(host: str) -> dict:
    """Auf welche Adressen zeigt die Domain, und passt das zur öffentlichen IP des Servers?"""
    try:
        ips = sorted({r[4][0] for r in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except OSError:
        return {"host": host, "ips": [], "resolves": False, "matches": None}
    expected = settings.public_ips
    return {"host": host, "ips": ips, "resolves": True,
            "matches": (any(ip in expected for ip in ips) if expected else None)}


def root_cert_path() -> Path | None:
    path = settings.caddy_data_dir / "caddy" / "pki" / "authorities" / "local" / "root.crt"
    return path if path.exists() else None
