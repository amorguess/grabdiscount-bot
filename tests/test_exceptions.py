"""Tests de app.core.exceptions — hiérarchie."""

from __future__ import annotations

from app.core.exceptions import (
    AlreadyExistsError,
    ConfigError,
    GrabError,
    IntegrationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    StorageCorruptError,
    StorageError,
    StorageLockTimeout,
)


def test_all_inherit_from_grab_error():
    for cls in (
        ConfigError,
        StorageError,
        StorageCorruptError,
        StorageLockTimeout,
        NotFoundError,
        AlreadyExistsError,
        PermissionDeniedError,
        IntegrationError,
        RateLimitedError,
    ):
        assert issubclass(cls, GrabError)


def test_storage_subhierarchy():
    assert issubclass(StorageCorruptError, StorageError)
    assert issubclass(StorageLockTimeout, StorageError)


def test_rate_limited_is_integration_error():
    assert issubclass(RateLimitedError, IntegrationError)


def test_exceptions_accept_messages():
    e = ConfigError("missing BOT_TOKEN")
    assert str(e) == "missing BOT_TOKEN"
