"""Fixtures pytest partagées.

Isole les tests du vrai /data : DATA_DIR pointe vers un tmp_path,
toutes les variables d'env sensibles sont mockées.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remplit les env vars obligatoires pour tous les tests."""
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_CHAT_ID", "123")
    monkeypatch.setenv("CHANNEL_ID", "-100123456789")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-pwd")
    monkeypatch.setenv("EMPLOYEE_PASSWORD", "test-emp")
    monkeypatch.setenv("DASHBOARD_SECRET", "test-secret-32-chars-minimum-abcdef")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Dossier /data isolé par test."""
    return tmp_path


@pytest.fixture
def write_json(data_dir: Path):
    """Helper pour écrire un JSON de fixture dans DATA_DIR."""
    import json

    def _write(name: str, content: object) -> Path:
        p = data_dir / name
        p.write_text(json.dumps(content), encoding="utf-8")
        return p

    return _write
