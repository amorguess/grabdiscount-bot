"""Tests de app.storage.paths — noms canoniques."""

from __future__ import annotations

from app.storage import paths


def test_all_names_are_json():
    for name in (
        paths.ACCOUNTS,
        paths.ORDERS,
        paths.MESSAGES,
        paths.SUBSCRIBERS,
        paths.STATUS,
        paths.PENDING_REFERRALS,
        paths.RESTAURANTS,
    ):
        assert name.endswith(".json")


def test_names_are_distinct():
    names = [
        paths.ACCOUNTS,
        paths.ORDERS,
        paths.MESSAGES,
        paths.SUBSCRIBERS,
        paths.STATUS,
        paths.PENDING_REFERRALS,
        paths.RESTAURANTS,
    ]
    assert len(set(names)) == len(names)
