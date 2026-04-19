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
    "plan": "starter",            // starter | pro
    "subscribed_at": "2026-04-19T20:00:00",
    "expires_at": "2026-05-19T20:00:00",
    "paused_until": null,         // ISO string si en pause
    "invite_link": "https://t.me/+xxxxx",
    "orders_count": 0,            // lifetime total
    "monthly_orders": 0,          // reset au 1er du mois
    "monthly_orders_month": "2026-04",
    "parrain_id": null,           // qui m'a parrainé
    "filleuls": [],               // qui j'ai parrainé
    "referral_credit_eur": 0,     // EUR crédités via parrainage (à déduire au prochain renouvellement)
    "had_referral_discount": false // filleul : -5€ déjà consommé sur 1er mois
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

# ── Config plans ──────────────────────────────────────────
PLAN_CAPS = {
    "starter": 20,   # 20 commandes/mois
    "pro":     -1,   # illimité
}
PLAN_PRICES = {
    "starter": 20,   # EUR
    "pro":     30,   # EUR
}
DEFAULT_PLAN = "starter"

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
                   invite_link: str = "", days: int = 30,
                   plan: str = DEFAULT_PLAN,
                   parrain_id: int | None = None) -> dict:
    """Ajoute ou réactive un abonné. Retourne l'entrée créée/mise à jour.

    Si parrain_id fourni et filleul n'avait jamais eu de remise, on flag
    had_referral_discount=True (admin facture -5€ sur le 1er mois) et on crédite
    le parrain de +5€ dans referral_credit_eur.
    """
    now     = datetime.now()
    expires = now + timedelta(days=days)
    subs    = _read_subs()
    plan    = plan if plan in PLAN_CAPS else DEFAULT_PLAN

    # Anti-abus : filleul_id != parrain_id et pas de circularité immédiate
    if parrain_id is not None and parrain_id == user_id:
        parrain_id = None

    found_idx = -1
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            found_idx = i
            break

    # Parrainage : applicable uniquement au tout 1er abonnement du filleul
    apply_referral = (parrain_id is not None and (
        found_idx == -1 or not subs[found_idx].get("had_referral_discount")
    ))

    if found_idx >= 0:
        subs[found_idx].update({
            "name":           name,
            "username":       username,
            "status":         "active",
            "plan":           plan,
            "subscribed_at":  now.strftime(TS_FMT),
            "expires_at":     expires.strftime(TS_FMT),
            "invite_link":    invite_link or subs[found_idx].get("invite_link", ""),
            "paused_until":   None,
        })
        if apply_referral:
            subs[found_idx]["parrain_id"] = parrain_id
            subs[found_idx]["had_referral_discount"] = True
        entry = subs[found_idx]
    else:
        entry = {
            "user_id":       user_id,
            "username":      username,
            "name":          name,
            "status":        "active",
            "plan":          plan,
            "subscribed_at": now.strftime(TS_FMT),
            "expires_at":    expires.strftime(TS_FMT),
            "paused_until":  None,
            "invite_link":   invite_link,
            "orders_count":  0,
            "monthly_orders": 0,
            "monthly_orders_month": now.strftime("%Y-%m"),
            "parrain_id":    parrain_id if apply_referral else None,
            "filleuls":      [],
            "referral_credit_eur": 0,
            "had_referral_discount": bool(apply_referral and parrain_id),
        }
        subs.append(entry)

    # Crédit parrain : +5€ + ajout du filleul dans sa liste
    if apply_referral and parrain_id is not None:
        for j, p in enumerate(subs):
            if p.get("user_id") == parrain_id:
                subs[j]["referral_credit_eur"] = p.get("referral_credit_eur", 0) + 5
                filleuls = p.get("filleuls") or []
                if user_id not in filleuls:
                    filleuls.append(user_id)
                subs[j]["filleuls"] = filleuls
                break

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
    """Incrémente le compteur de commandes (lifetime + mensuel)."""
    subs = _read_subs()
    now_month = datetime.now().strftime("%Y-%m")
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            # Reset compteur mensuel si on change de mois
            if s.get("monthly_orders_month") != now_month:
                subs[i]["monthly_orders"] = 0
                subs[i]["monthly_orders_month"] = now_month
            subs[i]["orders_count"]   = s.get("orders_count", 0) + 1
            subs[i]["monthly_orders"] = subs[i].get("monthly_orders", 0) + 1
            _write_subs(subs)
            return


