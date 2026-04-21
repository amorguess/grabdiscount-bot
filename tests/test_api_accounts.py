"""Tests des endpoints `/api/accounts/*`."""

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
        resp = c.get("/api/accounts")
        assert resp.status_code == 401


def test_list_empty(client):
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["accounts"] == []
    assert body["counts"] == {}


def test_list_with_accounts(client, app):
    s = app.config["STORES"].accounts
    s.add({"email": "a@x.com", "status": "available"})
    s.add({"email": "b@x.com", "status": "full"})

    body = client.get("/api/accounts").get_json()
    assert len(body["accounts"]) == 2
    assert body["counts"] == {"available": 1, "full": 1}


def test_pool_counters(client, app):
    s = app.config["STORES"].accounts
    s.add({"email": "r@x.com", "status": "grab_ready"})
    s.add({"email": "a@x.com", "status": "available"})
    s.add({"email": "f@x.com", "status": "full"})

    body = client.get("/api/accounts/pool").get_json()
    assert body["ready"] == 1
    assert body["available"] == 1
    assert body["full"] == 1
    assert body["total"] == 3


def test_get_account_found(client, app):
    app.config["STORES"].accounts.add({"email": "x@x.com", "status": "full"})
    resp = client.get("/api/accounts/x@x.com")
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "x@x.com"


def test_get_account_missing_returns_404(client):
    resp = client.get("/api/accounts/none@x.com")
    assert resp.status_code == 404


def test_update_status_used_sets_used_at(client, app):
    app.config["STORES"].accounts.add({"email": "b@x.com", "status": "full"})
    resp = client.post("/api/accounts/b@x.com", json={"status": "used"})
    assert resp.status_code == 200
    account = resp.get_json()["account"]
    assert account["status"] == "used"
    assert account["used_at"] is not None


def test_update_rejects_unknown_fields(client, app):
    app.config["STORES"].accounts.add({"email": "c@x.com", "status": "full"})
    resp = client.post("/api/accounts/c@x.com", json={"foo": "bar"})
    assert resp.status_code == 400


def test_update_missing_account_404(client):
    resp = client.post("/api/accounts/ghost@x.com", json={"status": "used"})
    assert resp.status_code == 404


def test_update_clears_used_at_on_revert(client, app):
    s = app.config["STORES"].accounts
    s.add({"email": "d@x.com", "status": "used", "used_at": "2026-04-20T10:00:00"})
    resp = client.post("/api/accounts/d@x.com", json={"status": "available"})
    assert resp.get_json()["account"]["used_at"] is None
