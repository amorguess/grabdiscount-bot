"""Tests du RestaurantsStore — cache mtime, lecture JSON."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.storage.restaurants import RestaurantsStore


def test_empty_when_file_missing(tmp_path: Path) -> None:
    store = RestaurantsStore(tmp_path)
    assert store.all() == []
    assert store.raw_bytes() is None


def test_reads_restaurants_key(tmp_path: Path) -> None:
    (tmp_path / "restaurants.json").write_text(
        json.dumps({"restaurants": [{"id": "a", "name": "Alice"}]}),
        encoding="utf-8",
    )
    store = RestaurantsStore(tmp_path)
    assert store.all() == [{"id": "a", "name": "Alice"}]


def test_cache_invalidated_on_mtime_change(tmp_path: Path) -> None:
    p = tmp_path / "restaurants.json"
    p.write_text(json.dumps({"restaurants": [{"id": "1"}]}), encoding="utf-8")
    store = RestaurantsStore(tmp_path)
    assert len(store.all()) == 1

    time.sleep(0.01)
    p.write_text(json.dumps({"restaurants": [{"id": "1"}, {"id": "2"}]}), encoding="utf-8")
    # Force mtime change on filesystems with low resolution
    import os

    os.utime(p, (time.time() + 1, time.time() + 1))
    assert len(store.all()) == 2


def test_corrupt_json_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "restaurants.json").write_text("{not json", encoding="utf-8")
    store = RestaurantsStore(tmp_path)
    assert store.all() == []


def test_raw_bytes_returns_file_content(tmp_path: Path) -> None:
    payload = b'{"restaurants": []}'
    (tmp_path / "restaurants.json").write_bytes(payload)
    store = RestaurantsStore(tmp_path)
    assert store.raw_bytes() == payload
