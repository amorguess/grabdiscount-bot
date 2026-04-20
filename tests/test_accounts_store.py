"""Tests de app.storage.accounts.AccountsStore."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.exceptions import NotFoundError
from app.storage.accounts import AccountsStore
from app.storage.models import AccountStatus


@pytest.fixture
def store(data_dir: Path) -> AccountsStore:
    return AccountsStore(data_dir)


def test_empty_store(store):
    assert store.all() == []
    assert store.get("nope@icloud.com") is None
    assert store.count_by_status() == {}


def test_add_and_get(store):
    rec = {"email": "a@icloud.com", "status": "available"}
    store.add(rec)
    assert store.get("a@icloud.com") == rec
    assert len(store.all()) == 1


def test_add_duplicate_raises(store):
    store.add({"email": "a@icloud.com", "status": "available"})
    with pytest.raises(ValueError, match="déjà présent"):
        store.add({"email": "a@icloud.com", "status": "full"})


def test_add_without_email_raises(store):
    with pytest.raises(ValueError):
        store.add({"status": "available"})


def test_update_existing(store):
    store.add({"email": "a@icloud.com", "status": "available"})
    updated = store.update("a@icloud.com", status="full", grab_phone="0812345678")
    assert updated["status"] == "full"
    assert updated["grab_phone"] == "0812345678"


def test_update_missing_raises(store):
    with pytest.raises(NotFoundError):
        store.update("nope@icloud.com", status="full")


def test_by_status(store):
    store.add({"email": "a@icloud.com", "status": "available"})
    store.add({"email": "b@icloud.com", "status": "full"})
    store.add({"email": "c@icloud.com", "status": "full"})
    assert len(store.by_status(AccountStatus.FULL)) == 2
    assert len(store.by_status("available")) == 1


def test_count_by_status(store):
    for email, s in [("a", "full"), ("b", "full"), ("c", "used"), ("d", "available")]:
        store.add({"email": email, "status": s})
    counts = store.count_by_status()
    assert counts == {"full": 2, "used": 1, "available": 1}


def test_claim_next_full(store):
    store.add({"email": "a@icloud.com", "status": "full"})
    store.add({"email": "b@icloud.com", "status": "full"})
    first = store.claim_next_full()
    assert first is not None
    assert first["email"] == "a@icloud.com"
    assert first["status"] == "en_cours"
    assert first["_locked_at"]
    # Deuxième call assigne le suivant
    second = store.claim_next_full()
    assert second is not None
    assert second["email"] == "b@icloud.com"


def test_claim_next_full_none_available(store):
    store.add({"email": "a@icloud.com", "status": "used"})
    assert store.claim_next_full() is None


def test_concurrent_claims_no_double_assign(data_dir):
    """2 threads qui claim simultanément ne doivent pas prendre le même compte."""
    store = AccountsStore(data_dir)
    for i in range(5):
        store.add({"email": f"{i}@x.com", "status": "full"})

    claimed = []
    lock = threading.Lock()

    def worker():
        rec = store.claim_next_full()
        if rec:
            with lock:
                claimed.append(rec["email"])

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == 5
    assert len(set(claimed)) == 5  # aucun doublon


def test_mark_used(store):
    store.add({"email": "a@icloud.com", "status": "en_cours"})
    rec = store.mark_used("a@icloud.com")
    assert rec["status"] == "used"
    assert rec["used_at"]


def test_release(store):
    store.add({"email": "a@icloud.com", "status": "en_cours", "_locked_at": "x"})
    rec = store.release("a@icloud.com")
    assert rec["status"] == "full"
    assert rec["_locked_at"] is None


def test_remove(store):
    store.add({"email": "a@icloud.com", "status": "available"})
    assert store.remove("a@icloud.com") is True
    assert store.get("a@icloud.com") is None
    assert store.remove("a@icloud.com") is False
