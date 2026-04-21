"""Application Factory Flask pour le dashboard admin GrabDiscount.

Pattern `create_app()` : aucune instance globale, chaque appel construit
une app indépendante (utile pour les tests + futurs workers async).

Phase 2 ter — coexistence avec le `dashboard.py` legacy :
- Nouvelles routes enregistrées via blueprints dans `app/dashboard/api/`
- L'app tourne sur un port distinct (défaut 5002) pour validation en prod
- Une fois stabilisée, on bascule le proxy VPS + on archive dashboard.py
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.dashboard.api import register_api_blueprints

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, config_overrides: dict[str, Any] | None = None) -> Flask:
    """Crée une instance Flask configurée.

    Args:
        settings: `Settings` injectable (tests). Défaut = `get_settings()`.
        config_overrides: clefs/valeurs écrasant la config Flask (ex. TESTING=True).

    Returns:
        L'app prête à être servie.
    """
    if settings is None:
        settings = get_settings()

    configure_logging()

    app = Flask("grabdiscount.dashboard")
    app.config["SETTINGS"] = settings
    app.config["SECRET_KEY"] = settings.dashboard.secret

    if config_overrides:
        app.config.update(config_overrides)

    register_api_blueprints(app)

    logger.info(
        "dashboard app ready",
        extra={"blueprints": sorted(app.blueprints.keys()), "data_dir": str(settings.data_dir)},
    )
    return app
