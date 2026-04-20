"""Tests de app.storage.base.JSONStore."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from app.core.exceptions import StorageCorruptError, StorageLockTimeout
from app.storage.base import JSONStore


@pytest.fixture
def store(tmp_path: Path) -> JSONStore[dict]:
    return JSONStore(tmp_path / "data.json", default=dict)


def test_read_missing_returns_default(store):
    assert store.read() == {}


def test_write_then_read(store):
    store.write({"a": 1})
    assert store.read() == {"a": 1}


def test_write_is_atomic(store, tmp_path):
    store.write({"foo": "bar"})
    content = json.loads((tmp_path / "data.json").read_text())
    assert content == {"foo": "bar"}
    # Aucun fichier tmp résiduel
    leftovers = list(tmp_path.glob(".data.json.*.tmp"))
    assert leftovers == []


def test_write_creates_parent_dirs(tmp_path):
    store = JSONStore(tmp_path / "nested" / "deep" / "data.json", default=dict)
    store.write({"x": 1})
    assert store.read() == {"x": 1}


def test_mutate_transforms_and_persists(store):
    store.write({"counter": 0})
    new = store.mutate(lambda d: {**d, "counter": d["counter"] + 1})
    assert new == {"counter": 1}
    assert store.read() == {"counter": 1}


def test_mutate_on_missing_uses_default(store):
    new = store.mutate(lambda d: {**d, "first": True})
    assert new == {"first": True}


def test_cache_invalidates_on_mtime_change(store, tmp_path):
    store.write({"v": 1})
    assert store.read() == {"v": 1}

    # Écrit directement sur disque (hors du store) pour simuler un writer externe
    import time

    time.sleep(0.01)  # garantit mtime différent
    (tmp_path / "data.json").write_text(json.dumps({"v": 2}))
    os.utime(tmp_path / "data.json", None)

    assert store.read() == {"v": 2}


def test_corrupt_json_raises(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{not valid json")
    store = JSONStore(p, default=dict)
    with pytest.raises(StorageCorruptError):
        store.read()


def test_lock_timeout(tmp_path):
    """Deuxième writer doit timeout si le premier tient le verrou."""
    p = tmp_path / "locked.json"
    s1 = JSONStore(p, default=dict, lock_timeout=0.2)
    s2 = JSONStore(p, default=dict, lock_timeout=0.2)

    started = threading.Event()
    release = threading.Event()

    def writer_holding_lock():
        with s1._file_lock():
            started.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=writer_holding_lock)
    t.start()
    started.wait(timeout=2.0)

    with pytest.raises(StorageLockTimeout):
        s2.write({"x": 1})

    release.set()
    t.join()


def test_concurrent_mutate_is_serialized(tmp_path):
    """N threads qui incrémentent un compteur doivent tous compter."""
    p = tmp_path / "counter.json"
    store = JSONStore(p, default=dict, lock_timeout=10.0)
    store.write({"n": 0})

    N_THREADS = 8
    N_INCR_PER_THREAD = 25

    def worker():
        for _ in range(N_INCR_PER_THREAD):
            store.mutate(lambda d: {**d, "n": d["n"] + 1})

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = json.loads(p.read_text())
    assert final["n"] == N_THREADS * N_INCR_PER_THREAD


def test_invalidate_cache_forces_reread(store, tmp_path):
    store.write({"v": 1})
    store.read()
    # Patch disque sans changer mtime apparent : on invalide à la main
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"v": 99}))
    store.invalidate_cache()
    assert store.read() == {"v": 99}


def test_generic_typing_with_list(tmp_path):
    store: JSONStore[list] = JSONStore(tmp_path / "list.json", default=list)
    store.write([1, 2, 3])
    assert store.read() == [1, 2, 3]


def test_indent_option(tmp_path):
    p = tmp_path / "pretty.json"
    store = JSONStore(p, default=dict, indent=2)
    store.write({"a": 1, "b": [2, 3]})
    content = p.read_text()
    assert "\n  " in content  # indenté


def test_non_ascii_persisted(tmp_path):
    p = tmp_path / "fr.json"
    store: JSONStore[dict] = JSONStore(p, default=dict)
    store.write({"prénom": "Éléonore", "ville": "Bangkok ภาษาไทย"})
    raw = p.read_text(encoding="utf-8")
    assert "Éléonore" in raw
    assert "ภาษาไทย" in raw
