"""Hiérarchie d'exceptions du domaine GrabDiscount.

Toutes les erreurs métier héritent de `GrabError`. Cela permet aux layers
supérieures (bot handlers, Flask routes) d'attraper un seul type et de
les convertir en messages utilisateur sans avoir à gérer des exceptions
stdlib ambiguës.
"""

from __future__ import annotations


class GrabError(Exception):
    """Exception de base pour toute erreur applicative GrabDiscount."""


class ConfigError(GrabError):
    """Variable d'environnement manquante ou malformée."""


class StorageError(GrabError):
    """Erreur d'accès à la couche de persistance."""


class StorageCorruptError(StorageError):
    """Le fichier sur disque est illisible (JSON cassé, etc.)."""


class StorageLockTimeout(StorageError):
    """Impossible d'acquérir le verrou fichier dans le délai imparti."""


class NotFoundError(GrabError):
    """Ressource demandée introuvable."""


class AlreadyExistsError(GrabError):
    """Conflit d'unicité (ex: subscriber déjà présent)."""


class PermissionDeniedError(GrabError):
    """Utilisateur non autorisé pour l'action demandée."""


class IntegrationError(GrabError):
    """Erreur côté service externe (Telegram, SMSPool, iCloud, etc.)."""


class RateLimitedError(IntegrationError):
    """Trop de requêtes — l'appelant doit retry plus tard."""
