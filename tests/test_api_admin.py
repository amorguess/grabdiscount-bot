"""Tests des endpoints `/api/admin/*` (stats + dispo)."""

from __future__ import annotations

import pytest

from app.core.config import reset_settings_cache
from app.dashboard.app import create_app


@pytest.fixture
def app():
    reset_settings_cache()
    return create_app(config_overrides={"TESTING": True})


@pytest.fixture
def client(app):
    with app.test_client() as c:
        # login-as-admin pour tous les tests de ce fichier
        c.post("/login", json={"password": "test-pwd"})
        yield c


# ─── Auth ─────────────────────────────────────────────────────────────


def test_stats_requires_auth(app):
    with app.test_client() as c:
        resp = c.get("/api/admin/stats")
        assert resp.status_code == 401


def test_dispo_requires_auth(app):
    with app.test_client() as c:
        resp = c.get("/api/admin/dispo")
        assert resp.status_code == 401


# ─── Stats ────────────────────────────────────────────────────────────


def test_stats_empty_data(client):
    resp = client.get("/api/admin/stats")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["accounts"]["total"] == 0
    assert body["orders"]["total"] == 0
    assert body["messages"]["unread"] == 0
    assert body["subscribers"]["total"] == 0
    assert len(body["series"]["days"]) == 7
    assert len(body["series"]["delivered_per_day"]) == 7


def test_stats_counts_accounts_by_status(client, app):
    stores = app.config["STORES"]
    stores.accounts.add({"email": "a@x.com", "status": "available"})
    stores.accounts.add({"email": "b@x.com", "status": "full"})
    stores.accounts.add({"email": "c@x.com", "status": "full"})
    stores.accounts.add({"email": "d@x.com", "status": "used"})

    body = client.get("/api/admin/stats").get_json()
    assert body["accounts"]["total"] == 4
    assert body["accounts"]["available"] == 1
    assert body["accounts"]["full"] == 2
    assert body["accounts"]["used"] == 1


def test_stats_orders_breakdown(client, app):
    stores = app.config["STORES"]
    o1 = stores.orders.create(user_id=1, user_name="A")
    o2 = stores.orders.create(user_id=2, user_name="B")
    stores.orders.create(user_id=3, user_name="C")
    stores.orders.mark_in_progress(o1["order_id"])
    stores.orders.mark_delivered(o2["order_id"])

    body = client.get("/api/admin/stats").get_json()
    assert body["orders"]["total"] == 3
    assert body["orders"]["pending"] == 1
    assert body["orders"]["in_progress"] == 1
    assert body["orders"]["delivered"] == 1


# ─── Dispo ────────────────────────────────────────────────────────────


def test_dispo_get_default_is_open(client):
    body = client.get("/api/admin/dispo").get_json()
    assert body["dispo"] is True


def test_dispo_set_false(client):
    resp = client.post("/api/admin/dispo", json={"dispo": False})
    assert resp.status_code == 200
    assert resp.get_json()["dispo"] is False

    body = client.get("/api/admin/dispo").get_json()
    assert body["dispo"] is False


def test_dispo_set_rejects_missing_field(client):
    resp = client.post("/api/admin/dispo", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_field: dispo"