# ── Plans & cap mensuel ───────────────────────────────────

def get_plan(user_id: int) -> str:
    """Retourne le plan de l'abonné (starter par défaut)."""
    s = get_subscriber(user_id)
    if not s:
        return DEFAULT_PLAN
    return s.get("plan") or DEFAULT_PLAN


def set_plan(user_id: int, plan: str) -> bool:
    """Change le plan d'un abonné. Retourne True si trouvé."""
    if plan not in PLAN_CAPS:
        return False
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i]["plan"] = plan
            _write_subs(subs)
            return True
    return False


def get_monthly_usage(user_id: int) -> tuple[int, int]:
    """Retourne (commandes ce mois, cap du plan). cap=-1 → illimité."""
    s = get_subscriber(user_id)
    if not s:
        return (0, PLAN_CAPS[DEFAULT_PLAN])
    plan = s.get("plan") or DEFAULT_PLAN
    cap = PLAN_CAPS.get(plan, PLAN_CAPS[DEFAULT_PLAN])
    now_month = datetime.now().strftime("%Y-%m")
    # Si le dernier mois enregistré != mois courant → compteur effectivement à 0
    if s.get("monthly_orders_month") != now_month:
        return (0, cap)
    return (s.get("monthly_orders", 0), cap)


def can_order(user_id: int) -> tuple[bool, str]:
    """Vérifie si l'abonné peut passer commande. Retourne (ok, raison)."""
    s = get_subscriber(user_id)
    if not s:
        return (False, "no_sub")
    if s.get("status") == "blocked":
        return (False, "blocked")
    # Pause
    paused_until = s.get("paused_until")
    if paused_until:
        try:
            if datetime.strptime(paused_until, TS_FMT) > datetime.now():
                return (False, "paused")
        except ValueError:
            pass
    # Expiration
    if s.get("status") != "active":
        return (False, "expired")
    expires_at = s.get("expires_at", "")
    if expires_at:
        try:
            if datetime.strptime(expires_at, TS_FMT) < datetime.now():
                return (False, "expired")
        except ValueError:
            pass
    # Cap mensuel
    used, cap = get_monthly_usage(user_id)
    if cap != -1 and used >= cap:
        return (False, "cap_reached")
    return (True, "ok")


# ── Pause / Resume ─────────────────────────────────────────

def pause_subscriber(user_id: int, days: int = 30) -> bool:
    """Met en pause + prolonge expires_at de la même durée pour pas 'voler' les jours."""
    subs = _read_subs()
    now  = datetime.now()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i]["paused_until"] = (now + timedelta(days=days)).strftime(TS_FMT)
            # Prolonge l'expiration d'autant
            expires_at = s.get("expires_at", "")
            try:
                base = datetime.strptime(expires_at, TS_FMT)
            except (ValueError, TypeError):
                base = now
            subs[i]["expires_at"] = (base + timedelta(days=days)).strftime(TS_FMT)
            _write_subs(subs)
            return True
    return False


def resume_subscriber(user_id: int) -> bool:
    """Sort un abonné de pause (sans annuler la prolongation déjà accordée)."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            subs[i]["paused_until"] = None
            _write_subs(subs)
            return True
    return False


# ── Parrainage ─────────────────────────────────────────────

def get_referral_credit(user_id: int) -> int:
    """Retourne le crédit parrainage EUR en attente."""
    s = get_subscriber(user_id)
    return int(s.get("referral_credit_eur", 0)) if s else 0


def consume_referral_credit(user_id: int, amount: int) -> int:
    """Consomme jusqu'à `amount` EUR de crédit parrainage. Retourne le montant effectivement consommé."""
    subs = _read_subs()
    for i, s in enumerate(subs):
        if s.get("user_id") == user_id:
            have = int(s.get("referral_credit_eur", 0))
            used = min(have, int(amount))
            subs[i]["referral_credit_eur"] = have - used
            _write_subs(subs)
            return used
    return 0


def get_filleuls(user_id: int) -> list[int]:
    """Retourne la liste des user_id filleuls du parrain."""
    s = get_subscriber(user_id)
    return list(s.get("filleuls") or []) if s else []
