"""Tests unitaires du module `app.dashboard.security` :
- LoginRateLimiter (fenêtre glissante, pruning, reset)
- Décorateurs `login_required`, `api_login_required`, `employee_required`
- Dérivation du token employé (stable, HMAC)
"""

from __future__ import annotations

from flask import Flask

from app.core.config import get_settings, reset_settings_cache
from app.dashboard.security import (
    EMPLOYEE_COOKIE,
    LoginRateLimiter,
    _employee_token,
    api_login_required,
    employee_required,
    login_required,
)

# ─── LoginRateLimiter ─────────────────────────────────────────────────


def test_rate_limiter_allows_up_to_max() -> None:
    rl = LoginRateLimiter(max_attempts=3, window_sec=60)
    for _ in range(3):
        assert rl.is_allowed("1.2.3.4")
        rl.record_failure("1.2.3.4")
    assert not rl.is_allowed("1.2.3.4")


def test_rate_limiter_isolates_per_ip() -> None:
    rl = LoginRateLimiter(max_attempts=2, window_sec=60)
    rl.record_failure("1.1.1.1")
    rl.record_failure("1.1.1.1")
    assert not rl.is_allowed("1.1.1.1")
    assert rl.is_allowed("2.2.2.2")


def test_rate_limiter_window_expires() -> None:
    """Avec clock injectable, on avance de 61 s et les tentatives sont nettoyées."""
    clock = {"t": 1000.0}
    rl = LoginRateLimiter(max_attempts=2, window_sec=60, clock=lambda: clock["t"])
    rl.record_failure("ip")
    rl.record_failure("ip")
    assert not rl.is_allowed("ip")
    clock["t"] += 61
    assert rl.is_allowed("ip")
    assert rl.remaining("ip") == 2


def test_rate_limiter_reset() -> None:
    rl = LoginRateLimiter(max_attempts=2, window_sec=60)
    rl.record_failure("ip")
    rl.record_failure("ip")
    assert not rl.is_allowed("ip")
    rl.reset("ip")
    assert rl.is_allowed("ip")
    assert rl.remaining("ip") == 2


def test_rate_limiter_remaining_counts_down() -> None:
    rl = LoginRateLimiter(max_attempts=5, window_sec=60)
    assert rl.remaining("ip") == 5
    rl.record_failure("ip")
    assert rl.remaining("ip") == 4


# ─── Décorateurs ─────────────────────────────────────────────────────


def _make_app() -> Flask:
    reset_settings_cache()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-key-please-change-me-12345678"
    app.config["SETTINGS"] = get_settings()
    app.config["TESTING"] = True
    return app


def test_login_required_redirects_when_anonymous() -> None:
    app = _make_app()

    @app.route("/protected")
    @login_required
    def protected() -> str:
        return "ok"

    with app.test_client() as c:
        resp = c.get("/protected", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")


def test_login_required_allows_when_session_set() -> None:
    app = _make_app()

    @app.route("/protected")
    @login_required
    def protected() -> str:
        return "ok"

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["ok"] = True
        resp = c.get("/protected")
        assert resp.status_code == 200
        assert resp.data == b"ok"


def test_api_login_required_returns_401_json() -> None:
    app = _make_app()

    @app.route("/api/secret")
    @api_login_required
    def secret() -> str:
        return "ok"

    with app.test_client() as c:
        resp = c.get("/api/secret")
        assert resp.status_code == 401
        assert resp.get_json() == {"ok": False, "error": "unauthorized"}


def test_employee_required_accepts_valid_token() -> None:
    app = _make_app()

    @app.route("/emp")
    @employee_required
    def emp() -> str:
        return "ok"

    token = _employee_token(app.config["SETTINGS"])
    with app.test_client() as c:
        c.set_cookie(EMPLOYEE_COOKIE, token)
        resp = c.get("/emp")
        assert resp.status_code == 200


def test_employee_required_rejects_wrong_token() -> None:
    app = _make_app()

    @app.route("/emp")
    @employee_required
    def emp() -> str:
        return "ok"

    with app.test_client() as c:
        c.set_cookie(EMPLOYEE_COOKIE, "wrong")
        resp = c.get("/emp")
        assert resp.status_code == 401


def test_employee_required_rejects_missing_cookie() -> None:
    app = _make_app()

    @app.route("/emp")
    @employee_required
    def emp() -> str:
        return "ok"

    with app.test_client() as c:
        resp = c.get("/emp")
        assert resp.status_code == 401


# ─── Token employé ────────────────────────────────────────────────────


def test_employee_token_is_stable() -> None:
    reset_settings_cache()
    s = get_settings()
    assert _employee_token(s) == _employee_token(s)


def test_employee_token_is_hex_64() -> None:
    reset_settings_cache()
    s = get_settings()
    tok = _employee_token(s)
    assert len(tok) == 64
    int(tok, 16)  # valid hex
