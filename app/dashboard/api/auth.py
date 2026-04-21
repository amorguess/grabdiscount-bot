"""Blueprint d'authentification : `/login`, `/logout`, `/api/auth/status`.

Deux modes :
- **Formulaire HTML** classique (POST form-data) pour compat navigateur.
- **API JSON** (POST application/json) pour appels fetch() depuis la Mini App.

La réponse 429 (rate limit dépassé) est renvoyée dans les deux formats
selon le `Accept` header.
"""

from __future__ import annotations

import hmac
import logging

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.dashboard.security import SESSION_KEY, get_login_limiter

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


def _wants_json() -> bool:
    """Détecte si le client veut du JSON (fetch) ou du HTML (form)."""
    if request.is_json:
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


def _extract_password() -> str:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return str(payload.get("password") or payload.get("pwd") or "")
    return str(request.form.get("password") or request.form.get("pwd") or "")


@bp.post("/login")
def login() -> tuple[object, int] | object:
    settings = current_app.config["SETTINGS"]
    limiter = get_login_limiter()
    ip = request.remote_addr or "unknown"

    if not limiter.is_allowed(ip):
        logger.warning("login rate limited", extra={"ip": ip})
        return jsonify({"ok": False, "error": "rate_limited"}), 429

    submitted = _extract_password()
    expected = settings.dashboard.password

    # `compare_digest` évite un timing attack sur le mot de passe.
    if submitted and hmac.compare_digest(submitted, expected):
        session[SESSION_KEY] = True
        limiter.reset(ip)
        logger.info("login ok", extra={"ip": ip})
        if _wants_json():
            return jsonify({"ok": True})
        return redirect("/")

    count = limiter.record_failure(ip)
    logger.info("login failed", extra={"ip": ip, "attempt": count})
    if _wants_json():
        return jsonify({"ok": False, "error": "invalid_password"}), 401
    return jsonify({"ok": False, "error": "invalid_password"}), 401


@bp.post("/logout")
@bp.get("/logout")
def logout() -> object:
    session.clear()
    if _wants_json():
        return jsonify({"ok": True})
    return redirect("/login")


@bp.get("/api/auth/status")
def auth_status() -> object:
    """Renvoie l'état de la session (pour Mini App)."""
    return jsonify({"authenticated": bool(session.get(SESSION_KEY))})
