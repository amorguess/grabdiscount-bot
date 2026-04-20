"""OrdersStore — accès typé à orders.json.

Cycle de vie d'une commande :

    pending → in_progress → delivered
                         ↘ cancelled

Transitions gérées atomiquement via `JSONStore.mutate()`. Les `order_id`
sont générés ici (uuid4 court) pour découpler du user_id et garantir
l'unicité même si un user commande plusieurs fois.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.core.exceptions import NotFoundError
from app.storage import paths
from app.storage.base import JSONStore
from app.storage.models import TS_FMT, OrderRecord

OrderStatus = Literal["pending", "in_progress", "delivered", "cancelled"]


class OrdersStore:
    """Opérations métier sur orders.json."""

    __slots__ = ("_store",)

    def __init__(self, data_dir: Path) -> None:
        self._store: JSONStore[list[OrderRecord]] = JSONStore(data_dir / paths.ORDERS, default=list, indent=2)

    # ─── Lecture ──────────────────────────────────────────────────────

    def all(self) -> list[OrderRecord]:
        return list(self._store.read())

    def get(self, order_id: str) -> OrderRecord | None:
        for o in self._store.read():
            if o.get("order_id") == order_id:
                return o
        return None

    def by_user(self, user_id: int) -> list[OrderRecord]:
        return [o for o in self._store.read() if o.get("user_id") == user_id]

    def by_status(self, status: OrderStatus) -> list[OrderRecord]:
        return [o for o in self._store.read() if o.get("status") == status]

    def active_for_user(self, user_id: int) -> OrderRecord | None:
        """La dernière commande non-terminale (pending/in_progress) du user."""
        active = [
            o
            for o in self._store.read()
            if o.get("user_id") == user_id and o.get("status") in ("pending", "in_progress")
        ]
        return active[-1] if active else None

    # ─── Écriture ─────────────────────────────────────────────────────

    def create(
        self,
        *,
        user_id: int,
        user_name: str,
        user_username: str = "",
        screenshot_path: str = "",
        address: str = "",
    ) -> OrderRecord:
        """Crée une commande en état `pending`. Retourne l'enregistrement."""
        now = datetime.now().strftime(TS_FMT)
        record: OrderRecord = {
            "order_id": _generate_id(),
            "user_id": user_id,
            "user_name": user_name,
            "user_username": user_username,
            "screenshot_path": screenshot_path,
            "address": address,
            "account_email": "",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "admin_note": "",
        }
        self._store.mutate(lambda data: [*data, record])
        return record

    def assign_account(self, order_id: str, account_email: str) -> OrderRecord:
        """Associe un compte Grab à la commande."""
        return self._patch(order_id, {"account_email": account_email})

    def set_address(self, order_id: str, address: str) -> OrderRecord:
        return self._patch(order_id, {"address": address})

    def transition(self, order_id: str, to: OrderStatus) -> OrderRecord:
        """Change le statut d'une commande (pas de validation du graph)."""
        return self._patch(order_id, {"status": to})

    def mark_in_progress(self, order_id: str) -> OrderRecord:
        return self.transition(order_id, "in_progress")

    def mark_delivered(self, order_id: str) -> OrderRecord:
        return self.transition(order_id, "delivered")

    def cancel(self, order_id: str, reason: str = "") -> OrderRecord:
        patch: dict[str, object] = {"status": "cancelled"}
        if reason:
            patch["admin_note"] = reason
        return self._patch(order_id, patch)

    def add_admin_note(self, order_id: str, note: str) -> OrderRecord:
        return self._patch(order_id, {"admin_note": note})

    # ─── Helpers internes ─────────────────────────────────────────────

    def _patch(self, order_id: str, fields: dict[str, object]) -> OrderRecord:
        now = datetime.now().strftime(TS_FMT)

        def _mutator(data: list[OrderRecord]) -> list[OrderRecord]:
            for o in data:
                if o.get("order_id") == order_id:
                    o.update(fields)  # type: ignore[typeddict-item]
                    o["updated_at"] = now
                    return data
            raise NotFoundError(f"commande {order_id} introuvable")

        self._store.mutate(_mutator)
        found = self.get(order_id)
        assert found is not None
        return found

    @property
    def store(self) -> JSONStore[list[OrderRecord]]:
        return self._store


def _generate_id() -> str:
    """Court ID unique (12 chars)."""
    return uuid.uuid4().hex[:12]
