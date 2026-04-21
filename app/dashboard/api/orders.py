"""Endpoints commandes — liste + transitions d'état.

Routes :
- `GET /api/orders` : toutes les commandes
- `GET /api/orders/pending` : commandes en attente (pending + in_progress)
- `GET /api/orders/<order_id>` : détail
- `POST /api/orders/<order_id>/validate` : pending → in_progress (assigne compte)
- `POST /api/orders/<order_id>/delivered` : in_progress → delivered (marque compte used)
- `POST /api/orders/<order_id>/cancel` : pending/in_progress → cancelled (relâche compte)

Les transitions ne font PAS de validation stricte du graph — c'est l'admin
qui décide. Mais on soigne la cohérence côté AccountsStore (claim/release/used).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.core.exceptions import NotFoundError
from app.dashboard.security import api_login_required
from app.dashboard.stores import get_stores

logger = logging.getLogger(__name__)

bp = Blueprint("orders", __name__, url_prefix="/api/orders")


@bp.get("")
@api_login_required
def list_orders() -> object:
    return jsonify({"orders": get_stores().orders.all()})


@bp.get("/pending")
@api_login_required
def list_pending() -> object:
    orders = get_stores().orders
    pending = [*orders.by_status("pending"), *orders.by_status("in_progress")]
    return jsonify({"orders": pending, "total": len(pending)})


@bp.get("/<order_id>")
@api_login_required
def get_order(order_id: str) -> object:
    record = get_stores().orders.get(order_id)
    if record is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify(record)


@bp.post("/<order_id>/validate")
@api_login_required
def validate_order(order_id: str) -> object:
    """pending → in_progress, assigne auto un compte `full`."""
    stores = get_stores()
    order = stores.orders.get(order_id)
    if order is None:
        return jsonify({"ok": False, "error": "not_found"}), 404

    account = None
    if not order.get("account_email"):
        account = stores.accounts.claim_next_full()
        if account is None:
            return jsonify({"ok": False, "error": "no_full_account_available"}), 409
        stores.orders.assign_account(order_id, account["email"])

    updated = stores.orders.mark_in_progress(order_id)
    logger.info(
        "order validated",
        extra={"order_id": order_id, "account_email": updated.get("account_email")},
    )
    return jsonify({"ok": True, "order": updated})


@bp.post("/<order_id>/delivered")
@api_login_required
def deliver_order(order_id: str) -> object:
    stores = get_stores()
    order = stores.orders.get(order_id)
    if order is None:
        return jsonify({"ok": False, "error": "not_found"}), 404

    updated = stores.orders.mark_delivered(order_id)
    email = order.get("account_email")
    if email:
        try:
            stores.accounts.mark_used(email)
        except NotFoundError:
            logger.warning("account missing on delivery", extra={"email": email, "order_id": order_id})

    logger.info("order delivered", extra={"order_id": order_id})
    return jsonify({"ok": True, "order": updated})


@bp.post("/<order_id>/cancel")
@api_login_required
def cancel_order(order_id: str) -> object:
    stores = get_stores()
    order = stores.orders.get(order_id)
    if order is None:
        return jsonify({"ok": False, "error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "")

    updated = stores.orders.cancel(order_id, reason=reason)
    email = order.get("account_email")
    if email:
        try:
            stores.accounts.release(email)
        except NotFoundError:
            logger.warning("account missing on cancel", extra={"email": email, "order_id": order_id})

    logger.info("order cancelled", extra={"order_id": order_id, "reason": reason})
    return jsonify({"ok": True, "order": updated})
