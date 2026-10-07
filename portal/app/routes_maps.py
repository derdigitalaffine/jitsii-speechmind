"""Karten: Kartenbrowser (öffentlich und angemeldet), Kachel-Proxy, eigene Karten, Admin-Layerverwaltung."""

import json
import re
import secrets
from time import monotonic

import httpx
from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import maps as mp
from .db import MapLayer, SessionLocal, User, UserMap, get_settings, set_setting
from .main import (
    app, check_csrf, enabled_modules, flash, get_db, rate_limit, redirect, render, require,
    session_user,
)

map_user = require("maps")
maps_admin_user = require("maps_admin")
EMBED = "/karte-embed"


# --- Gemeinsame Kartendaten --------------------------------------------------------

def visible_layers(db: Session, user: User | None, purpose: str = "browser") -> list[MapLayer]:
    q = select(MapLayer).where(MapLayer.enabled.is_(True)).order_by(MapLayer.role, MapLayer.position, MapLayer.name)
    if purpose == "forms":
        q = q.where(MapLayer.in_forms.is_(True), MapLayer.role == "base")
    elif user is None:
        q = q.where(MapLayer.public.is_(True))
    return list(db.scalars(q))


def view_defaults(db: Session) -> dict:
    cfg = get_settings(db)

    def num(key, default):
        try:
            return float(cfg.get(key, default))
        except ValueError:
            return float(default)
    return {"center": [num("map_center_lon", "7.768"), num("map_center_lat", "49.493")], "zoom": num("map_zoom", "11")}


def map_bundle(db: Session, request: Request, user: User | None, state: dict | None = None,
               purpose: str = "browser") -> dict:
    """Alles, was map-core.js zum Aufbau braucht; setzt die CSP-Hosts für direkt geladene Layer."""
    layers = visible_layers(db, user, purpose)
    configs = [mp.system_config(layer) for layer in layers]
    state = state or {}
    for entry in state.get("custom", []) if isinstance(state.get("custom"), list) else []:
        defn = mp.clean_custom(entry.get("def") if isinstance(entry, dict) else None)
        if defn:
            cfg = mp.custom_config(defn, mp.sign(defn), float(entry.get("opacity", 1) or 1))
            configs.append(cfg)
    request.state.csp_hosts = mp.csp_hosts(configs) + mp.extra_hosts(layers)
    return {"layers": configs, "view": view_defaults(db), "state": state}


# --- Kartenbrowser ------------------------------------------------------------------

def _browser(request: Request, db: Session, embed: bool, saved: UserMap | None = None):
    user = None if embed else session_user(request, db)
    if embed and get_settings(db).get("maps_embed", "1") != "1":
        raise HTTPException(404, "Das Einbinden des Kartenbrowsers ist auf diesem Server abgeschaltet.")
    state = mp.view_state(saved.state_json) if saved else {}
    bundle = map_bundle(db, request, user, state)
    can_edit = bool(user and user.can("maps")) and not embed
    ctx = {"bundle": bundle, "saved": saved, "can_edit": can_edit, "embed": embed,
           "layout": "base_embed.html" if embed else "base.html", "R": EMBED if embed else "/karte",
           "embed_label": "Karte", "embed_icon": "fa-map-location-dot",
           "embed_public_path": request.url.path.replace(EMBED, "/karte", 1),
           "own": saved is not None and user is not None and saved.owner_id == user.id}
    response = render(request, "map.html", user, **ctx)
    if not user and "jsm_session" not in request.cookies:
        request.session.clear()   # Besucher ohne Anmeldung bekommen kein Cookie
    return response


@app.get("/karte")
def map_browser(request: Request, db: Session = Depends(get_db)):
    return _browser(request, db, False)


@app.get(EMBED)
def map_browser_embed(request: Request, db: Session = Depends(get_db)):
    return _browser(request, db, True)


def _shared(db: Session, token: str) -> UserMap:
    saved = db.scalar(select(UserMap).where(UserMap.public_token == token)) if len(token) > 10 else None
    if saved is None:
        raise HTTPException(404, "Diese Karte ist nicht (mehr) freigegeben.")
    return saved


@app.get("/karte/m/{token}")
def map_shared(request: Request, token: str, db: Session = Depends(get_db)):
    return _browser(request, db, False, _shared(db, token))


@app.get(EMBED + "/m/{token}")
def map_shared_embed(request: Request, token: str, db: Session = Depends(get_db)):
    return _browser(request, db, True, _shared(db, token))


# --- Proxy -------------------------------------------------------------------------------

