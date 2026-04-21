"""Endpoints admin — statistiques agrégées + toggle disponibilité.

Routes :
- `GET  /api/admin/stats` : compteurs agrégés (accounts, orders, messages, subs)
- `GET  /api/admin/dispo` : état actuel (dispo ouvert/fermé)
- `POST /api/admin/dispo` : toggle / set explicite

Tout est derrière `api_login_required` (401 JSON pour les fetch).
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from app.dashboard.security import api_login_required
from app.dashboard.stores import get_stores
from app.storage.models import AccountStatus

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/stats")
@api_login_required
def stats() -> object:
    """Agrège les compteurs utiles pour la home du dashboard."""
    s = get_stores()

    acc_counts = s.accounts.count_by_status()
    orders_all = s.orders.all()
    msgs_unread = s.messages.unread_total()
    subs_active = sum(1 for sub in s.subscribers.all() if s.subscribers.is_active(int(sub["user_id"])))
    total_subs = len(s.subscribers.all())

    # Revenue proxy : non-cancelled orders (à affiner quand on aura les prix)
    total_orders = len(orders_all)
    pending = sum(1 for o in orders_all if o.get("status") == "pending")
    in_progress = sum(1 for o in orders_all if o.get("status") == "in_progress")
    delivered = sum(1 for o in orders_all if o.get("status") == "delivered")
    cancelled = sum(1 for o in orders_all if o.get("status") == "cancelled")

    # Série 7 jours : nombre de commandes livrées par jour (MM-DD)
    today = date.today()
    day_labels: list[str] = []
    day_counts: list[int] = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        day_labels.append(d.strftime("%m-%d"))
        prefix = d.isoformat()
        day_counts.append(
            sum(
                1
                for o in orders_all
                if o.get("status") == "delivered" and (o.get("updated_at") or "").startswith(prefix)
            )
        )

    return jsonify(
        {
            "accounts": {
                "total": sum(acc_counts.values()),
                "by_status": acc_counts,
                "available": acc_counts.get(AccountStatus.AVAILABLE.value, 0),
                "full": acc_counts.get(AccountStatus.FULL.value, 0),
                "used": acc_counts.get(AccountStatus.USED.value, 0),
            },
            "orders": {
                "total": total_orders,
                "pending": pending,
                "in_progress": in_progress,
                "delivered": delivered,
                "cancelled": cancelled,
            },
            "messages": {
                "unread": msgs_unread,
            },
            "subscribers": {
                "total": total_subs,
                "active": subs_active,
            },
            "series": {
                "days": day_labels,
                "delivered_per_day": day_counts,
            },
        }
    )


@bp.get("/dispo")
@api_login_required
def dispo_get() -> object:
    return jsonify(get_stores().status.read())


@bp.post("/dispo")
@api_login_required
def dispo_set() -> object:
    payload = request.get_json(silent=True) or {}
    if "dispo" not in payload:
        return jsonify({"ok": False, "error": "missing_field: dispo"}), 400
    record = get_stores().status.set_dispo(bool(payload["dispo"]))
    return jsonify({"ok": True, **record})
