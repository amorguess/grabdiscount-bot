"""Smoke tests Phase 1 — vérifie que le projet démarre correctement.

Phase 2+ ajoutera des tests unitaires sur app.storage, app.core, etc.
"""

from __future__ import annotations


def test_app_package_imports():
    """Le package app est importable."""
    import app

    assert app.__version__


def test_app_subpackages_import():
    """Tous les sous-packages sont importables."""
    from app import bot, core, dashboard, integrations, storage  # noqa: F401


def test_subscribers_module_imports():
    """Le module subscribers (legacy) s'importe sans crash."""
    import subscribers

    assert hasattr(subscribers, "is_active")
    assert hasattr(subscribers, "add_subscriber")
    assert hasattr(subscribers, "PLAN_PRICES")


def test_subscribers_empty_state(data_dir):
    """Sans fichier, is_active renvoie False (pas d'exception)."""
    import subscribers

    assert subscribers.is_active(99999) is False
