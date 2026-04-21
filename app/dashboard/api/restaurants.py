"""Endpoints API restaurants (liste paginée + payload brut legacy).

Porté depuis `dashboard.py` (legacy). Contrat préservé à l'identique :

`/api/restaurants/v2`
    Params :
        - `page` (int, défaut 1, min 1)
        - `size` (int, défaut 30, clamp 1..50)
        - `q` (str, recherche dans name + cuisine)
        - `cuisine` (str, match partiel dans la liste cuisine)
        - `zone` (str, match partiel)
        - `halal` (bool : "1"/"true"/"yes")
    Réponse :
        `{restaurants: [{id, name, cuisine[:3], zone, halal, photo}],
          page, size, total, has_more}`
    Headers :
        - `Content-Type: application/json; charset=utf-8`
        - `Access-Control-Allow-Origin: *`

`/api/restaurants`
    Legacy : renvoie `restaurants.json` brut (~20 MB). Conservé pour
    compat descendante — la Mini App utilise v2 depuis la v3 du cache.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from app.storage.restaurants import RestaurantsStore

bp = Blueprint("restaurants", __name__, url_prefix="/api")


def _store() -> RestaurantsStore:
    """Résout le store depuis la config de l'app (un par `data_dir`).

    `lru_cache` évite de recréer le store (et son cache RAM) à chaque requête.
    """
    data_dir = current_app.config["SETTINGS"].data_dir
    return _get_store(str(data_dir))


@lru_cache(maxsize=4)
def _get_store(data_dir_str: str) -> RestaurantsStore:
    from pathlib import Path

    return RestaurantsStore(Path(data_dir_str))


def _parse_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = request.args.get(name, default)
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    val = max(minimum, val)
    if maximum is not None:
        val = min(maximum, val)
    return val


def _matches(r: dict[str, Any], *, q: str, cuisine: str, zone: str, halal: bool) -> bool:
    if cuisine and not any(cuisine in (c or "").lower() for c in (r.get("cuisine") or [])):
        return False
    if zone and zone not in (r.get("zone") or "").lower():
        return False
    if halal and not r.get("halal"):
        return False
    if q:
        name_hit = q in (r.get("name") or "").lower()
        cuisine_hit = any(q in (c or "").lower() for c in (r.get("cuisine") or []))
        if not (name_hit or cuisine_hit):
            return False
    return True


@bp.get("/restaurants/v2")
def restaurants_v2() -> Response:
    page = _parse_int("page", default=1, minimum=1)
    size = _parse_int("size", default=30, minimum=1, maximum=50)
    q = (request.args.get("q") or "").strip().lower()
    cuisine = (request.args.get("cuisine") or "").strip().lower()
    zone = (request.args.get("zone") or "").strip().lower()
    halal = (request.args.get("halal") or "").lower() in ("1", "true", "yes")

    all_restos = _store().all()
    filtered = [r for r in all_restos if _matches(r, q=q, cuisine=cuisine, zone=zone, halal=halal)]

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    window = filtered[start:end]

    light = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "cuisine": (r.get("cuisine") or [])[:3],
            "zone": r.get("zone"),
            "halal": bool(r.get("halal")),
            "photo": r.get("photo"),
        }
        for r in window
    ]

    payload = json.dumps(
        {
            "restaurants": light,
            "page": page,
            "size": size,
            "total": total,
            "has_more": end < total,
        },
        ensure_ascii=False,
    )
    resp = make_response(payload)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@bp.get("/restaurants")
def restaurants_legacy() -> Response:
    """Payload brut du fichier JSON (~20 MB)."""
    raw = _store().raw_bytes()
    if raw is None:
        return jsonify({"restaurants": [], "total": 0})
    resp = make_response(raw)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp
