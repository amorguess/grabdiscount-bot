"""Tests de l'endpoint `/api/restaurants/v2` — contrat identique au legacy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import reset_settings_cache
from app.dashboard.api.restaurants import _get_store
from app.dashboard.app import create_app


def _sample(n: int) -> list[dict]:
    """Génère n restaurants avec un mix de zones/cuisines/halal."""
    cuisines_pool = [["Thai"], ["Japanese", "Sushi"], ["Halal", "Indian"], ["Pizza", "Italian"]]
    zones_pool = ["Sukhumvit", "Silom", "Ari", "Asok"]
    return [
        {
            "id": f"r{i:03d}",
            "name": f"Resto {i}",
            "cuisine": cuisines_pool[i % 4],
            "zone": zones_pool[i % 4],
            "halal": (i % 5 == 0),
            "photo": f"https://cdn.example/{i}.jpg",
        }
        for i in range(n)
    ]


@pytest.fixture
def client(data_dir: Path, write_json):
    reset_settings_cache()
    _get_store.cache_clear()  # empty the per-data_dir store cache
    write_json("restaurants.json", {"restaurants": _sample(120)})
    app = create_app(config_overrides={"TESTING": True})
    with app.test_client() as c:
        yield c


def test_default_pagination_returns_30(client):
    resp = client.get("/api/restaurants/v2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["page"] == 1
    assert body["size"] == 30
    assert body["total"] == 120
    assert body["has_more"] is True
    assert len(body["restaurants"]) == 30


def test_page_2_returns_next_slice(client):
    resp = client.get("/api/restaurants/v2?page=2")
    body = resp.get_json()
    assert body["restaurants"][0]["id"] == "r030"
    assert len(body["restaurants"]) == 30


def test_size_clamped_to_50(client):
    resp = client.get("/api/restaurants/v2?size=999")
    body = resp.get_json()
    assert body["size"] == 50
    assert len(body["restaurants"]) == 50


def test_size_min_1(client):
    resp = client.get("/api/restaurants/v2?size=0")
    body = resp.get_json()
    assert body["size"] == 1


def test_invalid_page_falls_back_to_1(client):
    resp = client.get("/api/restaurants/v2?page=abc")
    body = resp.get_json()
    assert body["page"] == 1


def test_filter_halal(client):
    resp = client.get("/api/restaurants/v2?halal=1&size=50")
    body = resp.get_json()
    assert all(r["halal"] for r in body["restaurants"])
    assert body["total"] == 24  # 120 / 5


def test_filter_zone(client):
    resp = client.get("/api/restaurants/v2?zone=silom&size=50")
    body = resp.get_json()
    assert body["total"] == 30
    assert all("Silom" in r["zone"] for r in body["restaurants"])


def test_filter_cuisine(client):
    resp = client.get("/api/restaurants/v2?cuisine=thai&size=50")
    body = resp.get_json()
    assert all("Thai" in r["cuisine"] for r in body["restaurants"])


def test_query_matches_name_or_cuisine(client):
    resp = client.get("/api/restaurants/v2?q=pizza&size=50")
    body = resp.get_json()
    assert all(any("Pizza" in c for c in r["cuisine"]) for r in body["restaurants"])


def test_light_payload_shape(client):
    resp = client.get("/api/restaurants/v2?size=1")
    body = resp.get_json()
    r = body["restaurants"][0]
    assert set(r.keys()) == {"id", "name", "cuisine", "zone", "halal", "photo"}
    assert len(r["cuisine"]) <= 3


def test_has_more_false_on_last_page(client):
    resp = client.get("/api/restaurants/v2?page=4&size=30")
    body = resp.get_json()
    assert body["has_more"] is False


def test_cors_and_content_type(client):
    resp = client.get("/api/restaurants/v2")
    assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
    assert resp.headers["Access-Control-Allow-Origin"] == "*"


def test_legacy_endpoint_returns_raw_file(data_dir: Path, write_json):
    reset_settings_cache()
    _get_store.cache_clear()
    payload = {"restaurants": _sample(3)}
    write_json("restaurants.json", payload)
    app = create_app(config_overrides={"TESTING": True})
    with app.test_client() as c:
        resp = c.get("/api/restaurants")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "public, max-age=3600"
        body = json.loads(resp.data)
        assert len(body["restaurants"]) == 3


def test_legacy_endpoint_graceful_when_missing(data_dir: Path):
    reset_settings_cache()
    _get_store.cache_clear()
    app = create_app(config_overrides={"TESTING": True})
    with app.test_client() as c:
        resp = c.get("/api/restaurants")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"restaurants": [], "total": 0}


def test_v2_graceful_when_file_missing(data_dir: Path):
    reset_settings_cache()
    _get_store.cache_clear()
    app = create_app(config_overrides={"TESTING": True})
    with app.test_client() as c:
        resp = c.get("/api/restaurants/v2")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 0
        assert body["restaurants"] == []
