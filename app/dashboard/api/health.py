"""Endpoint `/api/health` — liveness probe.

Utilisé par UptimeRobot / Grafana pour monitorer que l'app répond.
Renvoie un payload minimal : statut + version du package.

Aucune auth — c'est le but (probe externe).
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app import __version__

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/health")
def health() -> tuple[object, int]:
    """Renvoie 200 tant que le process tourne."""
    return jsonify({"status": "ok", "version": __version__}), 200
