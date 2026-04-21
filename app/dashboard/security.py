"""Couche sécurité du dashboard : auth + rate limiting.

Deux rôles d'auth :
- **admin** : session Flask (`session["ok"]`) posée après login mot de passe.
  Couvre toutes les routes `/api/*` et `/*` admin (CRUD accounts, orders…).
- **employee** : cookie `emp_tok` persistant (7 j), valeur opaque dérivée du
  mot de passe employé. Usage restreint à quelques endpoints opérationnels
  (génération emails, lecture simple).

Le rate limiter est une classe testable — pas de dépendance Redis pour l'instant.
Si on dépasse 1 instance Flask ou 10k requêtes/min on passera à `flask-limiter`
avec backend Redis. Tant qu'on a 1 worker Gunicorn, in-memory suffit largement.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from threading import Lock
from typing import Any, TypeVar

from flask import current_app, jsonify, redirect, request, session

from app.core.config import Settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

SESSION_KEY = "ok"
EMPLOYEE_COOKIE = "emp_tok"


# ─── Décorateurs ──────────────────────────────────────────────────────


def login_required(view: F) -> F:
    """Redirige vers `/login` si pas de session admin.

    Pour les endpoints `/api/*` on retournerait plutôt 401 JSON — mais on
    préserve le comportement legacy (redirect) par compat navigateur.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not session.get(SESSION_KEY):
            return redirect("/login")
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def api_login_required(view: F) -> F:
    """Variante JSON : renvoie 401 au lieu de rediriger.

    Utilise ça pour les endpoints appelés par fetch() côté client —
    une redirect 302 vers HTML casse le JSON parsing.
    """

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not session.get(SESSION_KEY):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def employee_required(view: F) -> F:
    """Valide le cookie `emp_tok` (7 j). Renvoie 401 JSON si KO."""

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        expected = _employee_token(current_app.config["SETTINGS"])
        got = request.cookies.get(EMPLOYEE_COOKIE) or ""
        if not hmac.compare_digest(got, expected):
            return jsonify({"ok": False, "error": "auth"}), 401
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _employee_token(settings: Settings) -> str:
    """Dérive un token opaque (stable) depuis le mot de passe employé.

    HMAC-SHA256 avec `dashboard.secret` comme clef — évite de stocker le
    mot de passe en clair dans le cookie. Stable tant que les secrets ne
    changent pas → persistance 7 j sans session côté serveur.
    """
    return hmac.new(
        settings.dashboard.secret.encode("utf-8"),
        settings.dashboard.employee_password.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ─── Rate limiter login ───────────────────────────────────────────────


class LoginRateLimiter:
    """Sliding-window rate limit sur /login par IP.

    In-memory, thread-safe. `check_and_record()` est l'API principale :
    elle retourne `(allowed, remaining_attempts)`. Si `allowed=False`,
    l'endpoint doit renvoyer 429.

    La politique "ne pas compter les bons mots de passe" est déléguée à
    l'appelant : on appelle `record_failure()` seulement sur échec.

    Paramètres par défaut : 5 tentatives / 15 min.
    """

    __slots__ = ("_max_attempts", "_window_sec", "_attempts", "_lock", "_clock")

    def __init__(
        self,
        max_attempts: int = 5,
        window_sec: int = 900,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_sec = window_sec
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._clock = clock

    def is_allowed(self, ip: str) -> bool:
        """True si l'IP peut encore tenter. Ne consomme rien."""
        with self._lock:
            self._prune(ip)
            return len(self._attempts[ip]) < self._max_attempts

    def record_failure(self, ip: str) -> int:
        """Enregistre une tentative échouée. Retourne le compteur actuel."""
        now = self._clock()
        with self._lock:
            self._prune(ip)
            self._attempts[ip].append(now)
            return len(self._attempts[ip])

    def reset(self, ip: str) -> None:
        """Remet le compteur à 0 (appelé après login réussi)."""
        with self._lock:
            self._attempts.pop(ip, None)

    def remaining(self, ip: str) -> int:
        with self._lock:
            self._prune(ip)
            return max(0, self._max_attempts - len(self._attempts[ip]))

    def _prune(self, ip: str) -> None:
        """Supprime les tentatives hors fenêtre. Appelé sous lock."""
        now = self._clock()
        cutoff = now - self._window_sec
        self._attempts[ip] = [t for t in self._attempts[ip] if t > cutoff]


def get_login_limiter() -> LoginRateLimiter:
    """Récupère le rate limiter attaché à l'app (créé lazily)."""
    limiter = current_app.config.get("LOGIN_LIMITER")
    if limiter is None:
        limiter = LoginRateLimiter()
        current_app.config["LOGIN_LIMITER"] = limiter
    return limiter
