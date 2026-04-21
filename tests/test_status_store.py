"""Tests du StatusStore."""

from __future__ import annotations

from pathlib import Path

from app.storage.status import StatusStore


def test_default_is_dispo_true(tmp_path: Path) -> None:
    s = StatusStore(tmp_path)
    assert s.is_dispo() is True
    assert s.read() == {"dispo": True, "pause_until": None}


def test_set_dispo_false(tmp_path: Path) -> None:
    s = StatusStore(tmp_path)
    s.set_dispo(False)
    assert s.is_dispo() is False


def test_set_pause_until(tmp_path: Path) -> None:
    s = StatusStore(tmp_path)
    s.set_pause("2026-05-01T00:00:00")
    assert s.read()["pause_until"] == "2026-05-01T00:00:00"


def test_persists_across_instances(tmp_path: Path) -> None:
    StatusStore(tmp_path).set_dispo(False)
    assert StatusStore(tmp_path).is_dispo() is False


def test_clear_pause(tmp_path: Path) -> None:
    s = StatusStore(tmp_path)
    s.set_pause("2026-05-01T00:00:00")
    s.set_pause(None)
    assert s.read()["pause_until"] is None
