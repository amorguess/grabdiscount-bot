"""
subscribers.py — Gestion des abonnés GrabDiscount
==================================================
subscribers.json dans /data/
[
  {
    "user_id": 123456789,
    "username": "@tonino",
    "name": "Tonino",
    "status": "active",          // active | expired | blocked
    "subscribed_at": "2026-04-19T20:00:00",
    "expires_at": "2026-05-19T20:00:00",
    "invite_link": "https://t.me/+xxxxx",
    "orders_count": 0
  }
]
"""
from __future__ import annotations
import os, json, fcntl, threading
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR  = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
SUBS_FILE = DATA_DIR / "subscribers.json"
TS_FMT    = "%Y-%m-%dT%H:%M:%S"

_io_lock = threading.Lock()


def _read_subs() -> list:
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_subs(data: list) -> None:
    tmp = str(SUBS_FILE) + ".tmp"
    with _io_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, str(SUBS_FILE))


# ── Lecture ───────────────────────────────────────────────

def is_active(user_id: int) -> bool:
    """Retourne True si l'utilisateur a un abonnement actif non expiré."""
    now = datetime.now()
    for s in _read_subs():
        if s.get("user_id") != user_id:
            continue
        if s.get("status") == "blocked":
            return False
        if s.get("status") == "active":
            expires_at = s.get("expires_at", "")
            if expires_at:
                try:
                    if datetime.strptime(expires_at, TS_FMT) < now:
                        return False
                except ValueError:
                    pass
            return True
    return False


def get_subscriber(user_id: int) -> dict | None:
    for s in _read_subs():
        if s.get("user_id") == user_id:
            return s
    return None


def get_all() -> list:
    return _read_subs()


def get_active() -> list:
    now = datetime.now()
    result = []
    for s in _read_subs():
        if s.get("status") != "active":
            continue
        expires_at = s.get("expires_at", "")
        if expires_at:
            try:
                if datetime.strptime(expires_at, TS_FMT) < now:
                    continue
            except ValueError:
                pass
        result.append(s)
    return result


def get_expiring_soon(days: int = 3) -> list:
    """Abonnés actifs qui expirent dans les prochains `days` jours."""
    now   = datetime.now()
    limit = now + timedelta(days=days)
    result = []
    for s in _read_subs():
        if s.get("status") != "active":
            continue
        expires_at = s.get("expires_at", "")
        if not expires_at:
            continue
        try:
            exp_dt = datetime.strptime(expires_at, TS_FMT)
            if now <= exp_dt <= limit:
                result.append(s)
        except ValueError:
            pass
    return result


def get_expired_recently(hours: int = 25) -> list:
    """Abonnés dont l'abonnement a expiré dans les dernières `hours` heures."""
    now       = datetime.now()
    threshold = now - timedelta(hours=hours)
    result = []
    for s in _read_subs():
        if s.get("status") != "active":
            continue
        expires_at = s.get("expires_at", "")
        if not expires_at:
            continue
        try:
            exp_dt = datetime.strptime(expires_at, TS_FMT)
            if threshold <= exp_dt <= now:
                result.append(s)
        except ValueError:
            pass
    return result


# ── Écriture ─────────────────────────────────────────────

def add_subscriber(user_id: int, name: str, username: str,
                   invite_link: str = "", days: int = 30) -> dict:
    """Ajoute ou réactive un abonné. Retourne l'entrée créée/mise à jour."""
    now     = datetime.now()
    expires = now + timedelta(days=days)
    subs    = _read_subs()

    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i].update({
                "name":           name,
                "username":       username,
                "status":         "active",
                "subscribed_at":  now.strftime(TS_FMT),
                "expires_at":     expires.strftime(TS_FMT),
                "invite_link":    invite_link or s.get("invite_link", ""),
            })
            _write_subs(subs)
            return subs[i]

    entry = {
        "user_id":      user_id,
        "username":     username,
        "name":         name,
        "status":       "active",
        "subscribed_at": now.strftime(TS_FMT),
        "expires_at":   expires.strftime(TS_FMT),
        "invite_link":  invite_link,
        "orders_count": 0,
    }
    subs.append(entry)
    _write_subs(subs)
    return entry


def expire_subscriber(user_id: int) -> bool:
    """Passe un abonné à 'expired'. Retourne True si trouvé."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id and s.get("status") == "active":
            subs[i]["status"]     = "expired"
            subs[i]["expired_at"] = datetime.now().strftime(TS_FMT)
            _write_subs(subs)
            return True
    return False


def block_subscriber(user_id: int) -> bool:
    """Bloque un utilisateur. Retourne True."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i]["status"] = "blocked"
            _write_subs(subs)
            return True
    subs.append({
        "user_id":       user_id,
        "username":      "",
        "name":          "Inconnu",
        "status":        "blocked",
        "subscribed_at": datetime.now().strftime(TS_FMT),
        "expires_at":    "",
        "invite_link":   "",
        "orders_count":  0,
    })
    _write_subs(subs)
    return True


def extend_subscription(user_id: int, days: int = 30) -> bool:
    """Prolonge l'abonnement de `days` jours depuis l'expiration actuelle (ou maintenant si expiré)."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            expires_at = s.get("expires_at", "")
            try:
                base = datetime.strptime(expires_at, TS_FMT)
                base = max(base, datetime.now())
            except (ValueError, TypeError):
                base = datetime.now()
            subs[i]["expires_at"] = (base + timedelta(days=days)).strftime(TS_FMT)
            subs[i]["status"]     = "active"
            _write_subs(subs)
            return True
    return False


def increment_orders(user_id: int) -> None:
    """Incrémente le compteur de commandes d'un abonné."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i]["orders_count"] = subs[i].get("orders_count", 0) + 1
            _write_subs(subs)
            return
