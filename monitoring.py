"""
monitoring.py — Alertes Telegram pour GrabDiscount
====================================================
Alertes :
  - Bot crash / restart
  - 0 emails générés (auto-gen)
  - Résumé quotidien à 8h (Bangkok, UTC+7)
"""
from __future__ import annotations
import os, json, threading, datetime
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_CHAT_ID", 0))
DATA_DIR  = Path(os.environ.get("DATA_DIR", Path(__file__).parent))

ACCOUNTS_F = DATA_DIR / "accounts.json"
ORDERS_F   = DATA_DIR / "orders.json"
SUBS_F     = DATA_DIR / "subscribers.json"

TS_FMT = "%Y-%m-%dT%H:%M:%S"

# ── Anti-spam : on ne répète pas la même alerte sous 10 min ──
_last_alert: dict[str, datetime.datetime] = {}
_COOLDOWN = datetime.timedelta(minutes=10)

# ── Core : envoi Telegram ────────────────────────────────
def _tg(text: str) -> bool:
    if not BOT_TOKEN or not ADMIN_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.json().get("ok", False)
    except Exception:
        return False


def _throttled(key: str) -> bool:
    """Retourne True si l'alerte est en cooldown (ne pas renvoyer)."""
    now = datetime.datetime.now()
    last = _last_alert.get(key)
    if last and (now - last) < _COOLDOWN:
        return True
    _last_alert[key] = now
    return False


# ── Alertes ───────────────────────────────────────────────

def alert_bot_crash(error: str, attempt: int = 1) -> None:
    """Appelé quand le subprocess bot.py crash."""
    if _throttled("bot_crash"):
        return
    _tg(
        f"🔴 *Bot crash* (tentative #{attempt})\n"
        f"`{error[:300]}`\n"
        f"↩️ Relance automatique dans 10s…"
    )


def alert_bot_restarted(attempt: int = 1) -> None:
    """Appelé quand bot.py redémarre avec succès après un crash."""
    if _throttled("bot_restart"):
        return
    _tg(f"✅ *Bot redémarré* (tentative #{attempt}) — tout est OK")


def alert_zero_emails(run_number: int = 0) -> None:
    """Appelé quand une génération auto produit 0 emails."""
    if _throttled("zero_emails"):
        return
    _tg(
        f"⚠️ *0 emails générés* (cycle #{run_number})\n"
        "Vérifie le cookie iCloud → `/employe` ou renouvelle depuis Chrome."
    )


def alert_email_gen_error(error: str) -> None:
    """Erreur inattendue lors de la génération d'emails."""
    if _throttled("email_error"):
        return
    _tg(f"❌ *Erreur génération emails*\n`{error[:300]}`")


# ── Résumé quotidien ──────────────────────────────────────

def _build_daily_summary() -> str:
    today = datetime.date.today().isoformat()

    # Comptes
    try:
        accounts = json.loads(ACCOUNTS_F.read_text(encoding="utf-8"))
        total_accounts = len(accounts)
        full_accounts  = sum(1 for a in accounts if a.get("phone"))
        new_today      = sum(1 for a in accounts if (a.get("ts") or a.get("created", ""))[:10] == today)
    except Exception:
        total_accounts = full_accounts = new_today = 0

    # Commandes
    try:
        orders = json.loads(ORDERS_F.read_text(encoding="utf-8"))
        orders_today = [o for o in orders.values() if (o.get("ts") or "")[:10] == today]
        revenue_today = sum(
            o.get("prix", 0) for o in orders_today
            if o.get("statut") not in ("annule", "en_attente_confirmation", "en_attente_paiement")
        )
        orders_pending = sum(1 for o in orders.values() if o.get("statut") in ("en_attente_paiement", "en_attente_confirmation"))
    except Exception:
        orders_today = []
        revenue_today = orders_pending = 0

    lines = [
        f"📊 *Résumé quotidien — {today}*",
        "",
        f"👤 Comptes : *{total_accounts}* ({full_accounts} complets, +{new_today} aujourd'hui)",
        f"🛵 Commandes aujourd'hui : *{len(orders_today)}* — {revenue_today:,.0f} ฿",
        f"⏳ En attente paiement : *{orders_pending}*",
        "",
        f"🔗 Dashboard : https://passfooddelivery.online",
    ]
    return "\n".join(lines)


def send_daily_summary() -> None:
    _tg(_build_daily_summary())


