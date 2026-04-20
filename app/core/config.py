"""Configuration centrale — charge et valide les variables d'environnement.

Pattern 12-factor : un seul point d'entrée, `get_settings()`, qui cache
l'instance (singleton lazy). Les modules consomment `get_settings()` — jamais
`os.environ` directement — pour garder la config typée et testable.

Design:
- `Settings` est un dataclass frozen (immutable après création).
- Les champs obligatoires lèvent `ConfigError` si absents.
- Les chemins sont résolus en `Path` absolu.
- `reset()` vide le cache (usage: tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.core.exceptions import ConfigError

# Charge .env au plus tôt si présent (no-op en prod si vars déjà exportées)
load_dotenv(override=False)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ConfigError(f"Variable d'environnement obligatoire manquante: {key}")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _optional_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{key} doit être un entier, reçu: {raw!r}") from e


def _resolve_data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    """Config Telegram : bot token, admin, canal."""

    bot_token: str
    admin_chat_id: int
    channel_id: int


@dataclass(frozen=True, slots=True)
class DashboardSettings:
    """Config dashboard Flask (admin + employé)."""

    password: str
    employee_password: str
    secret: str
    port: int


@dataclass(frozen=True, slots=True)
class IntegrationSettings:
    """Clés API des services externes (tous optionnels)."""

    smspool_key: str = ""
    fivesim_key: str = ""
    smsactivate_key: str = ""
    herosms_key: str = ""
    icloud_email: str = ""
    icloud_apppass: str = ""
    git_token: str = ""


@dataclass(frozen=True, slots=True)
class MonitoringSettings:
    """Config Sentry (optionnel)."""

    sentry_dsn: str = ""
    sentry_environment: str = "production"

    @property
    def enabled(self) -> bool:
        return bool(self.sentry_dsn)


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration complète de l'application.

    Instancier via `get_settings()` — ne jamais construire à la main sauf en tests.
    """

    telegram: TelegramSettings
    dashboard: DashboardSettings
    integrations: IntegrationSettings
    monitoring: MonitoringSettings
    data_dir: Path
    project_root: Path = field(default_factory=lambda: _PROJECT_ROOT)

    def data_path(self, filename: str) -> Path:
        """Chemin absolu vers un fichier de données (ex: accounts.json)."""
        return self.data_dir / filename


def _build_settings() -> Settings:
    try:
        admin_id = int(_require("ADMIN_CHAT_ID"))
        channel_id = int(_require("CHANNEL_ID"))
    except ValueError as e:
        raise ConfigError(f"ADMIN_CHAT_ID et CHANNEL_ID doivent être des entiers: {e}") from e

    dashboard_pwd = _require("DASHBOARD_PASSWORD")

    return Settings(
        telegram=TelegramSettings(
            bot_token=_require("BOT_TOKEN"),
            admin_chat_id=admin_id,
            channel_id=channel_id,
        ),
        dashboard=DashboardSettings(
            password=dashboard_pwd,
            employee_password=_optional("EMPLOYEE_PASSWORD", dashboard_pwd),
            secret=_require("DASHBOARD_SECRET"),
            port=_optional_int("DASHBOARD_PORT", 5001),
        ),
        integrations=IntegrationSettings(
            smspool_key=_optional("SMSPOOL_KEY"),
            fivesim_key=_optional("FIVESIM_KEY"),
            smsactivate_key=_optional("SMSACTIVATE_KEY"),
            herosms_key=_optional("HEROSMS_KEY"),
            icloud_email=_optional("ICLOUD_EMAIL"),
            icloud_apppass=_optional("ICLOUD_APPPASS"),
            git_token=_optional("GIT_TOKEN"),
        ),
        monitoring=MonitoringSettings(
            sentry_dsn=_optional("SENTRY_DSN"),
            sentry_environment=_optional("SENTRY_ENVIRONMENT", "production"),
        ),
        data_dir=_resolve_data_dir(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Renvoie les settings (instance singleton, lazy)."""
    return _build_settings()


def reset_settings_cache() -> None:
    """Vide le cache des settings. À utiliser uniquement en tests."""
    get_settings.cache_clear()
