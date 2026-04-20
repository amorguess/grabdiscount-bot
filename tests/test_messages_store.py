"""Tests de app.storage.messages.MessagesStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.messages import MessagesStore


@pytest.fixture
def store(data_dir: Path) -> MessagesStore:
    return MessagesStore(data_dir)


def test_empty_store(store):
    assert store.all_threads() == {}
    assert store.get_thread(42) is None
    assert store.list_messages(42) == []
    assert store.unread_total() == 0


def test_append_client_message(store):
    rec = store.append(42, text="Bonjour", author="client", name="Alice", username="@alice")
    assert rec["text"] == "Bonjour"
    assert rec["from"] == "client"
    assert rec["read"] is False

    thread = store.get_thread(42)
    assert thread["name"] == "Alice"
    assert thread["username"] == "@alice"
    assert len(thread["messages"]) == 1
    assert thread["unread"] == 1


def test_append_admin_message_does_not_increment_unread(store):
    store.append(42, text="Hi client", author="admin", name="Alice")
    thread = store.get_thread(42)
    assert thread["unread"] == 0
    assert thread["messages"][0]["read"] is True


def test_multiple_messages_increment_unread(store):
    store.append(42, text="A", author="client", name="Alice")
    store.append(42, text="B", author="client")
    store.append(42, text="C", author="client")
    assert store.get_thread(42)["unread"] == 3


def test_admin_reply_does_not_reset_unread(store):
    """Admin qui répond ne marque pas les messages client comme lus."""
    store.append(42, text="A", author="client", name="Alice")
    store.append(42, text="réponse", author="admin")
    # Toujours 1 unread côté client
    assert store.get_thread(42)["unread"] == 1


def test_mark_thread_read(store):
    store.append(42, text="A", author="client", name="Alice")
    store.append(42, text="B", author="client")
    assert store.mark_thread_read(42) is True
    thread = store.get_thread(42)
    assert thread["unread"] == 0
    assert all(m["read"] for m in thread["messages"])


def test_mark_thread_read_missing(store):
    assert store.mark_thread_read(999) is False


def test_unread_total_across_threads(store):
    store.append(1, text="A", author="client", name="A")
    store.append(1, text="B", author="client")
    store.append(2, text="C", author="client", name="B")
    assert store.unread_total() == 3


def test_threads_with_unread_sorted(store):
    store.append(1, text="a", author="client", name="A")
    store.append(2, text="a", author="client", name="B")
    store.append(2, text="b", author="client")
    store.append(2, text="c", author="client")
    store.append(3, text="a", author="admin", name="C")  # 0 unread

    results = store.threads_with_unread()
    assert len(results) == 2
    assert results[0][0] == "2"  # le plus gros unread d'abord
    assert results[1][0] == "1"


def test_delete_thread(store):
    store.append(42, text="A", author="client", name="Alice")
    assert store.delete_thread(42) is True
    assert store.get_thread(42) is None
    assert store.delete_thread(42) is False


def test_name_not_overwritten_by_later_append(store):
    store.append(42, text="A", author="client", name="Alice", username="@alice")
    store.append(42, text="B", author="client", name="DIFFERENT", username="@other")
    thread = store.get_thread(42)
    # Le nom initial est préservé
    assert thread["name"] == "Alice"
    assert thread["username"] == "@alice"


def test_read_flag_forced_true(store):
    """Un message client peut être créé pré-lu (ex: import depuis archive)."""
    rec = store.append(42, text="A", author="client", name="Alice", read=True)
    assert rec["read"] is True
    thread = store.get_thread(42)
    assert thread["unread"] == 0  # pas incrémenté car read=True
