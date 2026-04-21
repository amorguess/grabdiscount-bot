"""Résolution centralisée des stores dans le contexte Flask.

Chaque store est construit **une fois par app Flask** (pas par requête) et
attaché à `app.config["STORES"]`. Un helper `get_stores()` résout depuis
`current_app` pour usage dans les vues.

Pourquoi pas des globaux module-level ? Parce qu'on veut pouvoir créer
plusieurs apps en parallèle (tests, future split en microservices) avec
des `data_dir` différents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from flask import Flask, current_app

from app.storage.accounts import AccountsStore
from app.storage.messages import MessagesStore
from app.storage.orders import OrdersStore
from app.storage.restaurants import RestaurantsStore
from app.storage.status import StatusStore
from app.storage.subscribers import SubscribersStore


@dataclass(frozen=True, slots=True)
class Stores:
    """Bundle immuable de tous les stores attachés à une app."""

    accounts: AccountsStore
    orders: OrdersStore
    messages: MessagesStore
    subscribers: SubscribersStore
    status: StatusStore
    restaurants: RestaurantsStore


def build_stores(data_dir: Path) -> Stores:
    """Construit un bundle de stores pointant sur `data_dir`."""
    return Stores(
        accounts=AccountsStore(data_dir),
        orders=OrdersStore(data_dir),
        messages=MessagesStore(data_dir),
        subscribers=SubscribersStore(data_dir),
        status=StatusStore(data_dir),
        restaurants=RestaurantsStore(data_dir),
    )


def attach_stores(app: Flask) -> Stores:
    """Crée + attache le bundle à l'app (idempotent)."""
    existing = app.config.get("STORES")
    if isinstance(existing, Stores):
        return existing
    data_dir = app.config["SETTINGS"].data_dir
    stores = build_stores(data_dir)
    app.config["STORES"] = stores
    return stores


def get_stores() -> Stores:
    """Résout le bundle depuis l'app courante (lève si absent)."""
    stores = current_app.config.get("STORES")
    if not isinstance(stores, Stores):
        raise RuntimeError("STORES not attached — call attach_stores(app) in factory")
    return stores
