"""Tests de app.storage.subscribers.SubscribersStore."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.storage.models import TS_FMT
from app.storage.subscribers import PLAN_CAPS, SubscribersStore


@pytest.fixture
def store(data_dir: Path) -> SubscribersStore:
    return SubscribersStore(data_dir)


def _offset_ts(days: int = 0, hours: int = 0) -> str:
    return (datetime.now() + timedelta(days=days, hours=hours)).strftime(TS_FMT)


# ─── Base ────────────────────────────────────────────────────────────


def test_empty(store):
    assert store.all() == []
    assert store.get(42) is None
    assert store.is_active(42) is False
    assert store.can_order(42) == (False, "no_sub")


def test_add_subscriber(store):
    rec = store.add_or_renew(42, name="Alice", username="@alice")
    assert rec["user_id"] == 42
    assert rec["status"] == "active"
    assert rec["plan"] == "pro"
    assert store.is_active(42) is True


def test_renew_existing_resets_expires(store):
    store.add_or_renew(42, name="A", username="@a", days=30)
    rec = store.add_or_renew(42, name="A", username="@a", days=60)
    exp = datetime.strptime(rec["expires_at"], TS_FMT)
    assert exp > datetime.now() + timedelta(days=59)


def test_expire_then_is_inactive(store):
    store.add_or_renew(42, name="A", username="@a")
    assert store.expire(42) is True
    assert store.is_active(42) is False
    sub = store.get(42)
    assert sub["status"] == "expired"
    assert "expired_at" in sub


def test_block(store):
    store.block(42)
    sub = store.get(42)
    assert sub["status"] == "blocked"
    assert store.is_active(42) is False
    # Même après add_or_renew, block reste effectif jusqu'à unblock explicit
    # (le code legacy ne gère pas l'unblock → on teste juste le can_order)
    assert store.can_order(42) == (False, "blocked")


def test_expired_by_date_not_status(store):
    """Un sub ACTIVE mais expires_at < now → inactif."""
    store.add_or_renew(42, name="A", username="@a", days=30)
    # Force expires_at dans le passé (hack direct via store interne)
    store.store.mutate(lambda data: [{**s, "expires_at": _offset_ts(days=-1)} for s in data])
    assert store.is_active(42) is False
    assert store.can_order(42) == (False, "expired")


# ─── Parrainage ──────────────────────────────────────────────────────


def test_referral_grants_credit_to_parrain(store):
    store.add_or_renew(1, name="Parrain", username="@p")
    filleul = store.add_or_renew(2, name="Filleul", username="@f", parrain_id=1)
    assert filleul["parrain_id"] == 1
    assert filleul["had_referral_discount"] is True
    assert store.get_referral_credit(1) == 5
    assert store.get_filleuls(1) == [2]


def test_referral_not_applied_twice(store):
    store.add_or_renew(1, name="P", username="@p")
    store.add_or_renew(2, name="F", username="@f", parrain_id=1)
    store.add_or_renew(2, name="F", username="@f", parrain_id=1)  # renew
    # crédit parrain reste à 5 (pas de double)
    assert store.get_referral_credit(1) == 5


def test_self_referral_ignored(store):
    rec = store.add_or_renew(42, name="A", username="@a", parrain_id=42)
    assert rec.get("parrain_id") is None
    assert rec.get("had_referral_discount") is False


def test_consume_referral_credit(store):
    store.add_or_renew(1, name="P", username="@p")
    store.add_or_renew(2, name="F", username="@f", parrain_id=1)
    assert store.consume_referral_credit(1, 3) == 3
    assert store.get_referral_credit(1) == 2
    # Consommer plus que dispo → capé
    assert store.consume_referral_credit(1, 10) == 2
    assert store.get_referral_credit(1) == 0


# ─── Pause ───────────────────────────────────────────────────────────


def test_pause_blocks_ordering_and_extends_expiration(store):
    store.add_or_renew(42, name="A", username="@a", days=30)
    original_exp = datetime.strptime(store.get(42)["expires_at"], TS_FMT)
    assert store.pause(42, days=15) is True
    sub = store.get(42)
    new_exp = datetime.strptime(sub["expires_at"], TS_FMT)
    assert (new_exp - original_exp).days == 15
    assert store.can_order(42) == (False, "paused")


def test_resume_allows_ordering_again(store):
    store.add_or_renew(42, name="A", username="@a")
    store.pause(42, days=15)
    assert store.resume(42) is True
    ok, reason = store.can_order(42)
    assert ok and reason == "ok"


# ─── Plans & cap ─────────────────────────────────────────────────────


def test_pro_plan_has_no_cap(store):
    store.add_or_renew(42, name="A", username="@a", plan="pro")
    for _ in range(25):
        store.increment_orders(42)
    ok, reason = store.can_order(42)
    assert ok and reason == "ok"


def test_starter_plan_cap_at_20(store):
    store.add_or_renew(42, name="A", username="@a", plan="starter")
    for _ in range(20):
        store.increment_orders(42)
    ok, reason = store.can_order(42)
    assert not ok and reason == "cap_reached"
    used, cap = store.get_monthly_usage(42)
    assert used == 20
    assert cap == PLAN_CAPS["starter"]


def test_invalid_plan_falls_back_to_default(store):
    rec = store.add_or_renew(42, name="A", username="@a", plan="mystery")
    assert rec["plan"] == "pro"


def test_set_plan(store):
    store.add_or_renew(42, name="A", username="@a", plan="pro")
    assert store.set_plan(42, "starter") is True
    assert store.get(42)["plan"] == "starter"
    assert store.set_plan(42, "mystery") is False


def test_monthly_counter_resets_on_new_month(store):
    store.add_or_renew(42, name="A", username="@a", plan="starter")
    store.increment_orders(42)
    # Force le compteur à être sur un mois passé
    store.store.mutate(lambda d: [{**s, "monthly_orders_month": "2020-01", "monthly_orders": 19} for s in d])
    used, _ = store.get_monthly_usage(42)
    assert used == 0  # mois différent → effectivement 0
    # increment remet le compteur à 1 pour le mois courant
    store.increment_orders(42)
    used, _ = store.get_monthly_usage(42)
    assert used == 1


# ─── Expirations proches ────────────────────────────────────────────


def test_get_expiring_soon(store):
    store.add_or_renew(1, name="A", username="@a", days=1)
    store.add_or_renew(2, name="B", username="@b", days=10)
    expiring = store.get_expiring_soon(days=3)
    user_ids = {s["user_id"] for s in expiring}
    assert user_ids == {1}


def test_get_expired_recently(store):
    store.add_or_renew(1, name="A", username="@a")
    # Met expires_at à -2h
    store.store.mutate(lambda d: [{**s, "expires_at": _offset_ts(hours=-2)} for s in d])
    recent = store.get_expired_recently(hours=25)
    assert len(recent) == 1


# ─── Onboarding ──────────────────────────────────────────────────────


def test_onboarding_fields_roundtrip(store):
    store.add_or_renew(42, name="A", username="@a")
    assert store.set_onboarding_field(42, "district", "Thong Lo") is True
    assert store.set_onboarding_field(42, "source", "parrainage") is True
    assert store.set_onboarding_field(42, "frequency_stated", "2x/semaine") is True
    sub = store.get(42)
    assert sub["district"] == "Thong Lo"
    assert sub["onboarded_at"]  # 3/3 → flag
    assert store.is_onboarded(42) is True


def test_onboarding_unknown_field_rejected(store):
    store.add_or_renew(42, name="A", username="@a")
    assert store.set_onboarding_field(42, "age", "30") is False


def test_onboarding_stats(store):
    store.add_or_renew(1, name="A", username="@a")
    store.set_onboarding_field(1, "district", "Asoke")
    store.set_onboarding_field(1, "source", "ig")
    store.set_onboarding_field(1, "frequency_stated", "1x")

    store.add_or_renew(2, name="B", username="@b")
    store.set_onboarding_field(2, "district", "Asoke")  # partial

    stats = store.get_onboarding_stats()
    assert stats["total"] == 2
    assert stats["onboarded"] == 1
    assert stats["partial"] == 1
    assert stats["district"]["Asoke"] == 2


# ─── Extend ──────────────────────────────────────────────────────────


def test_extend_from_current_expiration(store):
    store.add_or_renew(42, name="A", username="@a", days=30)
    original_exp = datetime.strptime(store.get(42)["expires_at"], TS_FMT)
    store.extend(42, days=30)
    new_exp = datetime.strptime(store.get(42)["expires_at"], TS_FMT)
    assert (new_exp - original_exp).days == 30


def test_extend_from_now_if_expired(store):
    store.add_or_renew(42, name="A", username="@a")
    store.store.mutate(lambda d: [{**s, "expires_at": _offset_ts(days=-10)} for s in d])
    store.extend(42, days=30)
    sub = store.get(42)
    new_exp = datetime.strptime(sub["expires_at"], TS_FMT)
    # Doit être ~30j dans le futur (pas -10+30 = 20j)
    assert new_exp > datetime.now() + timedelta(days=29)
    assert sub["status"] == "active"
