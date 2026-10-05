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

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
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
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082")
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
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or getattr(ip, "is_site_local", False)):
            raise BlockedAddress(f"„{host}“ zeigt auf eine interne Adresse ({ip}) und ist hier nicht erlaubt.")


def fetch(url: str, *, guard: bool, accept: str = "*/*") -> tuple[int, bytes, str]:
    """Holt eine Adresse (höchstens 3 Weiterleitungen, jede geprüft). Gibt (Status, Inhalt, Content-Type)."""
    headers = {"User-Agent": USER_AGENT.format(settings.portal_base_url), "Accept": accept}
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, headers=headers) as client:
        for _ in range(4):
            if guard:
                check_public_url(url)
            with client.stream("GET", url) as resp:
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


# --- Zwischenspeicher ----------------------------------------------------------------

_last_prune = {"at": 0.0}


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
    folder.mkdir(exist_ok=True)
    tmp = folder / (key + ".tmp")
    tmp.write_bytes(ctype.encode("ascii", "ignore")[:100] + b"\n" + body)
    os.replace(tmp, folder / key)
    if time.time() - _last_prune["at"] > 600:
        _last_prune["at"] = time.time()
        prune(limit_mb)


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
