"""Tests des endpoints `/api/messages/*`."""

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
        resp = c.get("/api/messages")
        assert resp.status_code == 401


def test_list_empty(client):
    body = client.get("/api/messages").get_json()
    assert body["threads"] == {}
    assert body["unread_total"] == 0


def test_list_with_threads(client, app):
    s = app.config["STORES"].messages
    s.append(1001, text="Salut", author="client", name="Alice")
    s.append(1002, text="Bonjour", author="client", name="Bob")
    s.append(1002, text="Commande possible ?", author="client", name="Bob")

    body = client.get("/api/messages").get_json()
    assert len(body["threads"]) == 2
    assert body["unread_total"] == 3


def test_unread_threads_sorted_desc(client, app):
    s = app.config["STORES"].messages
    s.append(1, text="un", author="client", name="A")
    for _ in range(3):
        s.append(2, text="spam", author="client", name="B")

    body = client.get("/api/messages/unread").get_json()
    assert body["total"] == 4
    assert body["threads"][0]["user_id"] == "2"  # plus de unread en premier


def test_get_thread(client, app):
    app.config["STORES"].messages.append(42, text="Hi", author="client", name="X")
    resp = client.get("/api/messages/42")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user_id"] == 42
    assert body["name"] == "X"
    assert len(body["messages"]) == 1


def test_get_thread_missing_404(client):
    resp = client.get("/api/messages/99999")
    assert resp.status_code == 404


def test_mark_read(client, app):
    s = app.config["STORES"].messages
    s.append(7, text="one", author="client", name="Z")
    s.append(7, text="two", author="client", name="Z")
    assert s.unread_total() == 2

    resp = client.post("/api/messages/7/read")
    assert resp.status_code == 200
    assert s.unread_total() == 0


def test_mark_read_missing_404(client):
    resp = client.post("/api/messages/12345/read")
    assert resp.status_code == 404


def test_reply_appends_admin_message(client, app):
    s = app.config["STORES"].messages
    s.append(5, text="bonjour", author="client", name="U")

    resp = client.post("/api/messages/5/reply", json={"text": "Salut !"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["message"]["from"] == "admin"
    assert body["message"]["text"] == "Salut !"

    msgs = s.list_messages(5)
    assert len(msgs) == 2
    assert msgs[-1]["from"] == "admin"


def test_reply_rejects_empty_text(client):
    resp = client.post("/api/messages/1/reply", json={"text": "   "})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_text"
