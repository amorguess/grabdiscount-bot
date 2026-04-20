"""Tests de app.storage.orders.OrdersStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import NotFoundError
from app.storage.orders import OrdersStore


@pytest.fixture
def store(data_dir: Path) -> OrdersStore:
    return OrdersStore(data_dir)


def test_create_order(store):
    order = store.create(user_id=42, user_name="Alice", user_username="@alice")
    assert order["user_id"] == 42
    assert order["status"] == "pending"
    assert order["order_id"]
    assert len(order["order_id"]) == 12


def test_ids_are_unique(store):
    ids = {store.create(user_id=i, user_name=f"U{i}")["order_id"] for i in range(20)}
    assert len(ids) == 20


def test_get_and_by_user(store):
    o1 = store.create(user_id=1, user_name="A")
    store.create(user_id=2, user_name="B")
    store.create(user_id=1, user_name="A")

    assert store.get(o1["order_id"])["user_id"] == 1
    assert store.get("nope") is None
    assert len(store.by_user(1)) == 2
    assert len(store.by_user(2)) == 1


def test_active_for_user(store):
    o1 = store.create(user_id=1, user_name="A")
    store.mark_delivered(o1["order_id"])
    o2 = store.create(user_id=1, user_name="A")

    active = store.active_for_user(1)
    assert active is not None
    assert active["order_id"] == o2["order_id"]


def test_active_for_user_none_when_all_delivered(store):
    o = store.create(user_id=1, user_name="A")
    store.mark_delivered(o["order_id"])
    assert store.active_for_user(1) is None


def test_transitions(store):
    o = store.create(user_id=1, user_name="A")
    oid = o["order_id"]

    assert store.mark_in_progress(oid)["status"] == "in_progress"
    assert store.mark_delivered(oid)["status"] == "delivered"


def test_cancel_with_reason(store):
    o = store.create(user_id=1, user_name="A")
    cancelled = store.cancel(o["order_id"], reason="hors zone")
    assert cancelled["status"] == "cancelled"
    assert cancelled["admin_note"] == "hors zone"


def test_assign_account(store):
    o = store.create(user_id=1, user_name="A")
    updated = store.assign_account(o["order_id"], "compte@icloud.com")
    assert updated["account_email"] == "compte@icloud.com"


def test_set_address(store):
    o = store.create(user_id=1, user_name="A")
    store.set_address(o["order_id"], "123 Sukhumvit")
    assert store.get(o["order_id"])["address"] == "123 Sukhumvit"


def test_by_status(store):
    o1 = store.create(user_id=1, user_name="A")
    o2 = store.create(user_id=2, user_name="B")
    store.mark_delivered(o1["order_id"])

    delivered = store.by_status("delivered")
    pending = store.by_status("pending")
    assert len(delivered) == 1 and delivered[0]["order_id"] == o1["order_id"]
    assert len(pending) == 1 and pending[0]["order_id"] == o2["order_id"]


def test_patch_missing_raises(store):
    with pytest.raises(NotFoundError):
        store.mark_delivered("nope")


def test_updated_at_changes_on_transition(store):
    o = store.create(user_id=1, user_name="A")
    original = o["updated_at"]
    import time

    time.sleep(1.01)  # TS_FMT granularity is 1s
    updated = store.mark_delivered(o["order_id"])
    assert updated["updated_at"] != original
