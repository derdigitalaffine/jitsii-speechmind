"""Adress- und Ortssuche für Formulare und Kartenbrowser (über den Server, siehe geocode.py)."""

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import geocode
from .main import app, rate_limit


def _json(data) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/geo/search")
async def geo_search(request: Request, q: str = "", limit: int = 6):
    rate_limit(request, "geo", limit=60, window=60)
    return _json({"results": await run_in_threadpool(geocode.search, q, limit)})


@app.get("/geo/reverse")
async def geo_reverse(request: Request, lat: float = 0, lon: float = 0):
    rate_limit(request, "geo", limit=60, window=60)
    return _json({"result": await run_in_threadpool(geocode.reverse, lat, lon)})


@app.get("/geo/postcode")
async def geo_postcode(request: Request, plz: str = ""):
    rate_limit(request, "geo", limit=60, window=60)
    return _json({"results": await run_in_threadpool(geocode.postcode, plz)})