async def _proxy(request: Request, spec: dict, scope: str, action: str, query: dict, cache_hours: int, guard: bool):
    """Holt eine Kachel/Antwort beim Anbieter (oder aus dem Zwischenspeicher). Wichtig: hier keine
    Datenbankverbindung und keinen Arbeitsplatz des Servers halten, während der Kartendienst rechnet – sonst
    blockieren langsame Dienste beim Herauszoomen das ganze Portal (siehe maps.queued_fetch)."""
    rate_limit(request, "map-proxy", limit=4000, window=300)
    url = mp.upstream_url(spec, action, query)
    if url is None:
        raise HTTPException(400, "Ungültige Kartenanfrage.")
    if action == "wfs" and mp.bbox_span(query.get("bbox", "")) > mp.MAX_WFS_SPAN:
        # Weit herausgezoomt: keine Objekte laden (sonst riesige Antworten)
        return JSONResponse({"type": "FeatureCollection", "features": [], "tooLarge": True},
                            headers={"Cache-Control": "private, max-age=60"})
    key = mp.cache_key(scope, url)
    cacheable = action in ("tile", "wms", "legend", "geojson")
    image_wanted = action in ("tile", "wms", "legend")
    hit = await run_in_threadpool(mp.cache_get, key, cache_hours) if cacheable else None
    if hit:
        body, ctype = hit
    else:
        status, body, ctype = 502, b"", ""
        if not mp.recently_failed(key):
            try:
                status, body, ctype = await mp.queued_fetch(
                    key, url, guard=guard, timeout=mp.TILE_TIMEOUT if image_wanted else mp.TIMEOUT)
            except mp.Busy:
                # Ausgelastet: sofort leer antworten, nicht merken – beim nächsten Verschieben neu versuchen
                if image_wanted:
                    return Response(mp.TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control": "no-store"})
                raise HTTPException(503, "Der Kartendienst ist gerade ausgelastet.", headers={"Retry-After": "5"}) from None
            except mp.BlockedAddress as exc:
                raise HTTPException(403, str(exc)) from exc
            except httpx.HTTPError:
                status = 502
            if status >= 500 or status == 429:
                mp.mark_failed(key)
        if status >= 400 or (image_wanted and not ctype.startswith("image/")):
            # Kaputte oder fehlende Kachel: unsichtbar statt Fehlerbild; Dienstfehler (XML) nicht weiterreichen
            if image_wanted:
                return Response(mp.TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control": "max-age=60"})
            if status >= 400:
                raise HTTPException(502, "Der Kartendienst antwortet nicht.")
        if status < 400 and cacheable and cache_hours > 0:
            await run_in_threadpool(_store, key, body, ctype)
    if action == "info":
        text = body.decode("utf-8", "replace")[:200_000]
        # Wird im Browser nur in einem abgeschotteten iframe (sandbox) angezeigt
        return JSONResponse({"html": text if "html" in ctype or "<" in text else f"<pre>{text}</pre>"})
    if action in ("wfs", "geojson"):
        data = await run_in_threadpool(_geojson, body, bool(spec.get("swap_xy")))
        if data is None:
            raise HTTPException(502, "Der Dienst lieferte kein GeoJSON.")
        return JSONResponse(data, headers={"Cache-Control": "private, max-age=60"})
    safe_type = ctype if ctype.startswith("image/") and "svg" not in ctype else "application/octet-stream"
    return Response(body, media_type=safe_type, headers={"Cache-Control": f"public, max-age={min(cache_hours, 24) * 3600 or 300}"})


def _store(key: str, body: bytes, ctype: str) -> None:
    mp.cache_put(key, body, ctype, _cache_mb())


def _geojson(body: bytes, swap: bool):
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return _swap(data) if swap else data


def _swap(data):
    """Koordinaten (Breite, Länge) → (Länge, Breite) für Dienste mit vertauschter Achsenreihenfolge."""
    def fix(c):
        if isinstance(c, list) and c and isinstance(c[0], (int, float)):
            return [c[1], c[0], *c[2:]]
        return [fix(x) for x in c] if isinstance(c, list) else c
    for feat in data.get("features", []) if isinstance(data, dict) else []:
        geom = feat.get("geometry") or {}
        if "coordinates" in geom:
            geom["coordinates"] = fix(geom["coordinates"])
    return data


_cache_limit = {"mb": 500, "at": 0.0}


def _cache_mb() -> int:
    """Grenze des Zwischenspeichers (Einstellung), kurz gemerkt statt je Kachel aus der Datenbank gelesen."""
    if monotonic() - _cache_limit["at"] > 60:
        with SessionLocal() as db:
            try:
                _cache_limit["mb"] = int(get_settings(db).get("map_cache_mb", "500") or 500)
            except ValueError:
                _cache_limit["mb"] = 500
        _cache_limit["at"] = monotonic()
    return _cache_limit["mb"]


def _system_layer(request: Request, layer_id: int) -> dict:
    """Layer prüfen und die für den Abruf nötigen Angaben lesen; die Datenbankverbindung ist danach wieder frei."""
    with SessionLocal() as db:
        layer = db.get(MapLayer, layer_id)
        if layer is None or not layer.proxy:
            raise HTTPException(404)
        if not layer.enabled or (not layer.public and not layer.in_forms):
            member = session_user(request, db)
            # ausgeschaltete Layer nur für Admins (Vorschau), nicht öffentliche nur für Angemeldete
            if member is None or (not layer.enabled and not member.is_admin):
                raise HTTPException(404)
        return {"spec": mp.layer_spec(layer), "scope": f"l{layer.id}", "cache_hours": layer.cache_hours,
                "min_zoom": layer.min_zoom or 0, "max_zoom": layer.max_zoom or 22, "feature_info": layer.feature_info}


@app.get("/map/l/{layer_id:int}/{z:int}/{x:int}/{y:int}")
async def map_tile(request: Request, layer_id: int, z: int, x: int, y: int):
    layer = await run_in_threadpool(_system_layer, request, layer_id)
    if not (0 <= z <= 24 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
        raise HTTPException(400)
    if z < layer["min_zoom"] or z > layer["max_zoom"]:
        # außerhalb der eingestellten Zoomstufen gar nicht erst beim Anbieter fragen
        return Response(mp.TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return await _proxy(request, layer["spec"], layer["scope"], "tile", {"z": z, "x": x, "y": y},
                  layer["cache_hours"], guard=False)


@app.get("/map/l/{layer_id:int}/{action}")
async def map_service(request: Request, layer_id: int, action: str, bbox: str = "", time: str = "", i: int = 128,
                j: int = 128):
    if action not in ("wms", "info", "legend", "wfs", "geojson"):
        raise HTTPException(404)
    layer = await run_in_threadpool(_system_layer, request, layer_id)
    if action == "info" and not layer["feature_info"]:
        raise HTTPException(404)
    return await _proxy(request, layer["spec"], layer["scope"], action,
                  {"bbox": bbox, "time": time, "i": i, "j": j}, layer["cache_hours"], guard=False)


@app.get("/map/c/{token}/{z:int}/{x:int}/{y:int}")
async def map_custom_tile(request: Request, token: str, z: int, x: int, y: int):
    defn = mp.unsign(token)
    if defn is None or not (0 <= z <= 24 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
        raise HTTPException(404)
    return await _proxy(request, mp.custom_spec(defn), "c", "tile", {"z": z, "x": x, "y": y}, 24, guard=True)


@app.get("/map/c/{token}/{action}")
async def map_custom_service(request: Request, token: str, action: str, bbox: str = "", time: str = "", i: int = 128,
                       j: int = 128):
    defn = mp.unsign(token)
    if defn is None or action not in ("wms", "info", "legend", "wfs"):
        raise HTTPException(404)
    return await _proxy(request, mp.custom_spec(defn), "c", action, {"bbox": bbox, "time": time, "i": i, "j": j},
                  24, guard=True)


# --- Eigene Layer und Karten (Recht „Karten“) --------------------------------------------

async def _capabilities(request: Request, guard: bool):
    """Dienst abfragen: Layerliste aus GetCapabilities (Benutzer: nur öffentliche Adressen, Admins: alle)."""
    rate_limit(request, "map-caps", limit=60)
    data = await request.form()
    url, kind = str(data.get("url", "")).strip()[:1000], str(data.get("kind", "wms"))
    if not re.match(r"^https?://", url):
        return JSONResponse({"ok": False, "error": "Bitte eine Adresse beginnend mit https:// angeben."})
    try:
        result = mp.query_service(url, kind, guard=guard)
    except mp.BlockedAddress as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    except (httpx.HTTPError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": f"Der Dienst konnte nicht gelesen werden: {exc}"})
    except Exception:  # kaputtes XML o. Ä.
        return JSONResponse({"ok": False, "error": "Die Antwort des Dienstes ist kein gültiges Capabilities-Dokument."})
    return JSONResponse({"ok": True, **result})


@app.post("/maps/capabilities", dependencies=[Depends(check_csrf)])
async def maps_capabilities(request: Request, user: User = Depends(map_user)):
    return await _capabilities(request, guard=True)


@app.post("/admin/maps/capabilities", dependencies=[Depends(check_csrf)])
async def admin_maps_capabilities(request: Request, user: User = Depends(maps_admin_user)):
    return await _capabilities(request, guard=False)   # Admins dürfen auch Dienste im eigenen Netz nutzen


@app.post("/maps/sign", dependencies=[Depends(check_csrf)])
async def maps_sign(request: Request, user: User = Depends(map_user)):
    """Eigenen Layer freigeben: prüft die Beschreibung und liefert die Konfiguration mit signiertem Proxy-Pfad."""
    data = await request.form()
    try:
        raw = json.loads(str(data.get("layer", "{}")))
    except ValueError:
        raw = None
    defn = mp.clean_custom(raw)
    if defn is None:
        return JSONResponse({"ok": False, "error": "Bitte Art, Adresse und – bei WMS/WFS – mindestens einen Layer angeben."})
    try:
        mp.check_public_url(defn["url"])
    except mp.BlockedAddress as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    return JSONResponse({"ok": True, "layer": mp.custom_config(defn, mp.sign(defn))})


def _clean_state(raw) -> dict:
    """Gespeicherter Kartenzustand: Ausschnitt, Grundkarte, Systemlayer (Sichtbarkeit, Transparenz, Zeit),
    eigene Layer (Beschreibung) – alles geprüft und begrenzt."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    try:
        lon, lat = float(raw["center"][0]), float(raw["center"][1])
        out["center"] = [max(-180, min(180, lon)), max(-85, min(85, lat))]
        out["zoom"] = max(0.0, min(22.0, float(raw.get("zoom", 10))))
        out["bearing"] = max(-360.0, min(360.0, float(raw.get("bearing", 0) or 0)))
        out["pitch"] = max(0.0, min(85.0, float(raw.get("pitch", 0) or 0)))
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    if isinstance(raw.get("base"), str):
        out["base"] = raw["base"][:20]
    layers = []
    for item in raw.get("layers", [])[:200] if isinstance(raw.get("layers"), list) else []:
        if isinstance(item, dict) and re.fullmatch(r"[sc][0-9a-f]{1,12}", str(item.get("id", ""))):
            layers.append({"id": item["id"], "visible": bool(item.get("visible")),
                           "opacity": max(0.0, min(1.0, float(item.get("opacity", 1) or 0))),
                           "time": str(item.get("time") or "")[:40]})
    out["layers"] = layers
    custom = []
    for item in raw.get("custom", [])[:30] if isinstance(raw.get("custom"), list) else []:
        defn = mp.clean_custom(item.get("def") if isinstance(item, dict) else None)
        if defn:
            custom.append({"def": defn, "opacity": max(0.0, min(1.0, float(item.get("opacity", 1) or 0)))})
    out["custom"] = custom
    out["drawings"] = mp.clean_drawings(raw.get("drawings"))
    return out


@app.get("/maps")
def maps_list(request: Request, user: User = Depends(map_user), db: Session = Depends(get_db)):
    items = list(db.scalars(select(UserMap).where(UserMap.owner_id == user.id).order_by(UserMap.updated_at.desc())))
    return render(request, "maps.html", user, items=items, state=mp.view_state)


@app.get("/maps/{map_id:int}")
def maps_open(request: Request, map_id: int, user: User = Depends(map_user), db: Session = Depends(get_db)):
    saved = db.get(UserMap, map_id)
    if saved is None or (saved.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Karte nicht gefunden.")
    return _browser(request, db, False, saved)


@app.post("/maps/save", dependencies=[Depends(check_csrf)])
async def maps_save(request: Request, user: User = Depends(map_user), db: Session = Depends(get_db)):
    data = await request.form()
    try:
        state = _clean_state(json.loads(str(data.get("state", "{}"))))
    except ValueError:
        return JSONResponse({"ok": False, "error": "Ungültiger Kartenzustand."})
    title = " ".join(str(data.get("title", "")).split())[:200]
    if not title:
        return JSONResponse({"ok": False, "error": "Bitte einen Titel angeben."})
    map_id = str(data.get("id", ""))
    saved = db.get(UserMap, int(map_id)) if map_id.isdigit() else None
    if saved is not None and saved.owner_id != user.id:
        saved = None   # fremde Karte: als eigene Kopie speichern
    if saved is None:
        saved = UserMap(owner_id=user.id, title=title)
        db.add(saved)
    saved.title = title
    saved.description = str(data.get("description", ""))[:2000]
    saved.state_json = json.dumps(state, ensure_ascii=False)
    if data.get("public") == "1" and not saved.public_token:
        saved.public_token = secrets.token_urlsafe(16)
    elif data.get("public") == "0":
        saved.public_token = None
    db.commit()
    return JSONResponse({"ok": True, "id": saved.id, "link": f"/maps/{saved.id}",
                         "public": f"/karte/m/{saved.public_token}" if saved.public_token else ""})


@app.post("/maps/{map_id:int}/public", dependencies=[Depends(check_csrf)])
def maps_public(request: Request, map_id: int, action: str = Form("enable"), user: User = Depends(map_user),
                db: Session = Depends(get_db)):
    saved = db.get(UserMap, map_id)
    if saved is None or saved.owner_id != user.id:
        raise HTTPException(404)
    saved.public_token = secrets.token_urlsafe(16) if action in ("enable", "renew") else None
    db.commit()
    flash(request, "Öffentlicher Link " + ({"enable": "erzeugt.", "renew": "erneuert – der alte gilt nicht mehr."}
                                            .get(action, "abgeschaltet.")))
    return redirect("/maps")


@app.post("/maps/{map_id:int}/delete", dependencies=[Depends(check_csrf)])
def maps_delete(request: Request, map_id: int, user: User = Depends(map_user), db: Session = Depends(get_db)):
    saved = db.get(UserMap, map_id)
    if saved is None or (saved.owner_id != user.id and not user.is_admin):
        raise HTTPException(404)
    db.delete(saved)
    db.commit()
    flash(request, f"Karte „{saved.title}“ gelöscht.")
    return redirect("/maps")


# --- Admin: Kartenlayer -------------------------------------------------------------------

LAYER_FIELDS_TEXT = {"name": 200, "category": 100, "description": 5000, "url": 2000, "layers": 1000, "styles": 255,
                     "version": 10, "attribution": 1000, "legend_url": 2000, "time_values": 50000,
                     "time_default": 60, "extra_hosts": 1000}
LAYER_FLAGS = ("transparent", "feature_info", "swap_xy", "proxy", "enabled", "public", "in_forms", "default_visible")


def _apply_layer(layer: MapLayer, data) -> str | None:
    for key, limit in LAYER_FIELDS_TEXT.items():
        setattr(layer, key, str(data.get(key, "") or "").strip()[:limit])
    layer.kind = data.get("kind") if data.get("kind") in mp.KINDS else "xyz"
    layer.role = data.get("role") if data.get("role") in mp.ROLES else "overlay"
    layer.image_format = data.get("image_format") if data.get("image_format") in mp.FORMATS else "image/png"
    color = str(data.get("color", ""))
    layer.color = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#e4572e"
    for key, lo, hi, default in (("tile_size", 128, 1024, 256), ("min_zoom", 0, 24, 0), ("max_zoom", 0, 24, 22),
                                 ("cache_hours", 0, 24 * 365, 168)):
        try:
            setattr(layer, key, max(lo, min(hi, int(data.get(key, default)))))
        except (TypeError, ValueError):
            setattr(layer, key, default)
    try:
        layer.opacity = max(0.0, min(1.0, float(str(data.get("opacity", "1")).replace(",", "."))))
    except ValueError:
        layer.opacity = 1.0
    for flag in LAYER_FLAGS:
        setattr(layer, flag, data.get(flag) == "1")
    if layer.kind == "style":
        layer.proxy = False
    if not layer.name:
        return "Bitte einen Namen angeben."
    if not re.match(r"^https?://", layer.url):
        return "Bitte die Adresse des Dienstes (http/https) angeben."
    if layer.kind == "xyz" and not all(k in layer.url for k in ("{z}", "{x}", "{y}")):
        return "Eine Kachelvorlage braucht {z}, {x} und {y} (WMTS: TileMatrix → {z}, TileRow → {y}, TileCol → {x})."
    if layer.kind in ("wms", "wfs") and not layer.layers:
        return "Bitte den Layer- bzw. Objektartnamen angeben (oder über „Dienst abfragen“ auswählen)."
    return None


def _user_layers(db: Session) -> list[dict]:
    """Eigene Layer aus gespeicherten Karten aller Personen (zum Übernehmen)."""
    seen, out = set(), []
    for saved in db.scalars(select(UserMap).order_by(UserMap.updated_at.desc()).limit(500)):
        for idx, entry in enumerate(mp.view_state(saved.state_json).get("custom", [])):
            defn = mp.clean_custom(entry.get("def") if isinstance(entry, dict) else None)
            if not defn:
                continue
            key = (defn["kind"], defn["url"], defn.get("layers"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"map": saved, "index": idx, "def": defn})
    return out


@app.get("/admin/maps")
def admin_maps(request: Request, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    layers = list(db.scalars(select(MapLayer).order_by(MapLayer.role, MapLayer.position, MapLayer.name)))
    count, size = mp.cache_stats()
    known = {(lyr.kind, lyr.url, lyr.layers) for lyr in layers}
    return render(request, "admin_maps.html", user, layers=layers, kinds=mp.KINDS, roles=mp.ROLES,
                  cfg=get_settings(db), cache_count=count, cache_size=size,
                  user_layers=[u for u in _user_layers(db) if (u["def"]["kind"], u["def"]["url"], u["def"]["layers"]) not in known],
                  saved_maps=db.scalar(select(func.count(UserMap.id))), maps_module="maps" in enabled_modules(),
                  bundle=map_bundle(db, request, user))


@app.post("/admin/maps/settings", dependencies=[Depends(check_csrf)])
def admin_maps_settings(request: Request, map_center_lat: str = Form(""), map_center_lon: str = Form(""),
                        map_zoom: str = Form("11"), map_cache_mb: str = Form("500"), maps_embed: str = Form(""),
                        maps_embed_origins: str = Form(""), geocoder_url: str = Form(""), geocoder_countries: str = Form("de"),
                        geocoder_contact: str = Form(""), geocoder_search_mode: str = Form("auto"),
                        geocoder_delay_ms: str = Form("300"), user: User = Depends(maps_admin_user),
                        db: Session = Depends(get_db)):
    try:
        lat, lon, zoom = float(map_center_lat.replace(",", ".")), float(map_center_lon.replace(",", ".")), float(map_zoom)
        cache = int(map_cache_mb)
        assert -85 <= lat <= 85 and -180 <= lon <= 180 and 0 <= zoom <= 20 and 10 <= cache <= 100000
    except (ValueError, AssertionError):
        flash(request, "Bitte gültige Werte angeben (Breite −85…85, Länge −180…180, Zoom 0…20, Speicher ab 10 MB).", "error")
        return redirect("/admin/maps#einstellungen")
    origins = [o.strip().rstrip("/") for o in re.split(r"[\s,;]+", maps_embed_origins) if o.strip()]
    geo_url = geocoder_url.strip().rstrip("/") or "https://nominatim.openstreetmap.org"
    if not re.match(r"^https?://[^\s/]+", geo_url):
        flash(request, "Die Adresse des Geocoders muss mit http:// oder https:// beginnen.", "error")
        return redirect("/admin/maps#einstellungen")
    try:
        delay = int(geocoder_delay_ms)
        assert 250 <= delay <= 5000 and geocoder_search_mode in ("auto", "live", "manual")
    except (ValueError, AssertionError):
        flash(request, "Bitte Suchmodus und Verzögerung von 250 bis 5000 ms prüfen.", "error")
        return redirect("/admin/maps#einstellungen")
    set_setting(db, "geocoder_search_mode", geocoder_search_mode)
    set_setting(db, "geocoder_delay_ms", str(delay))
    set_setting(db, "geocoder_url", geo_url[:300])
    set_setting(db, "geocoder_countries", ",".join(c for c in re.split(r"[\s,;]+", geocoder_countries.lower()) if re.fullmatch(r"[a-z]{2}", c)))
    set_setting(db, "geocoder_contact", geocoder_contact.strip()[:200])
    for key, value in (("map_center_lat", f"{lat:.5f}"), ("map_center_lon", f"{lon:.5f}"), ("map_zoom", f"{zoom:g}"),
                       ("map_cache_mb", str(cache)), ("maps_embed", "1" if maps_embed == "1" else "0"),
                       ("maps_embed_origins", " ".join(origins))):
        set_setting(db, key, value)
    db.commit()
    flash(request, "Karteneinstellungen gespeichert.")
    return redirect("/admin/maps#einstellungen")


def _layer_page(request: Request, db: Session, user: User, layer: MapLayer | None, values: dict | None = None):
    bundle = map_bundle(db, request, user)
    bundle["layers"] = [c for c in bundle["layers"] if c["role"] == "base" and c["id"] != f"s{layer.id if layer else 0}"]
    if layer is not None:   # Vorschau: dieser Layer (auch ausgeschaltet) über der Startgrundkarte
        cfg = mp.system_config(layer)
        cfg["visible"] = True
        if layer.role == "base":
            cfg["role"] = "overlay"
        bundle["layers"].append(cfg)
        request.state.csp_hosts = list(request.state.csp_hosts) + mp.csp_hosts([cfg]) + mp.extra_hosts([layer])
    return render(request, "admin_map_layer.html", user, layer=layer, v=values or {}, kinds=mp.KINDS, roles=mp.ROLES,
                  formats=mp.FORMATS, categories=sorted({c for c in db.scalars(select(MapLayer.category)) if c}),
                  bundle=bundle)


@app.get("/admin/maps/new")
def admin_map_new(request: Request, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    return _layer_page(request, db, user, None, {"kind": "wms", "role": "overlay", "proxy": True, "enabled": True,
                                                 "public": True, "transparent": True, "opacity": 1.0,
                                                 "cache_hours": 168, "tile_size": 256, "max_zoom": 22,
                                                 "min_zoom": 0, "color": "#e4572e", "image_format": "image/png",
                                                 "version": "1.3.0"})


@app.get("/admin/maps/{layer_id:int}")
def admin_map_edit(request: Request, layer_id: int, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    layer = db.get(MapLayer, layer_id)
    if layer is None:
        raise HTTPException(404)
    return _layer_page(request, db, user, layer)


@app.post("/admin/maps/save", dependencies=[Depends(check_csrf)])
async def admin_map_save(request: Request, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    data = await request.form()
    layer_id = str(data.get("id", ""))
    layer = db.get(MapLayer, int(layer_id)) if layer_id.isdigit() else None
    is_new = layer is None
    if is_new:
        layer = MapLayer(position=(db.scalar(select(func.max(MapLayer.position))) or 0) + 1)
    error = _apply_layer(layer, data)
    if error:
        db.rollback()
        flash(request, error, "error")
        return _layer_page(request, db, user, None if is_new else db.get(MapLayer, layer.id), dict(data))
    if is_new:
        db.add(layer)
    db.commit()
    mp.clear_cache(f"l{layer.id}-")   # geänderte Einstellungen: alte Kacheln verwerfen
    flash(request, f"Layer „{layer.name}“ gespeichert.")
    return redirect(f"/admin/maps/{layer.id}" if data.get("stay") == "1" else "/admin/maps")


@app.post("/admin/maps/{layer_id:int}/toggle", dependencies=[Depends(check_csrf)])
def admin_map_toggle(request: Request, layer_id: int, field: str = Form(...), user: User = Depends(maps_admin_user),
                     db: Session = Depends(get_db)):
    layer = db.get(MapLayer, layer_id)
    if layer is None or field not in ("enabled", "public", "in_forms", "default_visible", "proxy"):
        raise HTTPException(404)
    if field == "proxy" and layer.kind == "style":
        return JSONResponse({"ok": False, "error": "Vektorkarten werden immer direkt geladen."})
    setattr(layer, field, not getattr(layer, field))
    db.commit()
    return JSONResponse({"ok": True, "value": getattr(layer, field)})


@app.post("/admin/maps/order", dependencies=[Depends(check_csrf)])
async def admin_map_order(request: Request, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    data = await request.form()
    for pos, raw in enumerate(str(data.get("ids", "")).split(",")):
        if raw.isdigit() and (layer := db.get(MapLayer, int(raw))):
            layer.position = pos
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/admin/maps/{layer_id:int}/duplicate", dependencies=[Depends(check_csrf)])
def admin_map_duplicate(request: Request, layer_id: int, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    layer = db.get(MapLayer, layer_id)
    if layer is None:
        raise HTTPException(404)
    clone = MapLayer(**{c.name: getattr(layer, c.name) for c in MapLayer.__table__.columns
                        if c.name not in ("id", "created_at", "updated_at")})
    clone.name = (layer.name + " (Kopie)")[:200]
    clone.enabled = False
    db.add(clone)
    db.commit()
    flash(request, "Kopie angelegt (ausgeschaltet).")
    return redirect(f"/admin/maps/{clone.id}")


@app.post("/admin/maps/{layer_id:int}/delete", dependencies=[Depends(check_csrf)])
def admin_map_delete(request: Request, layer_id: int, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    layer = db.get(MapLayer, layer_id)
    if layer is None:
        raise HTTPException(404)
    db.delete(layer)
    db.commit()
    mp.clear_cache(f"l{layer_id}-")
    flash(request, f"Layer „{layer.name}“ gelöscht.")
    return redirect("/admin/maps")


@app.post("/admin/maps/{layer_id:int}/test", dependencies=[Depends(check_csrf)])
def admin_map_test(request: Request, layer_id: int, user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    """Erreichbarkeit prüfen: eine Probeanfrage an den Dienst (Kachel, Kartenbild oder Objekte)."""
    import time as _time
    layer = db.get(MapLayer, layer_id)
    if layer is None:
        raise HTTPException(404)
    view = view_defaults(db)
    lon, lat = view["center"]
    import math
    x = 20037508.34 * lon / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) * 6378137
    bbox = f"{x - 2000:.2f},{y - 2000:.2f},{x + 2000:.2f},{y + 2000:.2f}"
    z = 12
    tx = int((lon + 180) / 360 * (1 << z))
    ty = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * (1 << z))
    if layer.kind == "style":
        url = layer.url
    else:
        action = {"xyz": "tile", "wms": "wms", "wfs": "wfs", "geojson": "geojson"}[layer.kind]
        url = mp.upstream_url(mp.layer_spec(layer), action, {"z": z, "x": tx, "y": ty, "bbox": bbox,
                                                               "time": layer.time_default})
    started = _time.monotonic()
    try:
        status, body, ctype = mp.fetch(url, guard=False)
    except (httpx.HTTPError, mp.BlockedAddress) as exc:
        return JSONResponse({"ok": False, "message": f"Nicht erreichbar: {exc}", "url": url})
    ms = int((_time.monotonic() - started) * 1000)
    good = status < 400 and (ctype.startswith("image/") if layer.kind in ("xyz", "wms") else True)
    hint = ""
    if not good and b"ServiceException" in body[:2000]:
        hint = body[:400].decode("utf-8", "replace")
    return JSONResponse({"ok": good, "message": f"HTTP {status}, {ctype or 'ohne Typ'}, {len(body) // 1024} kB in {ms} ms"
                                                + (f" – {hint}" if hint else ""), "url": url})


@app.post("/admin/maps/cache/clear", dependencies=[Depends(check_csrf)])
def admin_map_cache_clear(request: Request, layer: str = Form(""), user: User = Depends(maps_admin_user)):
    removed = mp.clear_cache(f"l{layer}-" if layer.isdigit() else "")
    flash(request, f"{removed} Kacheln aus dem Zwischenspeicher gelöscht.")
    return redirect("/admin/maps#cache")


EXPORT_FIELDS = [c for c in ("name", "kind", "role", "category", "description", "url", "layers", "styles", "image_format",
                             "version", "transparent", "tile_size", "min_zoom", "max_zoom", "opacity", "attribution",
                             "legend_url", "feature_info", "time_values", "time_default", "color", "swap_xy",
                             "extra_hosts", "proxy", "cache_hours", "enabled", "public", "in_forms", "default_visible")]


@app.get("/admin/maps/export.json")
def admin_map_export(user: User = Depends(maps_admin_user), db: Session = Depends(get_db)):
    layers = db.scalars(select(MapLayer).order_by(MapLayer.role, MapLayer.position))
    data = {"format": "kartenlayer/1", "layers": [{k: getattr(lyr, k) for k in EXPORT_FIELDS} for lyr in layers]}
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="kartenlayer.json"'})


@app.post("/admin/maps/import", dependencies=[Depends(check_csrf)])
async def admin_map_import(request: Request, file: UploadFile = File(...), user: User = Depends(maps_admin_user),
                           db: Session = Depends(get_db)):
    try:
        data = json.loads((await file.read(5_000_000)).decode("utf-8-sig"))
        items = data["layers"] if isinstance(data, dict) else data
        assert isinstance(items, list)
    except (ValueError, KeyError, AssertionError, UnicodeDecodeError):
        flash(request, "Die Datei ist keine gültige Layer-Exportdatei (JSON).", "error")
        return redirect("/admin/maps")
    added, bad = 0, 0
    pos = (db.scalar(select(func.max(MapLayer.position))) or 0) + 1
    for item in items[:500]:
        if not isinstance(item, dict):
            bad += 1
            continue

        class _D(dict):
            def get(self, k, d=None):
                v = super().get(k, d)
                return ("1" if v else "") if isinstance(v, bool) else v
        layer = MapLayer(position=pos)
        if _apply_layer(layer, _D(item)):
            bad += 1
            continue
        db.add(layer)
        added += 1
        pos += 1
    db.commit()
    flash(request, f"{added} Layer importiert." + (f" {bad} Einträge übersprungen." if bad else ""),
          "ok" if added else "error")
    return redirect("/admin/maps")


@app.post("/admin/maps/adopt", dependencies=[Depends(check_csrf)])
def admin_map_adopt(request: Request, map_id: int = Form(...), index: int = Form(...), user: User = Depends(maps_admin_user),
                    db: Session = Depends(get_db)):
    """Eigenen Layer aus einer gespeicherten Karte als Systemlayer übernehmen (zunächst ausgeschaltet)."""
    saved = db.get(UserMap, map_id)
    custom = mp.view_state(saved.state_json).get("custom", []) if saved else []
    defn = mp.clean_custom(custom[index].get("def")) if 0 <= index < len(custom) and isinstance(custom[index], dict) else None
    if defn is None:
        raise HTTPException(404)
    layer = MapLayer(name=defn.get("name") or defn["layers"] or "Übernommener Layer", kind=defn["kind"], role="overlay",
                     category="Übernommen", url=defn["url"], layers=defn.get("layers", ""), styles=defn.get("styles", ""),
                     version=defn.get("version", ""), image_format=defn.get("format", "image/png"),
                     attribution=defn.get("attribution", ""), time_values=",".join(defn.get("times", [])),
                     time_default=defn.get("time", ""), color=defn.get("color", "#7b2cbf"), swap_xy=defn.get("swap_xy", False),
                     feature_info=defn["kind"] == "wms", enabled=False, public=False,
                     position=(db.scalar(select(func.max(MapLayer.position))) or 0) + 1,
                     description=f"Übernommen aus der Karte „{saved.title}“ von {saved.owner.name if saved.owner else '–'}.")
    db.add(layer)
    db.commit()
    flash(request, "Layer übernommen. Bitte prüfen, beschreiben und dann einschalten.")
    return redirect(f"/admin/maps/{layer.id}")
