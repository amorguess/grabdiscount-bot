"""Endpoints comptes Grab — CRUD read + update léger.

Routes :
- `GET /api/accounts` : liste complète + compteurs par statut
- `GET /api/accounts/pool` : résumé du pool (ready / in_use / total)
- `GET /api/accounts/<email>` : détail d'un compte
- `POST /api/accounts/<email>` : met à jour status / grab_phone / grab_notes

Le status `used` passe `used_at` à now() ; repasser en `available` le remet à None.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from app.core.exceptions import NotFoundError
from app.dashboard.security import api_login_required
from app.dashboard.stores import get_stores
from app.storage.models import TS_FMT, AccountStatus

bp = Blueprint("accounts", __name__, url_prefix="/api/accounts")

_UPDATABLE_FIELDS = frozenset({"status", "grab_phone", "grab_notes", "grab_password"})


@bp.get("")
@api_login_required
def list_accounts() -> object:
    s = get_stores().accounts
    return jsonify(
        {
            "accounts": s.all(),
            "counts": s.count_by_status(),
        }
    )


@bp.get("/pool")
@api_login_required
def pool() -> object:
    counts = get_stores().accounts.count_by_status()
    return jsonify(
        {
            "ready": counts.get(AccountStatus.GRAB_READY.value, 0),
            "full": counts.get(AccountStatus.FULL.value, 0),
            "available": counts.get(AccountStatus.AVAILABLE.value, 0),
            "en_cours": counts.get(AccountStatus.EN_COURS.value, 0),
            "used": counts.get(AccountStatus.USED.value, 0),
            "failed": counts.get(AccountStatus.FAILED.value, 0),
            "total": sum(counts.values()),
        }
    )


@bp.get("/<path:email>")
@api_login_required
def get_account(email: str) -> object:
    record = get_stores().accounts.get(email)
    if record is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify(record)


@bp.post("/<path:email>")
@api_login_required
def update_account(email: str) -> object:
    payload = request.get_json(silent=True) or {}
    patch = {k: v for k, v in payload.items() if k in _UPDATABLE_FIELDS}
    if not patch:
        return jsonify({"ok": False, "error": "no_updatable_fields"}), 400

    # Gestion spéciale used_at quand on passe à/depuis `used`
    new_status = patch.get("status")
    if new_status == AccountStatus.USED.value:
        patch["used_at"] = datetime.now().strftime(TS_FMT)
    elif new_status == AccountStatus.AVAILABLE.value:
        patch["used_at"] = None

    try:
        updated = get_stores().accounts.update(email, **patch)
    except NotFoundError:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "account": updated})
