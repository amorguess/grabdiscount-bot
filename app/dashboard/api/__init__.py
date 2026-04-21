"""Regroupement des blueprints API du dashboard.

Chaque sous-module expose un `bp` (`flask.Blueprint`) qu'on enregistre ici.
Centralise l'ordre d'enregistrement + le préfixe `/api`.
"""

from __future__ import annotations

from flask import Flask

from app.dashboard.api.auth import bp as auth_bp
from app.dashboard.api.health import bp as health_bp
from app.dashboard.api.restaurants import bp as restaurants_bp


def register_api_blueprints(app: Flask) -> None:
    """Attache tous les blueprints API à l'app."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(restaurants_bp)
