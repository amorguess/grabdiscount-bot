"""Intégration Sentry (optionnelle).

`init_sentry()` est idempotent et no-op si `sentry-sdk` n'est pas installé ou
si `SENTRY_DSN` est vide. Cela permet d'avoir un code d'appel simple sans
`if monitoring.enabled:` partout :

    from app.integrations.sentry import init_sentry
    init_sentry()  # tout simplement
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

_LOG = get_logger(__name__)
_initialized = False


def init_sentry() -> bool:
    """Initialise Sentry si DSN configuré et SDK installé.

    Returns:
        True si Sentry est actif après l'appel, False sinon.
    """
    global _initialized
    if _initialized:
        return True

    settings = get_settings()
    if not settings.monitoring.enabled:
        _LOG.debug("Sentry désactivé (SENTRY_DSN vide)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        _LOG.warning("sentry-sdk non installé — pip install 'grabdiscount[monitoring]'")
        return False

    sentry_sdk.init(
        dsn=settings.monitoring.sentry_dsn,
        environment=settings.monitoring.sentry_environment,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.0,
        send_default_pii=False,
        attach_stacktrace=True,
    )
    _initialized = True
    _LOG.info("sentry_initialized", extra={"environment": settings.monitoring.sentry_environment})
    return True
