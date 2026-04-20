"""SubscribersStore — accès typé à subscribers.json.

Réimplémente la logique métier de `subscribers.py` legacy en utilisant
JSONStore pour le stockage atomique. Compatible ascendant : même shape
JSON, mêmes sémantiques de `is_active` / `can_order`.

Différences notables avec la version legacy :
- Tous les états mutables passent par `JSONStore.mutate()` → plus de
  race condition read-then-write.
- Business rules (parrainage, pause, cap mensuel) restent identiques.
- Interface orientée objet (`store.is_active(uid)`) au lieu de fonctions
  module-level (`subscribers.is_active(uid)`).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Literal

from app.storage import paths
from app.storage.base import JSONStore
from app.storage.models import (
    TS_FMT,
    Plan,
    SubscriberRecord,
    SubscriberStatus,
)

# Caps mensuels (−1 = illimité)
PLAN_CAPS: Final[dict[str, int]] = {
    Plan.STARTER.value: 20,
    Plan.PRO.value: -1,
}
PLAN_PRICES_EUR: Final[dict[str, int]] = {
    Plan.STARTER.value: 20,
    Plan.PRO.value: 20,
}
DEFAULT_PLAN: Final[str] = Plan.PRO.value

ONBOARDING_FIELDS: Final[tuple[str, ...]] = ("district", "source", "frequency_stated")

# Raisons de refus pour `can_order()`
CanOrderReason = Literal["ok", "no_sub", "blocked", "paused", "expired", "cap_reached"]


class SubscribersStore:
    """Opérations métier sur subscribers.json."""

    __slots__ = ("_store",)

    def __init__(self, data_dir: Path) -> None:
        self._store: JSONStore[list[SubscriberRecord]] = JSONStore(
            data_dir / paths.SUBSCRIBERS, default=list, indent=2
        )

    # ─── Lecture ──────────────────────────────────────────────────────

    def all(self) -> list[SubscriberRecord]:
        return list(self._store.read())

    def get(self, user_id: int) -> SubscriberRecord | None:
        for s in self._store.read():
            if s.get("user_id") == user_id:
                return s
        return None

    def is_active(self, user_id: int, *, now: datetime | None = None) -> bool:
        """Abonnement actif et non expiré (ignore la pause)."""
        now = now or datetime.now()
        s = self.get(user_id)
        if not s:
            return False
        if s.get("status") == SubscriberStatus.BLOCKED.value:
            return False
        if s.get("status") != SubscriberStatus.ACTIVE.value:
            return False
        exp = _parse_ts(s.get("expires_at"))
        if exp and exp < now:
            return False
        return True

    def get_active(self) -> list[SubscriberRecord]:
        return [s for s in self._store.read() if self.is_active(s["user_id"])]

    def get_expiring_soon(self, days: int = 3) -> list[SubscriberRecord]:
        now = datetime.now()
        limit = now + timedelta(days=days)
        return [
            s
            for s in self._store.read()
            if s.get("status") == SubscriberStatus.ACTIVE.value
            and (exp := _parse_ts(s.get("expires_at"))) is not None
            and now <= exp <= limit
        ]

    def get_expired_recently(self, hours: int = 25) -> list[SubscriberRecord]:
        now = datetime.now()
        threshold = now - timedelta(hours=hours)
        return [
            s
            for s in self._store.read()
            if s.get("status") == SubscriberStatus.ACTIVE.value
            and (exp := _parse_ts(s.get("expires_at"))) is not None
            and threshold <= exp <= now
        ]

    def get_referral_credit(self, user_id: int) -> int:
        s = self.get(user_id)
        return int(s.get("referral_credit_eur") or 0) if s else 0

    def get_filleuls(self, user_id: int) -> list[int]:
        s = self.get(user_id)
        return list(s.get("filleuls") or []) if s else []

    def get_monthly_usage(self, user_id: int) -> tuple[int, int]:
        """Retourne (orders_ce_mois, cap_plan). cap=-1 → illimité."""
        s = self.get(user_id)
        if not s:
            return (0, PLAN_CAPS[DEFAULT_PLAN])
        plan = s.get("plan") or DEFAULT_PLAN
        cap = PLAN_CAPS.get(plan, PLAN_CAPS[DEFAULT_PLAN])
        now_month = datetime.now().strftime("%Y-%m")
        if s.get("monthly_orders_month") != now_month:
            return (0, cap)
        return (int(s.get("monthly_orders") or 0), cap)

    def can_order(self, user_id: int) -> tuple[bool, str]:
        """Vérifie la capacité à commander. Retourne (ok, raison)."""
        s = self.get(user_id)
        if not s:
            return (False, "no_sub")
        if s.get("status") == SubscriberStatus.BLOCKED.value:
            return (False, "blocked")
        paused = _parse_ts(s.get("paused_until"))
        if paused and paused > datetime.now():
            return (False, "paused")
        if s.get("status") != SubscriberStatus.ACTIVE.value:
            return (False, "expired")
        exp = _parse_ts(s.get("expires_at"))
        if exp and exp < datetime.now():
            return (False, "expired")
        used, cap = self.get_monthly_usage(user_id)
        if cap != -1 and used >= cap:
            return (False, "cap_reached")
        return (True, "ok")

    def is_onboarded(self, user_id: int) -> bool:
        s = self.get(user_id)
        return bool(s and s.get("onboarded_at"))

    # ─── Écriture ─────────────────────────────────────────────────────

    def add_or_renew(
        self,
        user_id: int,
        *,
        name: str,
        username: str,
        invite_link: str = "",
        days: int = 30,
        plan: str = DEFAULT_PLAN,
        parrain_id: int | None = None,
    ) -> SubscriberRecord:
        """Ajoute ou renouvelle un abonné.

        Applique la logique parrainage :
        - filleul doit être différent du parrain
        - crédit −5€ appliqué uniquement sur le 1er abonnement jamais remisé
        - parrain reçoit +5€ en `referral_credit_eur`
        """
        plan = plan if plan in PLAN_CAPS else DEFAULT_PLAN
        now = datetime.now()
        expires = now + timedelta(days=days)

        # Anti-self-referral
        if parrain_id == user_id:
            parrain_id = None

        result: dict[str, SubscriberRecord] = {}

        def _mutator(data: list[SubscriberRecord]) -> list[SubscriberRecord]:
            idx = _index_of(data, user_id)
            apply_referral = parrain_id is not None and (
                idx < 0 or not data[idx].get("had_referral_discount")
            )

            if idx >= 0:
                entry = data[idx]
                entry.update(
                    {
                        "name": name,
                        "username": username,
                        "status": SubscriberStatus.ACTIVE.value,
                        "plan": plan,
                        "subscribed_at": now.strftime(TS_FMT),
                        "expires_at": expires.strftime(TS_FMT),
                        "invite_link": invite_link or entry.get("invite_link", ""),
                        "paused_until": None,
                    }
                )
                if apply_referral:
                    entry["parrain_id"] = parrain_id
                    entry["had_referral_discount"] = True
            else:
                entry = {
                    "user_id": user_id,
                    "username": username,
                    "name": name,
                    "status": SubscriberStatus.ACTIVE.value,
                    "plan": plan,
                    "subscribed_at": now.strftime(TS_FMT),
                    "expires_at": expires.strftime(TS_FMT),
                    "paused_until": None,
                    "invite_link": invite_link,
                    "orders_count": 0,
                    "monthly_orders": 0,
                    "monthly_orders_month": now.strftime("%Y-%m"),
                    "parrain_id": parrain_id if apply_referral else None,
                    "filleuls": [],
                    "referral_credit_eur": 0,
                    "had_referral_discount": bool(apply_referral and parrain_id),
                }
                data.append(entry)

            # Crédit parrain : +5€
            if apply_referral and parrain_id is not None:
                for p in data:
                    if p.get("user_id") == parrain_id:
                        p["referral_credit_eur"] = int(p.get("referral_credit_eur") or 0) + 5
                        filleuls = list(p.get("filleuls") or [])
                        if user_id not in filleuls:
                            filleuls.append(user_id)
                        p["filleuls"] = filleuls
                        break

            result["rec"] = entry
            return data

        self._store.mutate(_mutator)
        return result["rec"]

    def expire(self, user_id: int) -> bool:
        return self._patch_if_match(
            user_id,
            match=lambda s: s.get("status") == SubscriberStatus.ACTIVE.value,
            updates={
                "status": SubscriberStatus.EXPIRED.value,
                "expired_at": datetime.now().strftime(TS_FMT),
            },
        )

    def block(self, user_id: int) -> bool:
        """Bloque un user — crée un record vide si non-abonné."""

        def _mutator(data: list[SubscriberRecord]) -> list[SubscriberRecord]:
            idx = _index_of(data, user_id)
            if idx >= 0:
                data[idx]["status"] = SubscriberStatus.BLOCKED.value
            else:
                data.append(
                    {
                        "user_id": user_id,
                        "username": "",
                        "name": "Inconnu",
                        "status": SubscriberStatus.BLOCKED.value,
                        "subscribed_at": datetime.now().strftime(TS_FMT),
                        "expires_at": "",
                        "invite_link": "",
                        "orders_count": 0,
                    }
                )
            return data

        self._store.mutate(_mutator)
        return True

    def extend(self, user_id: int, days: int = 30) -> bool:
        """Prolonge depuis expires_at actuel (ou maintenant si expiré)."""

        def _patch(s: SubscriberRecord) -> None:
            base = _parse_ts(s.get("expires_at")) or datetime.now()
            base = max(base, datetime.now())
            s["expires_at"] = (base + timedelta(days=days)).strftime(TS_FMT)
            s["status"] = SubscriberStatus.ACTIVE.value

        return self._patch_with(user_id, _patch)

    def increment_orders(self, user_id: int) -> None:
        """Incrémente les compteurs lifetime + mensuel (reset auto si mois change)."""
        now_month = datetime.now().strftime("%Y-%m")

        def _patch(s: SubscriberRecord) -> None:
            if s.get("monthly_orders_month") != now_month:
                s["monthly_orders"] = 0
                s["monthly_orders_month"] = now_month
            s["orders_count"] = int(s.get("orders_count") or 0) + 1
            s["monthly_orders"] = int(s.get("monthly_orders") or 0) + 1

        self._patch_with(user_id, _patch)

    def pause(self, user_id: int, days: int = 30) -> bool:
        """Met en pause et prolonge expires_at d'autant (les jours ne sont pas volés)."""
        now = datetime.now()

        def _patch(s: SubscriberRecord) -> None:
            s["paused_until"] = (now + timedelta(days=days)).strftime(TS_FMT)
            base = _parse_ts(s.get("expires_at")) or now
            s["expires_at"] = (base + timedelta(days=days)).strftime(TS_FMT)

        return self._patch_with(user_id, _patch)

    def resume(self, user_id: int) -> bool:
        return self._patch_with(user_id, lambda s: s.__setitem__("paused_until", None))

    def set_plan(self, user_id: int, plan: str) -> bool:
        if plan not in PLAN_CAPS:
            return False
        return self._patch_with(user_id, lambda s: s.__setitem__("plan", plan))

    def consume_referral_credit(self, user_id: int, amount: int) -> int:
        """Consomme jusqu'à `amount` EUR. Retourne le montant effectivement consommé."""
        used_ref: dict[str, int] = {"v": 0}

        def _patch(s: SubscriberRecord) -> None:
            have = int(s.get("referral_credit_eur") or 0)
            take = min(have, int(amount))
            s["referral_credit_eur"] = have - take
            used_ref["v"] = take

        self._patch_with(user_id, _patch)
        return used_ref["v"]

    def set_onboarding_field(self, user_id: int, field: str, value: str) -> bool:
        if field not in ONBOARDING_FIELDS:
            return False

        def _patch(s: SubscriberRecord) -> None:
            s[field] = value  # type: ignore[literal-required]
            if all(s.get(f) for f in ONBOARDING_FIELDS) and not s.get("onboarded_at"):
                s["onboarded_at"] = datetime.now().strftime(TS_FMT)

        return self._patch_with(user_id, _patch)

    def get_onboarding_stats(self) -> dict[str, object]:
        from collections import Counter

        subs = self._store.read()
        stats: dict[str, object] = {"total": len(subs), "onboarded": 0, "partial": 0}
        counters: dict[str, Counter[str]] = {f: Counter() for f in ONBOARDING_FIELDS}
        onboarded = 0
        partial = 0
        for s in subs:
            if s.get("onboarded_at"):
                onboarded += 1
            elif any(s.get(f) for f in ONBOARDING_FIELDS):
                partial += 1
            for f in ONBOARDING_FIELDS:
                v = s.get(f)
                if v:
                    counters[f][v] += 1
        stats["onboarded"] = onboarded
        stats["partial"] = partial
        for f, c in counters.items():
            stats[f] = c
        return stats

    # ─── Helpers internes ─────────────────────────────────────────────

    def _patch_with(self, user_id: int, patch_fn) -> bool:
        found = {"v": False}

        def _mutator(data: list[SubscriberRecord]) -> list[SubscriberRecord]:
            for s in data:
                if s.get("user_id") == user_id:
                    patch_fn(s)
                    found["v"] = True
                    return data
            return data

        self._store.mutate(_mutator)
        return found["v"]

    def _patch_if_match(
        self, user_id: int, *, match, updates: dict[str, object]
    ) -> bool:
        found = {"v": False}

        def _mutator(data: list[SubscriberRecord]) -> list[SubscriberRecord]:
            for s in data:
                if s.get("user_id") == user_id and match(s):
                    s.update(updates)  # type: ignore[typeddict-item]
                    found["v"] = True
                    return data
            return data

        self._store.mutate(_mutator)
        return found["v"]

    @property
    def store(self) -> JSONStore[list[SubscriberRecord]]:
        return self._store


def _parse_ts(value: object) -> datetime | None:
    """Parse un timestamp ISO. Retourne None si absent ou invalide."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, TS_FMT)
    except ValueError:
        return None


def _index_of(data: list[SubscriberRecord], user_id: int) -> int:
    for i, s in enumerate(data):
        if s.get("user_id") == user_id:
            return i
    return -1