def _seconds_until_8am_bangkok() -> float:
    """Secondes restantes jusqu'au prochain 8h00 heure Bangkok (UTC+7)."""
    bangkok_tz = datetime.timezone(datetime.timedelta(hours=7))
    now_bkk = datetime.datetime.now(bangkok_tz)
    target = now_bkk.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_bkk >= target:
        target += datetime.timedelta(days=1)
    return (target - now_bkk).total_seconds()


def _daily_summary_loop() -> None:
    while True:
        delay = _seconds_until_8am_bangkok()
        threading.Event().wait(delay)
        try:
            send_daily_summary()
        except Exception:
            pass
        try:
            send_expiration_reminders()
        except Exception:
            pass
        threading.Event().wait(60)  # évite de déclencher 2x si on arrive pile à 8h00


# ── Rappels expiration ────────────────────────────────────

def _tg_to_user(user_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Envoie un message direct à un utilisateur via HTTP."""
    if not BOT_TOKEN:
        return False
    payload: dict = {"chat_id": user_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        return r.json().get("ok", False)
    except Exception:
        return False


def _read_subs() -> list:
    try:
        return json.loads(SUBS_F.read_text(encoding="utf-8"))
    except Exception:
        return []


def _get_expiring_soon(days: int = 3) -> list:
    now   = datetime.datetime.now()
    limit = now + datetime.timedelta(days=days)
    result = []
    for s in _read_subs():
        if s.get("status") != "active":
            continue
        expires_at = s.get("expires_at", "")
        if not expires_at:
            continue
        try:
            exp_dt = datetime.datetime.strptime(expires_at, TS_FMT)
            if now <= exp_dt <= limit:
                result.append(s)
        except ValueError:
            pass
    return result


def _get_expired_recently(hours: int = 25) -> list:
    """Abonnés dont l'abonnement a expiré dans les dernières `hours` heures."""
    now       = datetime.datetime.now()
    threshold = now - datetime.timedelta(hours=hours)
    result = []
    for s in _read_subs():
        if s.get("status") != "active":
            continue
        expires_at = s.get("expires_at", "")
        if not expires_at:
            continue
        try:
            exp_dt = datetime.datetime.strptime(expires_at, TS_FMT)
            if threshold <= exp_dt <= now:
                result.append(s)
        except ValueError:
            pass
    return result


def send_expiration_reminders() -> None:
    """Envoie les rappels d'expiration et notifie l'admin. Appelé dans le cron quotidien."""
    renew_markup = {
        "inline_keyboard": [[{
            "text": "🔄 Renouveler",
            "url":  f"tg://user?id={ADMIN_ID}",
        }]]
    }

    for s in _get_expiring_soon(days=3):
        user_id    = s.get("user_id")
        name       = s.get("name", "là")
        expires_at = s.get("expires_at", "")
        try:
            exp_dt    = datetime.datetime.strptime(expires_at, TS_FMT)
            exp_str   = exp_dt.strftime("%d/%m/%Y")
            days_left = (exp_dt - datetime.datetime.now()).days
        except Exception:
            exp_str   = expires_at
            days_left = "?"

        _tg_to_user(
            user_id,
            f"⏰ *Rappel — Ton abonnement expire dans {days_left} jour(s)*\n\n"
            f"📅 Date d'expiration : *{exp_str}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Pour renouveler ton accès GrabDiscount *20€/mois*, contacte-nous :",
            reply_markup=renew_markup,
        )
        _tg(
            f"⚠️ *Abonnement expire bientôt*\n"
            f"👤 {name} `{user_id}`\n"
            f"📅 Le {exp_str} ({days_left}j)\n"
            f"→ `/renouveler {user_id}`"
        )

    for s in _get_expired_recently():
        user_id = s.get("user_id")
        name    = s.get("name", "là")

        _tg_to_user(
            user_id,
            "⏰ *Ton abonnement GrabDiscount a expiré.*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Pour continuer à profiter des *-50% sur Grab Bangkok*, "
            "renouvelle ton abonnement.\n\n"
            "💳 *20€/mois* — commandes illimitées\n\n"
            "👇 Contacte-nous pour renouveler :",
            reply_markup=renew_markup,
        )
        _tg(
            f"🔴 *Abonnement expiré*\n"
            f"👤 {name} `{user_id}`\n"
            f"→ `/renouveler {user_id}`"
        )


def schedule_daily_summary() -> None:
    """Lance le thread du résumé quotidien. Appeler une seule fois au démarrage."""
    t = threading.Thread(target=_daily_summary_loop, daemon=True, name="monitoring-daily")
    t.start()
