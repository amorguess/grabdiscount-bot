"""Noms canoniques des fichiers de données.

Centralise les noms pour éviter les "accounts.json" en dur dispersés dans
le code. Résolution du chemin absolu via `Settings.data_path()`.
"""

from __future__ import annotations

from typing import Final

ACCOUNTS: Final = "accounts.json"
ORDERS: Final = "orders.json"
MESSAGES: Final = "messages.json"
SUBSCRIBERS: Final = "subscribers.json"
STATUS: Final = "status.json"
PENDING_REFERRALS: Final = "pending_referrals.json"
RESTAURANTS: Final = "restaurants.json"
