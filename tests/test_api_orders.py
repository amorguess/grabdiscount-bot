"""Tests des endpoints `/api/orders/*` + transitions d'état."""

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
        c.post("/login", json={"password": "test-pwd"})
        yield c


def test_list_requires_auth(app):
    with app.test_client() as c:
        resp = c.get("/api/orders")
        assert resp.status_code == 401


def test_list_empty(client):
    body = client.get("/api/orders").get_json()
    assert body == {"orders": []}


def test_list_pending_filters(client, app):
    s = app.config["STORES"].orders
    o1 = s.create(user_id=1, user_name="A")
    o2 = s.create(user_id=2, user_name="B")
    s.create(user_id=3, user_name="C")
    s.mark_in_progress(o1["order_id"])
    s.mark_delivered(o2["order_id"])

    body = client.get("/api/orders/pending").get_json()
    assert body["total"] == 2  # pending + in_progress
    statuses = {o["status"] for o in body["orders"]}
    assert statuses == {"pending", "in_progress"}


def test_get_order_found(client, app):
    o = app.config["STORES"].orders.create(user_id=1, user_name="A")
    resp = client.get(f"/api/orders/{o['order_id']}")
    assert resp.status_code == 200
    assert resp.get_json()["order_id"] == o["order_id"]


def test_get_order_missing_404(client):
    resp = client.get("/api/orders/ghost123")
    assert resp.status_code == 404


# ─── Validate ─────────────────────────────────────────────────────────


def test_validate_assigns_full_account(client, app):
    stores = app.config["STORES"]
    stores.accounts.add({"email": "full@x.com", "status": "full"})
    order = stores.orders.create(user_id=1, user_name="A")

    resp = client.post(f"/api/orders/{order['order_id']}/validate")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["order"]["status"] == "in_progress"
    assert body["order"]["account_email"] == "full@x.com"

    # Le compte est passé en_cours
    account = stores.accounts.get("full@x.com")
    assert account["status"] == "en_cours"


def test_validate_fails_when_no_account(client, app):
    order = app.config["STORES"].orders.create(user_id=1, user_name="A")
    resp = client.post(f"/api/orders/{order['order_id']}/validate")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "no_full_account_available"


def test_validate_missing_order_404(client):
    resp = client.post("/api/orders/ghost/validate")
    assert resp.status_code == 404


# ─── Delivered ────────────────────────────────────────────────────────


def test_delivered_marks_account_used(client, app):
    stores = app.config["STORES"]
    stores.accounts.add({"email": "f@x.com", "status": "full"})
    order = stores.orders.create(user_id=1, user_name="A")
    client.post(f"/api/orders/{order['order_id']}/validate")

    resp = client.post(f"/api/orders/{order['order_id']}/delivered")
    assert resp.status_code == 200
    assert resp.get_json()["order"]["status"] == "delivered"
    assert stores.accounts.get("f@x.com")["status"] == "used"


# ─── Cancel ───────────────────────────────────────────────────────────


def test_cancel_releases_account(client, app):
    stores = app.config["STORES"]
    stores.accounts.add({"email": "f@x.com", "status": "full"})
    order = stores.orders.create(user_id=1, user_name="A")
    client.post(f"/api/orders/{order['order_id']}/validate")
    # account is now en_cours

    resp = client.post(f"/api/orders/{order['order_id']}/cancel", json={"reason": "client renonce"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["order"]["status"] == "cancelled"
    assert body["order"]["admin_note"] == "client renonce"
    # account released back to full
    assert stores.accounts.get("f@x.com")["status"] == "full"


def test_cancel_missing_order_404(client):
    resp = client.post("/api/orders/ghost/cancel", json={})
    assert resp.status_code == 404
