"""Karten: Layer-Konfiguration für MapLibre, Kachel-/WMS-/WFS-Proxy mit Zwischenspeicher, Dienstabfrage.

Arten von Layern
  xyz     Kachelvorlage mit {z}/{x}/{y} (auch WMTS im REST-Stil, z. B. basemap.de)
  wms     WMS 1.1.1/1.3.0 (auch WMS-T mit Zeitdimension), Kacheln über GetMap in EPSG:3857
  wfs     WFS 1.1/2.0, Objekte als GeoJSON für den aktuellen Ausschnitt
  geojson feste GeoJSON-Datei
  style   MapLibre-Stil (Vektorkarte, z. B. basemap.de Vektor) – wird immer direkt geladen

Jeder Systemlayer wird wahlweise über das Portal (Proxy, mit Zwischenspeicher, ohne IP-Adressen an Dritte)
oder direkt beim Anbieter geladen. Eigene Layer von Benutzer:innen laufen immer über den Proxy, aber nur mit
einer vom Server signierten Beschreibung und mit Schutz vor Zugriffen ins interne Netz (SSRF).
"""

import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from itsdangerous import BadSignature, URLSafeSerializer

from .config import settings
from .db import MapLayer

KINDS = {"xyz": "Kacheln (XYZ / WMTS)", "wms": "WMS / WMS-T", "wfs": "WFS (Objekte)", "geojson": "GeoJSON-Datei",
         "style": "Vektorkarte (MapLibre-Stil)"}
ROLES = {"base": "Grundkarte", "overlay": "Überlagerung"}
FORMATS = ["image/png", "image/jpeg", "image/png8", "image/webp"]
USER_AGENT = "VerwaltungsPortal-Karten/1.0 (+{})"
MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = httpx.Timeout(20.0, connect=6.0)
TILE_TIMEOUT = httpx.Timeout(8.0, connect=4.0)      # Kacheln: lieber leer lassen als den Server blockieren
MAX_PARALLEL = 8                                    # gleichzeitige Abrufe beim Anbieter (alle Layer zusammen)
MAX_QUEUE = 200                                     # mehr wartende Abrufe → sofort leere Kachel
QUEUE_WAIT = 6.0                                    # länger gewartet → nicht mehr abrufen (längst weitergezoomt)
FAIL_SECONDS = 60                                   # fehlgeschlagene Adressen so lange nicht erneut abrufen
MAX_WFS_SPAN = 300_000                              # WFS nur für Ausschnitte bis 300 km Kantenlänge
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")
_signer = URLSafeSerializer(str(settings.secret_key), salt="map-custom-layer")


# --- Layer-Beschreibung für den Browser ---------------------------------------------

def _split_time(values: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,\n]+", values or "") if v.strip()][:2000]


def system_config(layer: MapLayer) -> dict:
    """Beschreibung eines Systemlayers für map-core.js (ohne interne Felder)."""
    cfg = {"id": f"s{layer.id}", "name": layer.name, "kind": layer.kind, "role": layer.role,
           "category": layer.category or ("Grundkarten" if layer.role == "base" else "Fachdaten"),
           "description": layer.description, "attribution": layer.attribution, "opacity": layer.opacity,
           "minzoom": layer.min_zoom, "maxzoom": layer.max_zoom, "tileSize": layer.tile_size,
           "visible": layer.default_visible, "color": layer.color, "featureInfo": layer.feature_info and layer.kind == "wms",
           "times": _split_time(layer.time_values), "time": layer.time_default, "legend": ""}
    base = f"/map/l/{layer.id}"
    if layer.kind == "style":
        cfg["style"] = layer.url
    elif layer.proxy:
        cfg["tiles"] = {"xyz": base + "/{z}/{x}/{y}", "wms": base + "/wms?bbox={bbox-epsg-3857}"}.get(layer.kind)
        cfg["data"] = {"wfs": base + "/wfs", "geojson": base + "/geojson"}.get(layer.kind)
        cfg["info"] = base + "/info" if cfg["featureInfo"] else ""
        cfg["legend"] = base + "/legend" if layer.legend_url or layer.kind == "wms" else ""
    else:
        cfg["tiles"] = layer.url if layer.kind == "xyz" else wms_template(layer) if layer.kind == "wms" else None
        cfg["data"] = layer.url if layer.kind == "geojson" else None
        cfg["wfsDirect"] = wfs_direct(layer) if layer.kind == "wfs" else None
        cfg["legend"] = layer.legend_url or (legend_url(layer) if layer.kind == "wms" else "")
        cfg["info"] = ""
    return cfg


