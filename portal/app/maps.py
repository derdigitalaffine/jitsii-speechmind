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
import math
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

KINDS = {"wmts": "WMTS (Dienst)", "xyz": "Kacheln (XYZ / WMTS)", "wms": "WMS / WMS-T", "wfs": "WFS (Objekte)", "geojson": "GeoJSON-Datei",
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
    elif layer.proxy or layer.kind == "wmts":
        cfg["tiles"] = {"wmts": base + "/{z}/{x}/{y}", "xyz": base + "/{z}/{x}/{y}", "wms": base + "/wms?bbox={bbox-epsg-3857}"}.get(layer.kind)
        cfg["data"] = {"wfs": base + "/wfs", "geojson": base + "/geojson"}.get(layer.kind)
        cfg["info"] = base + "/info" if cfg["featureInfo"] else ""
        cfg["legend"] = base + "/legend" if layer.legend_url or layer.kind == "wms" else ""
    else:
        cfg["tiles"] = layer.url if layer.kind == "xyz" else wms_template(layer) if layer.kind == "wms" else None
        cfg["data"] = layer.url if layer.kind == "geojson" else None
        cfg["wfsDirect"] = wfs_direct(layer) if layer.kind == "wfs" else None
        cfg["legend"] = layer.legend_url or (legend_url(layer) if layer.kind == "wms" else "")
        cfg["info"] = ""
    if layer.kind == 'wmts':
        service = clean_service(json.loads(layer.service_json or '{}'))
        cfg['tileSize'] = service.get('tile_size', 256)
        zooms = [int(z) for z in service.get('matrices', {})]
        if zooms: cfg.update(minzoom=max(layer.min_zoom,min(zooms)), maxzoom=min(layer.max_zoom,max(zooms)))
    return cfg


def custom_config(defn: dict, token: str, opacity: float = 1.0) -> dict:
    """Eigener Layer (signiert) – läuft über /map/c/<token>/…"""
    base = f"/map/c/{token}"
    kind = defn.get("kind")
    return {"id": "c" + hashlib.sha1(token.encode()).hexdigest()[:10], "name": defn.get("name") or "Eigener Layer",
            "kind": kind, "role": "overlay", "category": "Eigene Layer", "description": defn.get("url", ""),
            "attribution": html.escape(defn.get("attribution", "")), "opacity": opacity, "minzoom": min([int(z) for z in defn.get("service", {}).get("matrices", {})] or [0]), "maxzoom": max([int(z) for z in defn.get("service", {}).get("matrices", {})] or [22]),
            "tileSize": defn.get("service", {}).get("tile_size", 256), "visible": True, "color": defn.get("color") or "#7b2cbf",
            "featureInfo": kind == "wms", "times": defn.get("times") or [], "time": defn.get("time", ""),
            "tiles": {"wmts": base + "/{z}/{x}/{y}", "xyz": base + "/{z}/{x}/{y}", "wms": base + "/wms?bbox={bbox-epsg-3857}"}.get(kind),
            "data": base + "/wfs" if kind == "wfs" else None, "info": base + "/info" if kind == "wms" else "",
            "legend": base + "/legend" if kind == "wms" else "", "custom": defn, "token": token}


def clean_custom(raw: dict) -> dict | None:
    """Eigene Layerbeschreibung prüfen (nur http(s), bekannte Arten, Längen begrenzt)."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    url = str(raw.get("url") or "").strip()[:1000]
    if kind not in ("xyz", "wmts", "wms", "wfs") or not re.match(r"^https?://[^\s/]+", url):
        return None
    if kind == "xyz" and not all(k in url for k in ("{z}", "{x}", "{y}")):
        return None
    out = {"kind": kind, "url": url, "service": clean_service(raw.get("service", {})), "name": str(raw.get("name") or "")[:200],
           "layers": str(raw.get("layers") or "")[:1000], "styles": str(raw.get("styles") or "")[:200],
           "version": raw.get("version") if raw.get("version") in ("1.1.1", "1.3.0", "1.1.0", "2.0.0") else "",
           "format": raw.get("format") if raw.get("format") in FORMATS else "image/png",
           "attribution": str(raw.get("attribution") or "")[:300],
           "times": [str(t)[:40] for t in (raw.get("times") or [])][:2000] if isinstance(raw.get("times"), list) else [],
           "time": str(raw.get("time") or "")[:40], "color": raw.get("color") if re.match(r"^#[0-9a-fA-F]{6}$", str(raw.get("color") or "")) else "#7b2cbf",
           "swap_xy": bool(raw.get("swap_xy"))}
    if kind == "wmts" and (not out["layers"] or not out["service"].get("matrices") or not out["service"].get("matrix_set")): return None
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


def _wfs_url(url: str, typename: str, version: str, bbox: str | None, output_format="application/json", srs="urn:ogc:def:crs:OGC:1.3:CRS84") -> str:
    version = version or "2.0.0"
    params = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": version,
              ("TYPENAMES" if version.startswith("2") else "TYPENAME"): typename,
              "OUTPUTFORMAT": output_format, "SRSNAME": srs,
              ("COUNT" if version.startswith("2") else "MAXFEATURES"): "5000"}
    if bbox:
        params["BBOX"] = bbox + ",EPSG:3857"
    return _with_params(url, params)


def upstream_url(spec: dict, action: str, query: dict) -> str | None:
    """Ziel-URL beim Anbieter für eine Proxy-Anfrage. spec: Felder eines Layers (system oder eigen)."""
    kind, url = spec["kind"], spec["url"]
    service = spec.get("service", {})
    if action == "tile" and kind == "wmts":
        matrix = service.get("matrices", {}).get(str(query["z"]))
        if not matrix: return None
        values = {"TileMatrixSet": service.get("matrix_set"), "TileMatrix": matrix, "TileRow": query["y"], "TileCol": query["x"], "Style": spec.get("styles") or "default", "Layer": spec["layers"], "Time": query.get("time") or service.get("time", "")}
        if "{TileMatrix}" in url:
            for k, v in values.items(): url = url.replace("{" + k + "}", str(v))
            return url
        return _with_params(url, {"SERVICE":"WMTS", "REQUEST":"GetTile", "VERSION":"1.0.0", "LAYER":spec["layers"], "STYLE":values["Style"], "FORMAT":spec.get("format", "image/png"), "TILEMATRIXSET":values["TileMatrixSet"], "TILEMATRIX":matrix, "TILEROW":query["y"], "TILECOL":query["x"], "TIME": values["Time"] or None})
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
            params.update({"REQUEST": "GetFeatureInfo", "QUERY_LAYERS": service.get("query_layers") or spec["layers"], "INFO_FORMAT": service.get("info_format") or "text/html",
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
        return _wfs_url(url, spec["layers"], spec.get("version", ""), bbox or None, service.get("output_format", "application/json"), service.get("srs", "urn:ogc:def:crs:OGC:1.3:CRS84"))
    if action == "geojson" and kind == "geojson":
        return url
    return None


def layer_spec(layer: MapLayer) -> dict:
    return {"kind": layer.kind, "url": layer.url, "layers": layer.layers, "styles": layer.styles,
            "format": layer.image_format, "version": layer.version, "transparent": layer.transparent,
            "legend_url": layer.legend_url, "swap_xy": layer.swap_xy, "service": service_options(layer)}


def custom_spec(defn: dict) -> dict:
    return {"kind": defn["kind"], "url": defn["url"], "layers": defn.get("layers", ""), "styles": defn.get("styles", ""),
            "format": defn.get("format", "image/png"), "version": defn.get("version", ""), "transparent": True,
            "legend_url": "", "swap_xy": defn.get("swap_xy", False), "service": defn.get("service", {})}


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


def fetch(url: str, *, guard: bool, accept: str = "*/*", timeout: httpx.Timeout = TIMEOUT, content: bytes | None = None) -> tuple[int, bytes, str]:
    """Holt eine Adresse (höchstens 3 Weiterleitungen, jede geprüft). Gibt (Status, Inhalt, Content-Type)."""
    headers = {"User-Agent": USER_AGENT.format(settings.portal_base_url), "Accept": accept}
    if content is not None: headers["Content-Type"] = "text/xml; charset=utf-8"
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(4):
            if guard:
                check_public_url(url)
            with client.stream("POST" if content is not None else "GET", url, content=content) as resp:
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


async def queued_fetch(key: str, url: str, *, guard: bool, timeout: httpx.Timeout = TIMEOUT, content: bytes | None = None) -> tuple[int, bytes, str]:
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


def clean_service(raw):
    if not isinstance(raw, dict): return {}
    out = {k:str(raw[k])[:1000] for k in ('query_layers','matrix_set','time') if raw.get(k)}
    for k in ('info_format','output_format','srs'):
        if raw.get(k): out[k] = str(raw[k])[:100]
    matrices = raw.get('matrices', {})
    if isinstance(matrices, dict): out['matrices'] = {str(k):str(v)[:100] for k,v in matrices.items() if str(k).isdigit() and 0 <= int(k) <= 24}
    if raw.get('tile_size') in (256,512): out['tile_size'] = raw['tile_size']
    return out


def service_options(layer):
    try: return clean_service(json.loads(layer.service_json or '{}'))
    except (TypeError, ValueError): return {}


def exception_text(body):
    if not body.lstrip().startswith(b'<'): return ''
    try: root = ET.fromstring(body)
    except ET.ParseError: return ''
    if _local(root.tag) not in ('ServiceExceptionReport','ExceptionReport'): return ''
    return ' '.join((e.text or '').strip() for e in root.iter() if _local(e.tag) in ('ServiceException','ExceptionText'))[:1000] or 'Unbekannter Dienstfehler'


def parse_capabilities(xml: bytes, kind: str) -> dict:
    error = exception_text(xml)
    if error: raise ValueError(error)
    root = ET.fromstring(xml)
    tag = _local(root.tag)
    result = {'type':'', 'title':'', 'version':root.get('version',''), 'layers':[]}
    href = lambda e: e.get('{http://www.w3.org/1999/xlink}href','') if e is not None else ''
    if tag in ('WMS_Capabilities','WMT_MS_Capabilities'):
        result['type'] = 'wms'; result['title'] = _text(_child(root,'Service'),'Title')
        cap = _child(root,'Capability'); req = _child(cap,'Request')
        getmap = _child(req,'GetMap'); info = _child(req,'GetFeatureInfo')
        result['url'] = next((href(e) for e in getmap.iter() if _local(e.tag)=='OnlineResource'), '') if getmap is not None else ''
        formats = [(f.text or '').strip() for f in _children(info,'Format')] if info is not None else []
        info_format = next((f for f in ('application/json','text/html','text/plain','application/vnd.ogc.gml') if f in formats), formats[0] if formats else 'text/plain')
        def walk(el, depth=0, inherited=None):
            inherited = inherited or {'crs':[], 'times':[], 'time':'', 'queryable':False}
            for lyr in _children(el,'Layer'):
                local = dict(inherited)
                local['crs'] = list(dict.fromkeys(inherited['crs'] + [v for e in _children(lyr,'CRS') + _children(lyr,'SRS') for v in (e.text or '').split()]))
                if lyr.get('queryable') is not None: local['queryable'] = lyr.get('queryable') in ('1','true')
                dims = [d for d in _children(lyr,'Dimension') + _children(lyr,'Extent') if (d.get('name') or '').lower()=='time' and (d.text or '').strip()]
                if dims: local['times'] = expand_time(dims[0].text or ''); local['time'] = dims[0].get('default','') or (local['times'][-1] if local['times'] else '')
                name = _text(lyr,'Name')
                if name:
                    legend = next((href(e) for st in _children(lyr,'Style') for e in st.iter() if _local(e.tag)=='OnlineResource'), '')
                    result['layers'].append(dict(name=name,title=_text(lyr,'Title') or name, abstract=_text(lyr,'Abstract')[:500],depth=depth,legend=legend, **local,
                        supported=not local['crs'] or 'EPSG:3857' in local['crs'], service={'info_format':info_format,'query_layers':name} if local['queryable'] else {}))
                walk(lyr,depth+1,local)
        if cap is not None: walk(cap)
    elif tag == 'WFS_Capabilities':
        result['type'] = 'wfs'; result['title'] = _text(_child(root,'ServiceIdentification'),'Title') or _text(_child(root,'Service'),'Title')
        for op in root.iter():
            if _local(op.tag)=='Operation' and op.get('name')=='GetFeature':
                result['url'] = next((href(e) for e in op.iter() if _local(e.tag)=='Get'), '')
                all_formats = [(e.text or '').strip() for p in op.iter() if _local(p.tag)=='Parameter' and p.get('name')=='outputFormat' for e in p.iter() if _local(e.tag)=='Value']
                break
        else: all_formats = []
        ftl = _child(root,'FeatureTypeList')
        for ft in _children(ftl,'FeatureType') if ftl is not None else []:
            formats = [(e.text or '').strip() for f in _children(ft,'OutputFormats') for e in f] or all_formats
            output = next((f for f in formats if 'json' in f.lower()), next((f for f in formats if 'gml' in f.lower()), 'application/json'))
            crs = [_text(ft,k) for k in ('DefaultCRS','DefaultSRS') if _text(ft,k)] + [(e.text or '').strip() for e in _children(ft,'OtherCRS')+_children(ft,'OtherSRS')]
            srs = next((s for s in crs if '4326' in s), crs[0] if crs else 'urn:ogc:def:crs:OGC:1.3:CRS84')
            # CRS84 explicitly requests longitude/latitude where accepted; GML conversion also handles declared EPSG axes.
            result['layers'].append(dict(name=_text(ft,'Name'),title=_text(ft,'Title') or _text(ft,'Name'),abstract=_text(ft,'Abstract')[:500],depth=0,times=[],time='',service={'output_format':output,'srs':srs}))
    elif tag == 'Capabilities':
        result['type'] = 'wmts'; result['title'] = _text(_child(root,'ServiceIdentification'),'Title')
        result['url'] = next((href(e) for op in root.iter() if _local(op.tag)=='Operation' and op.get('name')=='GetTile' for e in op.iter() if _local(e.tag)=='Get'), '')
        contents = _child(root,'Contents'); matrix_sets = {}
        for tms in _children(contents,'TileMatrixSet') if contents is not None else []:
            crs = _text(tms,'SupportedCRS'); matrices = {}; tile_size = 256
            if not any(s in crs for s in ('3857','900913')): continue
            for tm in _children(tms,'TileMatrix'):
                try:
                    width,height=int(_text(tm,'MatrixWidth')),int(_text(tm,'MatrixHeight'))
                    z=round(math.log2(width)); size=int(_text(tm,'TileWidth'))
                    scale=float(_text(tm,'ScaleDenominator'))*.00028*size
                    origin=[float(v) for v in _text(tm,'TopLeftCorner').split()]
                    if width != 2**z or height != width or size not in (256,512) or int(_text(tm,'TileHeight')) != size or abs(scale*width-40075016.68557849)>500 or len(origin)!=2 or abs(origin[0]+20037508.342789244)>5 or abs(origin[1]-20037508.342789244)>5: continue
                    matrices[str(z)] = _text(tm,'Identifier'); tile_size=size
                except (ValueError, TypeError): continue
            if matrices: matrix_sets[_text(tms,'Identifier')] = dict(matrices=matrices,tile_size=tile_size)
        for lyr in _children(contents,'Layer') if contents is not None else []:
            ident=_text(lyr,'Identifier'); links=[_text(l,'TileMatrixSet') for l in _children(lyr,'TileMatrixSetLink')]
            selected=next((k for k in links if k in matrix_sets), '')
            style=next((_text(st,'Identifier') for st in _children(lyr,'Style') if st.get('isDefault')=='true'), next((_text(st,'Identifier') for st in _children(lyr,'Style')), 'default'))
            res=next((r for r in _children(lyr,'ResourceURL') if r.get('resourceType')=='tile'), None)
            url=res.get('template','') if res is not None else result['url']
            service=dict(matrix_sets.get(selected,{}), matrix_set=selected)
            dimension=next((d for d in _children(lyr,'Dimension') if _text(d,'Identifier').lower()=='time'),None)
            times=[(v.text or '').strip() for v in _children(dimension,'Value')] if dimension is not None else []
            time_default=_text(dimension,'Default') if dimension is not None else ''
            if time_default: service['time']=time_default
            result['layers'].append(dict(name=ident,title=_text(lyr,'Title') or ident,abstract=_text(lyr,'Abstract')[:500],depth=0,template=url,styles=style,format=_text(lyr,'Format') or 'image/png',supported=bool(selected and url),mercator=bool(selected),service=service,times=times,time=time_default))
    else: raise ValueError('Unbekannte Antwort – ist das eine WMS-, WFS- oder WMTS-Adresse?')
    return result


def capabilities_url(url: str, kind: str) -> str:
    service = {"wms": "WMS", "wfs": "WFS", "xyz": "WMTS", "wmts": "WMTS"}.get(kind, "WMS")
    return _with_params(url, {"SERVICE": service, "REQUEST": "GetCapabilities"})


def query_service(url: str, kind: str, guard: bool) -> dict:
    status, body, _ctype = fetch(capabilities_url(url, kind), guard=guard, accept="application/xml,text/xml")
    if status >= 400:
        raise ValueError(f"Der Dienst antwortet mit Fehler {status}.")
    result = parse_capabilities(body, kind)
    result["url"] = urljoin(url, result.get("url") or _with_params(url, {"REQUEST":None,"SERVICE":None,"VERSION":None}))
    return result


_capability_specs = {}
_capability_lock = threading.Lock()


def resolve_capability_spec(spec):
    """Older saved WMS/WFS capability URLs need the advertised operation endpoint."""
    if spec['kind'] not in ('wms','wfs'): return spec
    url=spec['url']
    params={k.lower():v.lower() for k,v in parse_qsl(urlparse(url).query)}
    if params.get('request') != 'getcapabilities' and not ('mapbender/php/wms.php' in url and 'layer_id' in params): return spec
    key=(url,spec['kind'])
    with _capability_lock:
        cached=_capability_specs.get(key)
        if not cached or cached[0] < time.monotonic():
            try: result=query_service(url,spec['kind'],False)
            except (ValueError,httpx.HTTPError,ET.ParseError) as exc:
                _capability_specs[key]=(time.monotonic()+60,None,str(exc));raise
            _capability_specs[key]=(time.monotonic()+3600,result,'')
        else:
            result=cached[1]
            if result is None: raise ValueError(cached[2])
    selected=next((l for l in result['layers'] if l['name']==spec['layers']),{})
    return {**spec,'url':result['url'],'service':{**selected.get('service',{}),**spec.get('service',{})}}


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
    """Nur Point, LineString und Polygon einschließlich Innenringen mit gültigen WGS84-Koordinaten."""
    if not isinstance(g, dict):
        return None
    kind, coords = g.get("type"), g.get("coordinates")
    if kind == "Point":
        c = _coord(coords)
        return {"type": "Point", "coordinates": c} if c else None
    if kind == "LineString" and isinstance(coords, list):
        pts = [c for c in (_coord(p) for p in coords[:max_points]) if c]
        return {"type": "LineString", "coordinates": pts} if len(pts) >= 2 else None
    if kind == "Polygon" and isinstance(coords, list) and coords:
        rings, total = [], 0
        for ring in coords:
            if not isinstance(ring, list): return None
            pts = [_coord(p) for p in ring]
            if any(p is None for p in pts): return None
            if len(pts) > 1 and pts[0] == pts[-1]: pts.pop()
            total += len(pts)
            if len(pts) < 3 or total > max_points: return None
            rings.append(pts + [pts[0]])
        return {"type": "Polygon", "coordinates": rings}
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


def normalize_features(body: bytes, swap=False):
    """Normalize GeoJSON or GML in WGS84/Web-Mercator; never silently plot an unknown CRS."""
    if exception_text(body): raise ValueError(exception_text(body))
    try:
        data = json.loads(body)
        if not isinstance(data,dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'),list): raise ValueError('Keine FeatureCollection')
    except (json.JSONDecodeError, UnicodeDecodeError):
        root = ET.fromstring(body)
        features=[]
        def coords(el, inherited=''):
            srs=el.get('srsName') or inherited
            if srs and not any(k in srs for k in ('4326','CRS84','3857')): raise ValueError('Nicht unterstütztes Koordinatensystem: ' + srs)
            pos = next((e for e in el.iter() if _local(e.tag) in ('posList','pos','coordinates')),None)
            if pos is None: return []
            srs=pos.get('srsName') or srs
            values=[float(x) for x in re.split(r'[,\s]+',(pos.text or '').strip()) if x]
            dim=int(pos.get('srsDimension') or el.get('srsDimension') or 2)
            points=[values[n:n+2] for n in range(0,len(values),dim)]
            for point in points:
                if len(point)!=2: raise ValueError('Ungültige Koordinaten')
                if '3857' in srs: point[:]=[point[0]/6378137*180/math.pi,(2*math.atan(math.exp(point[1]/6378137))-math.pi/2)*180/math.pi]
                elif '4326' in srs and ('urn:' in srs or '/def/crs/' in srs): point.reverse()
            return points
        members=[e for e in root.iter() if _local(e.tag) in ('member','featureMember')]
        for member in members[:5000]:
            if not len(member):continue
            obj=member[0]; geometry=None; props={}
            for prop in obj:
                ge=next((e for e in prop.iter() if _local(e.tag) in ('Point','LineString','Curve','Polygon','Surface','MultiSurface','MultiPolygon')),None)
                if ge is None: props[_local(prop.tag)]=' '.join(t.strip() for t in prop.itertext() if t.strip())[:4000];continue
                kind=_local(ge.tag); srs=ge.get('srsName','')
                if kind=='Point':
                    points=coords(ge,srs);geometry={'type':'Point','coordinates':points[0]} if points else None
                elif kind in ('LineString','Curve'): geometry={'type':'LineString','coordinates':coords(ge,srs)}
                else:
                    polygons=[]
                    for poly in ([ge] if kind in ('Polygon','Surface') else [e for e in ge.iter() if _local(e.tag) in ('Polygon','Surface')]):
                        rings=[coords(e,srs or poly.get('srsName','')) for e in poly.iter() if _local(e.tag)=='LinearRing']
                        if rings:polygons.append(rings)
                    if polygons:geometry={'type':'Polygon','coordinates':polygons[0]} if len(polygons)==1 else {'type':'MultiPolygon','coordinates':polygons}
            if geometry:features.append({'type':'Feature','id':obj.get('{http://www.opengis.net/gml/3.2}id') or obj.get('{http://www.opengis.net/gml}id'), 'geometry':geometry,'properties':props})
        data={'type':'FeatureCollection','features':features}
    crs=data.pop('crs',None)
    name=str((crs.get('properties') or {}).get('name','')) if isinstance(crs,dict) else ''
    if name and not any(k in name for k in ('4326','CRS84','3857')): raise ValueError('Nicht unterstütztes Koordinatensystem: '+name)
    def convert(c):
        if not isinstance(c,list): raise ValueError('Ungültige Geometrie')
        if c and isinstance(c[0],(int,float)):
            if len(c)<2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in c[:2]): raise ValueError('Ungültige Koordinaten')
            x,y=c[:2]
            if '3857' in name:
                if abs(x)>20037508.4 or abs(y)>20037508.4: raise ValueError('Koordinaten außerhalb Web-Mercator')
                x,y=x/6378137*180/math.pi,(2*math.atan(math.exp(y/6378137))-math.pi/2)*180/math.pi
            if swap: x,y=y,x
            if not (-180<=x<=180 and -90<=y<=90): raise ValueError('Der Dienst lieferte keine WGS84-Koordinaten.')
            return [x,y,*c[2:]]
        return [convert(v) for v in c]
    def geometry(g):
        if g is None:return None
        if not isinstance(g,dict): raise ValueError('Ungültige Geometrie')
        if g.get('type')=='GeometryCollection': return {**g,'geometries':[geometry(v) for v in g.get('geometries',[])]}
        return {**g,'coordinates':convert(g.get('coordinates'))}
    for f in data['features']:
        if not isinstance(f,dict) or f.get('type','Feature')!='Feature':raise ValueError('Ungültiges Objekt')
        f['geometry']=geometry(f.get('geometry'))
    return data
