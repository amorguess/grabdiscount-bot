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
from werkzeug.middleware.proxy_fix import ProxyFix

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.dashboard.api import register_api_blueprints
from app.dashboard.stores import attach_stores

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, config_overrides: dict[str, Any] | None = None) -> Flask:
    """Crée une instance Flask configurée.

    L'app tourne **toujours derrière nginx** (voir `ops/nginx/`). On applique
    `ProxyFix` pour que Flask respecte les headers injectés par nginx :
    - `X-Forwarded-Proto` → bon scheme pour les redirects (pas de HTTP→HTTP)
    - `X-Forwarded-For`   → vraie IP client (Cloudflare → nginx → Flask)
    - `X-Forwarded-Host`  → bon host pour les URLs générées
    Sans ça, les `redirect("/login")` casseraient en HTTPS, et le rate
    limiter verrait toujours `127.0.0.1`.

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

    # 1 hop : Cloudflare → nginx → Flask. nginx réécrit déjà les headers
    # CF-Connecting-IP via `real_ip_header`, donc X-Forwarded-For côté Flask
    # contient déjà la vraie IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    if config_overrides:
        app.config.update(config_overrides)

    attach_stores(app)
    register_api_blueprints(app)

    logger.info(
        "dashboard app ready",
        extra={"blueprints": sorted(app.blueprints.keys()), "data_dir": str(settings.data_dir)},
    )
    return app