def custom_config(defn: dict, token: str, opacity: float = 1.0) -> dict:
    """Eigener Layer (signiert) – läuft über /map/c/<token>/…"""
    base = f"/map/c/{token}"
    kind = defn.get("kind")
    return {"id": "c" + hashlib.sha1(token.encode()).hexdigest()[:10], "name": defn.get("name") or "Eigener Layer",
            "kind": kind, "role": "overlay", "category": "Eigene Layer", "description": defn.get("url", ""),
            "attribution": html.escape(defn.get("attribution", "")), "opacity": opacity, "minzoom": 0, "maxzoom": 22,
            "tileSize": 256, "visible": True, "color": defn.get("color") or "#7b2cbf",
            "featureInfo": kind == "wms", "times": defn.get("times") or [], "time": defn.get("time", ""),
            "tiles": {"xyz": base + "/{z}/{x}/{y}", "wms": base + "/wms?bbox={bbox-epsg-3857}"}.get(kind),
            "data": base + "/wfs" if kind == "wfs" else None, "info": base + "/info" if kind == "wms" else "",
            "legend": base + "/legend" if kind == "wms" else "", "custom": defn, "token": token}


def clean_custom(raw: dict) -> dict | None:
    """Eigene Layerbeschreibung prüfen (nur http(s), bekannte Arten, Längen begrenzt)."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    url = str(raw.get("url") or "").strip()[:1000]
    if kind not in ("xyz", "wms", "wfs") or not re.match(r"^https?://[^\s/]+", url):
        return None
    if kind == "xyz" and not all(k in url for k in ("{z}", "{x}", "{y}")):
        return None
    out = {"kind": kind, "url": url, "name": str(raw.get("name") or "")[:200],
           "layers": str(raw.get("layers") or "")[:1000], "styles": str(raw.get("styles") or "")[:200],
           "version": raw.get("version") if raw.get("version") in ("1.1.1", "1.3.0", "1.1.0", "2.0.0") else "",
           "format": raw.get("format") if raw.get("format") in FORMATS else "image/png",
           "attribution": str(raw.get("attribution") or "")[:300],
           "times": [str(t)[:40] for t in (raw.get("times") or [])][:2000] if isinstance(raw.get("times"), list) else [],
           "time": str(raw.get("time") or "")[:40], "color": raw.get("color") if re.match(r"^#[0-9a-fA-F]{6}$", str(raw.get("color") or "")) else "#7b2cbf",
           "swap_xy": bool(raw.get("swap_xy"))}
    if kind in ("wms", "wfs") and not out["layers"]:
        return None
    return out


def sign(defn: dict) -> str:
    return _signer.dumps(defn)


def unsign(token: str) -> dict | None:
    try:
        data = _signer.loads(token)
    except BadSignature:
        return None
    return clean_custom(data)


# --- URLs zu den Diensten -------------------------------------------------------------

def _with_params(url: str, params: dict) -> str:
    """Parameter an eine Dienstadresse hängen; vorhandene gleichnamige (Groß/klein egal) ersetzen."""
    parts = urlparse(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in {p.lower() for p in params}]
    return urlunparse(parts._replace(query=urlencode(keep + [(k, v) for k, v in params.items() if v is not None])))


def _wms_params(layers: str, styles: str, fmt: str, version: str, transparent: bool) -> dict:
    version = version or "1.3.0"
    return {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": version, "LAYERS": layers, "STYLES": styles or "",
            "FORMAT": fmt or "image/png", "TRANSPARENT": "TRUE" if transparent else "FALSE",
            ("CRS" if version == "1.3.0" else "SRS"): "EPSG:3857", "WIDTH": "256", "HEIGHT": "256"}


def wms_template(layer: MapLayer) -> str:
    url = _with_params(layer.url, _wms_params(layer.layers, layer.styles, layer.image_format, layer.version,
                                              layer.transparent))
    return url + "&BBOX={bbox-epsg-3857}"


def legend_url(layer: MapLayer) -> str:
    if layer.legend_url:
        return layer.legend_url
    first = (layer.layers or "").split(",")[0]
    return _with_params(layer.url, {"SERVICE": "WMS", "REQUEST": "GetLegendGraphic", "VERSION": layer.version or "1.3.0",
                                    "LAYER": first, "FORMAT": "image/png", "SLD_VERSION": "1.1.0"})


def wfs_direct(layer: MapLayer) -> str:
    return _wfs_url(layer.url, layer.layers, layer.version, None)


def _wfs_url(url: str, typename: str, version: str, bbox: str | None) -> str:
    version = version or "2.0.0"
    params = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": version,
              ("TYPENAMES" if version.startswith("2") else "TYPENAME"): typename,
              "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326",
              ("COUNT" if version.startswith("2") else "MAXFEATURES"): "5000"}
    if bbox:
        params["BBOX"] = bbox + ",EPSG:3857"
    return _with_params(url, params)


def upstream_url(spec: dict, action: str, query: dict) -> str | None:
    """Ziel-URL beim Anbieter für eine Proxy-Anfrage. spec: Felder eines Layers (system oder eigen)."""
    kind, url = spec["kind"], spec["url"]
    if action == "tile" and kind == "xyz":
        z, x, y = query["z"], query["x"], query["y"]
        return url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y)).replace(
            "{-y}", str((1 << z) - 1 - y))
    bbox = query.get("bbox", "")
    if action in ("wms", "info") and kind == "wms":
        if not re.fullmatch(r"-?[\d.]+(,-?[\d.e+-]+){3}", bbox):
            return None
        params = _wms_params(spec["layers"], spec.get("styles", ""), spec.get("format", "image/png"),
                             spec.get("version", ""), spec.get("transparent", True))
        params["BBOX"] = bbox
        if query.get("time"):
            params["TIME"] = query["time"][:60]
        if action == "info":
            version = params["VERSION"]
            params.update({"REQUEST": "GetFeatureInfo", "QUERY_LAYERS": spec["layers"], "INFO_FORMAT": "text/html",
                           ("I" if version == "1.3.0" else "X"): str(int(query.get("i", 128))),
                           ("J" if version == "1.3.0" else "Y"): str(int(query.get("j", 128))), "FEATURE_COUNT": "10"})
        return _with_params(url, params)
    if action == "legend" and kind == "wms":
        return spec.get("legend_url") or _with_params(url, {
            "SERVICE": "WMS", "REQUEST": "GetLegendGraphic", "VERSION": spec.get("version") or "1.3.0",
            "LAYER": spec["layers"].split(",")[0], "FORMAT": "image/png", "SLD_VERSION": "1.1.0"})
    if action == "wfs" and kind == "wfs":
        if bbox and not re.fullmatch(r"-?[\d.]+(,-?[\d.e+-]+){3}", bbox):
            return None
        return _wfs_url(url, spec["layers"], spec.get("version", ""), bbox or None)
    if action == "geojson" and kind == "geojson":
        return url
    return None


def layer_spec(layer: MapLayer) -> dict:
    return {"kind": layer.kind, "url": layer.url, "layers": layer.layers, "styles": layer.styles,
            "format": layer.image_format, "version": layer.version, "transparent": layer.transparent,
            "legend_url": layer.legend_url, "swap_xy": layer.swap_xy}


def custom_spec(defn: dict) -> dict:
    return {"kind": defn["kind"], "url": defn["url"], "layers": defn.get("layers", ""), "styles": defn.get("styles", ""),
            "format": defn.get("format", "image/png"), "version": defn.get("version", ""), "transparent": True,
            "legend_url": "", "swap_xy": defn.get("swap_xy", False)}


# --- Schutz vor Zugriffen ins interne Netz (nur für eigene Layer) -------------------

class BlockedAddress(Exception):
    pass


def check_public_url(url: str) -> None:
    """Nur http(s) zu öffentlichen Adressen – kein localhost, kein internes Netz, keine Docker-Dienste."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedAddress("Nur http- und https-Adressen sind erlaubt.")
    host = parts.hostname
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedAddress(f"Der Server „{host}“ ist nicht bekannt.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _internal(ip):
            raise BlockedAddress(f"„{host}“ zeigt auf eine interne Adresse ({ip}) und ist hier nicht erlaubt.")


def _internal(ip) -> bool:
    """Alles, was nicht global erreichbar ist (inkl. 100.64/10, IPv4 in IPv6 verpackt)."""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _check_peer(resp, url: str) -> None:
    """Nach dem Verbindungsaufbau die tatsächlich verbundene Adresse prüfen – schützt vor DNS-Rebinding
    (Name zeigt bei der Prüfung nach außen, beim Verbinden nach innen)."""
    if urllib.request.getproxies().get(urlparse(url).scheme):
        return  # über einen eingerichteten Proxy: der löst den Namen auf, die Vorabprüfung muss genügen
    stream = resp.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream is not None else None
    if not addr:
        raise BlockedAddress("Die Gegenstelle ließ sich nicht prüfen.")
    if _internal(ipaddress.ip_address(addr[0])):
        raise BlockedAddress(f"„{urlparse(url).hostname}“ zeigt auf eine interne Adresse und ist hier nicht erlaubt.")


def fetch(url: str, *, guard: bool, accept: str = "*/*", timeout: httpx.Timeout = TIMEOUT) -> tuple[int, bytes, str]:
    """Holt eine Adresse (höchstens 3 Weiterleitungen, jede geprüft). Gibt (Status, Inhalt, Content-Type)."""
    headers = {"User-Agent": USER_AGENT.format(settings.portal_base_url), "Accept": accept}
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(4):
            if guard:
                check_public_url(url)
            with client.stream("GET", url) as resp:
                if guard:
                    _check_peer(resp, url)
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise httpx.HTTPError("Antwort zu groß")
                    chunks.append(chunk)
                return resp.status_code, b"".join(chunks), resp.headers.get("content-type", "")
    raise httpx.HTTPError("Zu viele Weiterleitungen")


# --- Abrufe begrenzen -----------------------------------------------------------------
# Beim Herauszoomen fordert der Browser Dutzende Kacheln auf einmal an, und große Ausschnitte rendern WMS-Dienste
# langsam. Früher belegte jede wartende Kachel einen Arbeitsplatz des Servers (und eine Datenbankverbindung),
# bis das ganze Portal stand. Jetzt laufen Abrufe in einem eigenen kleinen Pool (MAX_PARALLEL), das Warten kostet
# keinen Arbeitsplatz, gleiche Adressen werden nur einmal geholt, Fehlschläge kurz gemerkt, und was zu lange in
# der Warteschlange lag (der Browser hat längst weitergezoomt), wird gar nicht mehr abgerufen.

class Busy(Exception):
    """Kein Abruf möglich (Warteschlange voll oder zu lange gewartet) – die Anfrage bekommt eine leere Antwort."""


_pool = ThreadPoolExecutor(MAX_PARALLEL, thread_name_prefix="map-fetch")
_inflight: dict[str, asyncio.Future] = {}
_queued = {"n": 0}
_failed: dict[str, float] = {}


def recently_failed(key: str) -> bool:
    until = _failed.get(key)
    if until and until > time.monotonic():
        return True
    _failed.pop(key, None)
    return False


def mark_failed(key: str) -> None:
    if len(_failed) > 5000:
        now = time.monotonic()
        for k in [k for k, v in _failed.items() if v <= now] or list(_failed)[:2500]:
            _failed.pop(k, None)
    _failed[key] = time.monotonic() + FAIL_SECONDS


def _fetch_if_fresh(queued_at: float, url: str, guard: bool, timeout: httpx.Timeout) -> tuple[int, bytes, str]:
    if time.monotonic() - queued_at > QUEUE_WAIT:
        raise Busy()
    return fetch(url, guard=guard, timeout=timeout)


async def queued_fetch(key: str, url: str, *, guard: bool, timeout: httpx.Timeout = TIMEOUT) -> tuple[int, bytes, str]:
    """fetch() über den begrenzten Pool. Läuft dieselbe Adresse schon, wird auf deren Ergebnis gewartet.
    Wirft Busy bei voller Warteschlange; Fehler des Abrufs (httpx.HTTPError, BlockedAddress) gehen durch."""
    running = _inflight.get(key)
    if running is None:
        if _queued["n"] >= MAX_QUEUE:
            raise Busy()
        loop = asyncio.get_running_loop()
        running = loop.run_in_executor(_pool, _fetch_if_fresh, time.monotonic(), url, guard, timeout)
        _inflight[key] = running
        _queued["n"] += 1

        def done(_f, key=key):
            _inflight.pop(key, None)
            _queued["n"] -= 1
        running.add_done_callback(done)
    return await asyncio.shield(running)


def bbox_span(bbox: str) -> float:
    """Größere Kantenlänge eines Ausschnitts „minx,miny,maxx,maxy“ (EPSG:3857, Meter)."""
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
    except ValueError:
        return 0.0
    return max(abs(x1 - x0), abs(y1 - y0))


# --- Zwischenspeicher ----------------------------------------------------------------

_last_prune = {"at": 0.0}
_prune_lock = threading.Lock()


def cache_dir() -> Path:
    path = settings.data_dir / "mapcache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_get(key: str, max_age_hours: int) -> tuple[bytes, str] | None:
    if max_age_hours <= 0:
        return None
    path = cache_dir() / key[:2] / key
    try:
        if time.time() - path.stat().st_mtime > max_age_hours * 3600:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    ctype, _, body = raw.partition(b"\n")
    return body, ctype.decode("ascii", "ignore")


def cache_put(key: str, body: bytes, ctype: str, limit_mb: int) -> None:
    folder = cache_dir() / key[:2]
    tmp = folder / f"{key}.{secrets.token_hex(4)}.tmp"     # eigener Name je Schreibvorgang (parallele Anfragen)
    try:
        folder.mkdir(exist_ok=True)
        tmp.write_bytes(ctype.encode("ascii", "ignore")[:100] + b"\n" + body)
        os.replace(tmp, folder / key)
    except OSError:
        tmp.unlink(missing_ok=True)   # Zwischenspeicher ist nur eine Beschleunigung – Fehler nicht weiterreichen
        return
    if time.time() - _last_prune["at"] > 600:
        _last_prune["at"] = time.time()
        # Aufräumen durchläuft den ganzen Ordner – nicht in der Anfrage, sondern nebenher
        threading.Thread(target=_prune_once, args=(limit_mb,), name="mapcache-prune", daemon=True).start()


def _prune_once(limit_mb: int) -> None:
    if not _prune_lock.acquire(blocking=False):
        return
    try:
        prune(limit_mb)
    except OSError:
        pass
    finally:
        _prune_lock.release()


def cache_stats() -> tuple[int, int]:
    count = size = 0
    for root, _dirs, files in os.walk(cache_dir()):
        for name in files:
            try:
                size += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                pass
    return count, size


def prune(limit_mb: int) -> int:
    """Älteste Einträge löschen, bis der Speicher unter die Grenze fällt."""
    entries = []
    for root, _dirs, files in os.walk(cache_dir()):
        for name in files:
            p = os.path.join(root, name)
            try:
                st = os.stat(p)
                entries.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
    total, limit, removed = sum(e[1] for e in entries), limit_mb * 1024 * 1024, 0
    for _mtime, size, p in sorted(entries):
        if total <= limit:
            break
        try:
            os.remove(p)
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


def clear_cache(prefix: str = "") -> int:
    removed = 0
    for root, _dirs, files in os.walk(cache_dir()):
        for name in files:
            if not prefix or name.startswith(prefix):
                try:
                    os.remove(os.path.join(root, name))
                    removed += 1
                except OSError:
                    pass
    return removed


def cache_key(scope: str, url: str) -> str:
    return scope + "-" + hashlib.sha256(url.encode()).hexdigest()


# --- Dienst abfragen (GetCapabilities) ------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    return next((c for c in el if _local(c.tag) == name), None)


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el, name) -> str:
    c = _child(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def expand_time(extent: str, limit: int = 500) -> list[str]:
    """WMS-T-Zeitangabe in Einzelwerte: Liste „a,b,c“ oder Intervall „start/ende/Periode“.
    Das Format der Werte bleibt erhalten (Jahr, Jahr-Monat, Datum oder Zeitpunkt)."""
    from datetime import datetime, timedelta

    values: list[str] = []
    for part in (extent or "").split(","):
        part = part.strip()
        if "/" not in part:
            if part:
                values.append(part)
            continue
        try:
            start, end, period = part.split("/")
        except ValueError:
            continue
        m = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", period)
        if not m or not any(m.groups()):
            values.extend([start, end])
            continue
        years, months, weeks, days, hours, minutes = (int(g or 0) for g in m.groups())
        if re.fullmatch(r"\d{4}", start):
            fmt, parse = "%Y", lambda v: datetime(int(v[:4]), 1, 1)
        elif re.fullmatch(r"\d{4}-\d{2}", start):
            fmt, parse = "%Y-%m", lambda v: datetime(int(v[:4]), int(v[5:7]), 1)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            fmt, parse = "%Y-%m-%d", lambda v: datetime.fromisoformat(v[:10])
        else:
            fmt, parse = "%Y-%m-%dT%H:%M:%SZ", lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        try:
            cur, stop = parse(start), parse(end)
        except ValueError:
            values.extend([start, end])
            continue
        while cur <= stop and len(values) < limit:
            values.append(cur.strftime(fmt))
            if years or months:
                month = cur.month - 1 + months + 12 * years
                cur = cur.replace(year=cur.year + month // 12, month=month % 12 + 1)
            else:
                cur += timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)
    return values[:limit]


def parse_capabilities(xml: bytes, kind: str) -> dict:
    """Liest Dienstname und Layer aus GetCapabilities (WMS, WFS oder WMTS)."""
    root = ET.fromstring(xml)
    tag = _local(root.tag)
    result = {"type": "", "title": "", "version": root.get("version", ""), "layers": []}
    if tag in ("WMS_Capabilities", "WMT_MS_Capabilities"):
        result["type"] = "wms"
        service = _child(root, "Service")
        result["title"] = _text(service, "Title")
        capability = _child(root, "Capability")

        def walk(el, depth=0):
            for lyr in _children(el, "Layer"):
                name = _text(lyr, "Name")
                if name:
                    dims = [d for d in _children(lyr, "Dimension") + _children(lyr, "Extent") if (d.get("name") or "").lower() == "time"]
                    times = expand_time((dims[0].text or "") if dims else "")
                    default = dims[0].get("default", "") if dims else ""
                    legend = ""
                    for st in _children(lyr, "Style"):
                        lg = _child(st, "LegendURL")
                        res = _child(lg, "OnlineResource") if lg is not None else None
                        if res is not None:
                            legend = res.get("{http://www.w3.org/1999/xlink}href", "")
                            break
                    result["layers"].append({"name": name, "title": _text(lyr, "Title") or name,
                                             "abstract": _text(lyr, "Abstract")[:500], "depth": depth,
                                             "queryable": lyr.get("queryable") == "1", "times": times,
                                             "time": default, "legend": legend})
                walk(lyr, depth + 1)
        if capability is not None:
            walk(capability)
    elif tag == "WFS_Capabilities":
        result["type"] = "wfs"
        info = _child(root, "ServiceIdentification")
        result["title"] = _text(info, "Title") if info is not None else _text(_child(root, "Service"), "Title")
        ftl = _child(root, "FeatureTypeList")
        for ft in _children(ftl, "FeatureType") if ftl is not None else []:
            result["layers"].append({"name": _text(ft, "Name"), "title": _text(ft, "Title") or _text(ft, "Name"),
                                     "abstract": _text(ft, "Abstract")[:500], "depth": 0, "times": [], "time": ""})
    elif tag == "Capabilities":  # WMTS
        result["type"] = "xyz"
        info = _child(root, "ServiceIdentification")
        result["title"] = _text(info, "Title") if info is not None else ""
        contents = _child(root, "Contents")
        matrix_sets = {}
        for tms in _children(contents, "TileMatrixSet") if contents is not None else []:
            ident = _text(tms, "Identifier")
            crs = _text(tms, "SupportedCRS")
            matrix_sets[ident] = crs
        for lyr in _children(contents, "Layer") if contents is not None else []:
            ident = _text(lyr, "Identifier")
            sets = [_text(link, "TileMatrixSet") for link in _children(lyr, "TileMatrixSetLink")]
            merc = next((s for s in sets if "3857" in matrix_sets.get(s, "") or "900913" in matrix_sets.get(s, "")
                         or "GoogleMaps" in s or "WEBMERCATOR" in s.upper()), None)
            res = next((r for r in _children(lyr, "ResourceURL") if r.get("resourceType") == "tile"), None)
            style = next((_text(st, "Identifier") for st in _children(lyr, "Style")), "default")
            template = ""
            if res is not None and merc:
                template = (res.get("template", "").replace("{TileMatrixSet}", merc).replace("{Style}", style)
                            .replace("{TileMatrix}", "{z}").replace("{TileRow}", "{y}").replace("{TileCol}", "{x}"))
            result["layers"].append({"name": ident, "title": _text(lyr, "Title") or ident,
                                     "abstract": _text(lyr, "Abstract")[:500], "depth": 0, "template": template,
                                     "times": [], "time": "", "mercator": bool(merc)})
    else:
        raise ValueError("Unbekannte Antwort – ist das wirklich eine WMS-, WFS- oder WMTS-Adresse?")
    return result


def capabilities_url(url: str, kind: str) -> str:
    service = {"wms": "WMS", "wfs": "WFS", "xyz": "WMTS", "wmts": "WMTS"}.get(kind, "WMS")
    return _with_params(url, {"SERVICE": service, "REQUEST": "GetCapabilities"})


def query_service(url: str, kind: str, guard: bool) -> dict:
    status, body, _ctype = fetch(capabilities_url(url, kind), guard=guard, accept="application/xml,text/xml")
    if status >= 400:
        raise ValueError(f"Der Dienst antwortet mit Fehler {status}.")
    return parse_capabilities(body, kind)


def csp_hosts(configs: list[dict]) -> list[str]:
    """Herkünfte direkt geladener Layer (für die Content-Security-Policy der Kartenseite)."""
    hosts = set()
    for cfg in configs:
        for key in ("tiles", "data", "style", "wfsDirect", "legend"):
            value = cfg.get(key)
            if value and isinstance(value, str) and value.startswith("http"):
                p = urlparse(value.replace("{", "").replace("}", ""))
                hosts.add(f"{p.scheme}://{p.netloc}")
    return sorted(hosts)


def extra_hosts(layers: list[MapLayer]) -> list[str]:
    hosts = []
    for layer in layers:
        for h in re.split(r"[\s,;]+", layer.extra_hosts or ""):
            if re.match(r"^https?://[A-Za-z0-9.-]+(:\d+)?$", h):
                hosts.append(h)
    return hosts


def view_state(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# --- Zeichnungen (Kartenbrowser) und Geometrien (Formulare) ----------------------------------

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _coord(p) -> list[float] | None:
    try:
        lon, lat = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [round(lon, 7), round(lat, 7)]


def clean_geometry(g, max_points: int = 5000) -> dict | None:
    """Nur Point, LineString und Polygon (äußerer Ring) mit gültigen WGS84-Koordinaten."""
    if not isinstance(g, dict):
        return None
    kind, coords = g.get("type"), g.get("coordinates")
    if kind == "Point":
        c = _coord(coords)
        return {"type": "Point", "coordinates": c} if c else None
    if kind == "LineString" and isinstance(coords, list):
        pts = [c for c in (_coord(p) for p in coords[:max_points]) if c]
        return {"type": "LineString", "coordinates": pts} if len(pts) >= 2 else None
    if kind == "Polygon" and isinstance(coords, list) and coords and isinstance(coords[0], list):
        pts = [c for c in (_coord(p) for p in coords[0][:max_points + 1]) if c]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        return {"type": "Polygon", "coordinates": [pts + [pts[0]]]} if len(pts) >= 3 else None
    return None


def clean_drawings(raw) -> list[dict]:
    out = []
    for f in raw[:500] if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        geom = clean_geometry(f.get("geometry"))
        if geom is None:
            continue
        props = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        color = str(props.get("color") or "")
        fid = str(f.get("id") or "")
        out.append({"type": "Feature", "id": fid if re.fullmatch(r"[0-9a-z]{1,16}", fid) else secrets.token_hex(4),
                    "geometry": geom,
                    "properties": {"name": " ".join(str(props.get("name") or "").split())[:200],
                                   "color": color if _COLOR_RE.match(color) else "#d62828",
                                   "kind": {"Point": "point", "LineString": "line", "Polygon": "polygon"}[geom["type"]]}})
    return out
