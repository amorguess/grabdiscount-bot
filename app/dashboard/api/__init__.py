"""Regroupement des blueprints API du dashboard.

Chaque sous-module expose un `bp` (`flask.Blueprint`) qu'on enregistre ici.
Centralise l'ordre d'enregistrement + le préfixe `/api`.
"""

from __future__ import annotations

from flask import Flask

from app.dashboard.api.accounts import bp as accounts_bp
from app.dashboard.api.admin import bp as admin_bp
from app.dashboard.api.auth import bp as auth_bp
from app.dashboard.api.health import bp as health_bp
from app.dashboard.api.messages import bp as messages_bp
from app.dashboard.api.orders import bp as orders_bp
from app.dashboard.api.restaurants import bp as restaurants_bp


def register_api_blueprints(app: Flask) -> None:
    """Attache tous les blueprints API à l'app."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(restaurants_bp)
