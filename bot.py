"""
╔══════════════════════════════════════════════════════════╗
║        GRABDISCOUNT BOT — v5                            ║
╚══════════════════════════════════════════════════════════╝
Flux client :
  1. /start  → "Envoie ton screenshot Grab"
  2. Photo   → "Quelle adresse de livraison ?"
  3. Adresse → confirmé, admin notifié + compte Grab assigné

Flux admin :
  ✅ En cours → client averti, boutons : Suivi | Livré
  📍 Lien suivi → colle l'URL Grab tracking
  ✅ Livré → client averti "bon appétit"
  ❌ Annuler → client averti + compte libéré

LANCEMENT : python3 bot.py
"""

from __future__ import annotations
import os, re, json, logging, random, string, time, fcntl
from datetime import datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)
import subscribers

WEBAPP_URL = "https://amorguess.github.io/grabdiscount-bot/webapp/"

# ──────────────────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────────────────

BOT_TOKEN     = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
CHANNEL_ID    = int(os.environ.get("CHANNEL_ID", -1003910907077))

# ──────────────────────────────────────────────────────────
#  ÉTATS
# ──────────────────────────────────────────────────────────

ATTENTE_COMMANDE, ATTENTE_ADRESSE = range(2)

# ──────────────────────────────────────────────────────────
#  LOGS
# ──────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
#  STATUT ADMIN
# ──────────────────────────────────────────────────────────

DATA_DIR      = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE   = os.path.join(DATA_DIR, "status.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")

_last_forward: dict[int, float] = {}
FORWARD_COOLDOWN = 30

_reply_map:     dict[int, int]  = {}   # admin_msg_id → client_chat_id
_pending_suivi: dict[int, dict] = {}   # ADMIN_CHAT_ID → {order_id, client_id}

_prospects_notified: set[int] = set()


def _has_access(user_id: int) -> bool:
    """Vérifie si un utilisateur peut commander (abonnement actif ou admin)."""
    if user_id == ADMIN_CHAT_ID:
        return True
    return subscribers.is_active(user_id)


async def _refuser_acces(update: Update, context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
    user = update.effective_user
    keyboard = [[InlineKeyboardButton(
        "📩 S'abonner — Contacter l'admin",
        url=f"tg://user?id={ADMIN_CHAT_ID}",
    )]]
    await update.message.reply_text(
        "🛵 *Bienvenue sur GrabDiscount !*\n\n"
        "Économisez jusqu'à *50%* sur toutes vos commandes Grab Bangkok.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 Abonnement mensuel : *20€/mois*\n"
        "✅ Commandes illimitées\n"
        "✅ Service en français 🇫🇷\n"
        "✅ Réponse en moins de 5 minutes\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Pour s'abonner :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    if context and user.id not in _prospects_notified:
        _prospects_notified.add(user.id)
        username = f"@{user.username}" if user.username else "_(aucun)_"
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    "🆕 *NOUVEAU PROSPECT*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *{user.full_name}*  {username}\n"
                    f"🆔 ID : `{user.id}`\n\n"
                    f"▸ Pour activer : `/invite {user.id} {user.first_name or 'Prénom'}`"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

def get_statut() -> bool:
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f).get("dispo", True)
    except (FileNotFoundError, json.JSONDecodeError):
        return True

def set_statut(dispo: bool) -> None:
    with open(STATUS_FILE, "w") as f:
        json.dump({"dispo": dispo}, f)

# ──────────────────────────────────────────────────────────
#  UTILITAIRES
# ──────────────────────────────────────────────────────────

def gen_order_id() -> str:
    return "CMD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))

def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y à %H:%M")

TS_FMT = "%Y-%m-%dT%H:%M:%S"
def now_ts() -> str:
    return datetime.now().strftime(TS_FMT)

def is_url(text: str) -> bool:
    return bool(re.match(r"https?://\S+", text.strip()))

ORDERS_FILE   = os.path.join(DATA_DIR, "orders.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")

ORDER_ID_RE = re.compile(r'^CMD-[A-Z0-9]{5}$')

_io_lock = __import__("threading").Lock()
_orders_cache: dict = {}

def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with _io_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, path)

# ──────────────────────────────────────────────────────────
#  COMPTES GRAB — auto-assignation
# ──────────────────────────────────────────────────────────

def _pick_account(order_id: str) -> dict | None:
    """Prend le premier compte grab_ready/full disponible et le marque 'en_cours'."""
    accounts = _read_json(ACCOUNTS_FILE, [])
    for i, acc in enumerate(accounts):
        if acc.get("status") in ("grab_ready", "full") and acc.get("phone"):
            accounts[i]["status"]   = "en_cours"
            accounts[i]["order_id"] = order_id
            try:
                _write_json(ACCOUNTS_FILE, accounts)
            except Exception as e:
                logger.error(f"_pick_account write: {e}")
            return acc
    return None

def _release_account(order_id: str, new_status: str = "used") -> None:
    """Marque le compte lié à order_id avec new_status."""
    accounts = _read_json(ACCOUNTS_FILE, [])
    changed = False
    for i, acc in enumerate(accounts):
        if acc.get("order_id") == order_id and acc.get("status") == "en_cours":
            accounts[i]["status"]   = new_status
            accounts[i]["order_id"] = None
            changed = True
            break
    if changed:
        try:
            _write_json(ACCOUNTS_FILE, accounts)
        except Exception as e:
            logger.error(f"_release_account write: {e}")

def _fmt_account(acc: dict) -> str:
    """Formate les infos du compte pour l'admin (Markdown)."""
    email  = acc.get("email", "?")
    name   = acc.get("grab_name") or (
        (acc.get("prenom", "") + " " + acc.get("nom", "")).strip()
    ) or "?"
    phone  = acc.get("phone", "?")
    addr   = acc.get("grab_bangkok_addr") or acc.get("bangkok_addr", "?")
    return (
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *Compte Grab assigné :*\n"
        f"📧 Email   : `{email}`\n"
        f"👤 Nom     : `{name}`\n"
        f"📞 Tél     : `{phone}`\n"
        f"📍 Adresse : `{addr}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )

# ──────────────────────────────────────────────────────────
#  COMMANDES
# ──────────────────────────────────────────────────────────

def sauvegarder_commande(order_id: str, chat_id: int, data: dict, statut: str = "en_attente") -> None:
    entry = {
        "chat_id":       chat_id,
        "nom":           data.get("nom", "Client"),
        "adresse":       data.get("adresse", "?"),
        "photo_file_id": data.get("photo_file_id", ""),
        "heure":         now_str(),
        "ts":            now_ts(),
        "statut":        statut,
        "account_email": data.get("account_email", ""),
    }
    _orders_cache[order_id] = entry
    try:
        orders = _read_json(ORDERS_FILE, {})
        orders.update(_orders_cache)
        _write_json(ORDERS_FILE, orders)
    except Exception as e:
        logger.error(f"sauvegarder_commande: {e}")

def mettre_a_jour_statut(order_id: str, statut: str) -> None:
    if order_id in _orders_cache:
        _orders_cache[order_id]["statut"] = statut
    try:
        orders = _read_json(ORDERS_FILE, {})
        if order_id in orders:
            orders[order_id]["statut"] = statut
        _write_json(ORDERS_FILE, orders)
    except Exception as e:
        logger.error(f"mettre_a_jour_statut: {e}")

def charger_commande(order_id: str):
    if order_id in _orders_cache:
        return _orders_cache[order_id]
    orders = _read_json(ORDERS_FILE, {})
    entry = orders.get(order_id)
    if entry:
        _orders_cache[order_id] = entry
    return entry

def log_message(user_id: int, name: str, username: str,
                text: str, direction: str = "client") -> None:
    try:
        msgs = _read_json(MESSAGES_FILE, {})
        uid = str(user_id)
        if uid not in msgs:
            msgs[uid] = {"name": name, "username": username, "messages": [], "unread": 0}
        msgs[uid]["name"]     = name
        msgs[uid]["username"] = username
        msgs[uid]["messages"].append({
            "text":  text,
            "ts":    now_ts(),
            "heure": now_str(),
            "from":  direction,
            "read":  direction == "admin",
        })
        if direction == "client":
            msgs[uid]["unread"] = msgs[uid].get("unread", 0) + 1
        msgs[uid]["messages"] = msgs[uid]["messages"][-100:]
        _write_json(MESSAGES_FILE, msgs)
    except Exception as e:
        logger.error(f"log_message: {e}")

def _precharger_cache() -> None:
    data = _read_json(ORDERS_FILE, {})
    _orders_cache.update(data)
    logger.info(f"Cache orders chargé : {len(_orders_cache)} commandes")

# ──────────────────────────────────────────────────────────
#  ÉTAPE 1 — ACCUEIL
# ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _has_access(update.effective_user.id):
        await _refuser_acces(update, context)
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["order_id"] = gen_order_id()

    keyboard = [[
        InlineKeyboardButton("🛒  Ouvrir Grab", web_app=WebAppInfo(url=WEBAPP_URL))
    ]]

    await update.message.reply_text(
        "🛵 *GrabDiscount* — Livraison à Bangkok\n\n"
        "Comment commander :\n"
        "1️⃣ Ouvre Grab et choisis ton restaurant\n"
        "2️⃣ Prends un *screenshot de ton panier*\n"
        "3️⃣ Envoie-le ici avec ton adresse\n"
        "4️⃣ On passe la commande pour toi 🍽️\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📸 *Envoie ton screenshot de panier Grab :*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ATTENTE_COMMANDE

# ──────────────────────────────────────────────────────────
#  ÉTAPE 2 — RÉCEPTION SCREENSHOT
# ──────────────────────────────────────────────────────────

async def recevoir_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data["photo_file_id"] = update.message.photo[-1].file_id

    await update.message.reply_text(
        "📸 *Screenshot reçu !*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📍 *Quelle est ton adresse de livraison ?*\n\n"
        "_Exemple : 42 Sukhumvit Soi 11, Bangkok_",
        parse_mode="Markdown",
    )
    return ATTENTE_ADRESSE

# ──────────────────────────────────────────────────────────
#  ÉTAPE 3 — ADRESSE & CONFIRMATION
# ──────────────────────────────────────────────────────────

async def recevoir_adresse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    adresse = update.message.text.strip()
    if len(adresse) < 5:
        await update.message.reply_text("⚠️ Adresse trop courte. Précise bien ton adresse.")
        return ATTENTE_ADRESSE

    user     = update.effective_user
    order_id = context.user_data.get("order_id", gen_order_id())
    photo_id = context.user_data.get("photo_file_id", "")

    # Assigne un compte Grab disponible
    acc = _pick_account(order_id)

    # Incrémente le compteur de commandes de l'abonné
    subscribers.increment_orders(user.id)

    # Sauvegarde la commande
    sauvegarder_commande(order_id, user.id, {
        "nom":           user.full_name,
        "adresse":       adresse,
        "photo_file_id": photo_id,
        "account_email": acc.get("email", "") if acc else "",
    }, statut="en_attente")

    # Confirmation au client
    await update.message.reply_text(
        "✅ *Commande reçue !*\n\n"
        f"🆔 Référence : `{order_id}`\n"
        f"📍 Adresse   : {adresse}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ On traite ta commande — tu seras notifié dès qu'elle est passée.\n\n"
        "_Pour toute question : /tchat_",
        parse_mode="Markdown",
    )

    # Notification admin
    username = f"@{user.username}" if user.username else "_(aucun)_"
    account_block = _fmt_account(acc) if acc else (
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Aucun compte Grab disponible !*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    caption = (
        "🆕 *NOUVELLE COMMANDE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Réf    : `{order_id}`\n"
        f"⏰ Heure  : {now_str()}\n\n"
        f"👤 *{user.full_name}*  {username}\n"
        f"🆔 ID     : `{user.id}`\n"
        f"📍 Adresse : {adresse}\n\n"
        f"{account_block}\n\n"
        "👇 _Réponds à ce message pour écrire au client_"
    )

    _kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ En cours", callback_data=f"ao_enc_{order_id}_{user.id}"),
        InlineKeyboardButton("❌ Annuler",  callback_data=f"ao_ann_{order_id}_{user.id}"),
    ]])

    try:
        sent = await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=_kb,
        )
        _reply_map[sent.message_id] = user.id
    except Exception as e:
        logger.error(f"Notif admin: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# ──────────────────────────────────────────────────────────
#  ANNULATION
# ──────────────────────────────────────────────────────────

async def _notifier_annulation(context, user) -> None:
    try:
        username = f"@{user.username}" if user.username else "_(aucun)_"
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                "🚫 *COMMANDE ANNULÉE*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *{user.full_name}*  {username}\n"
                f"🆔 ID : `{user.id}`\n"
                f"⏰ {now_str()}"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

async def annuler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    order_id = context.user_data.get("order_id")
    if order_id:
        _release_account(order_id, new_status="grab_ready")
    await update.message.reply_text(
        "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
        parse_mode="Markdown",
    )
    await _notifier_annulation(context, update.effective_user)
    context.user_data.clear()
    return ConversationHandler.END

# ──────────────────────────────────────────────────────────
#  ADMIN — BOUTONS INLINE COMMANDES
# ──────────────────────────────────────────────────────────

async def admin_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.answer("⛔ Réservé à l'admin")
        return
    await query.answer()

    # Format : "ao_<action>_<order_id>_<client_id>"
    parts = query.data.split("_", 3)
    if len(parts) < 4:
        return
    action    = parts[1]
    order_id  = parts[2]
    client_id = int(parts[3])

    if action == "enc":
        mettre_a_jour_statut(order_id, "en_cours")
        try:
            await context.bot.send_message(
                chat_id=client_id,
                text=(
                    "👨‍🍳 *Votre commande est en cours de préparation !*\n\n"
                    f"🆔 Réf : `{order_id}`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🕐 Vous recevrez votre lien de suivi dans quelques minutes.\n\n"
                    "_Bon appétit bientôt !_ 🍽️"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"ao_enc: {e}")
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📍 Lien suivi", callback_data=f"ao_svi_{order_id}_{client_id}"),
                    InlineKeyboardButton("✅ Livré",       callback_data=f"ao_liv_{order_id}_{client_id}"),
                ]])
            )
        except Exception:
            pass

    elif action == "ann":
        mettre_a_jour_statut(order_id, "annule")
        _release_account(order_id, new_status="grab_ready")
        try:
            await context.bot.send_message(
                chat_id=client_id,
                text=(
                    "❌ *Commande annulée*\n\n"
                    f"🆔 Réf : `{order_id}`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Votre commande n'a pas pu être traitée. Désolé.\n\n"
                    "_Pour toute question : /tchat_"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"ao_ann: {e}")
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annulée", callback_data="ao_noop"),
                ]])
            )
        except Exception:
            pass

    elif action == "svi":
        _pending_suivi[ADMIN_CHAT_ID] = {"order_id": order_id, "client_id": client_id}
        try:
            await query.message.reply_text(
                f"📍 Colle le lien de suivi Grab pour `{order_id}` :",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    elif action == "liv":
        mettre_a_jour_statut(order_id, "livre")
        _release_account(order_id, new_status="used")
        try:
            await context.bot.send_message(
                chat_id=client_id,
                text=(
                    "✅ *Commande livrée !*\n\n"
                    f"🆔 Réf : `{order_id}`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Merci d'avoir commandé via GrabDiscount ! 🙏\n\n"
                    "_Pour la prochaine fois : /start_ 🛵"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"ao_liv: {e}")
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Livré ✓", callback_data="ao_noop"),
                ]])
            )
        except Exception:
            pass

# ──────────────────────────────────────────────────────────
#  ADMIN — REPLY = RÉPONSE AU CLIENT
# ──────────────────────────────────────────────────────────

async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Réponse admin à un message forwardé → réponse directe au client.
    Aussi capte le lien de suivi quand _pending_suivi est actif.
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not update.message:
        return

    text = (update.message.text or "").strip()

    # URL de suivi en attente après clic bouton "📍 Lien suivi" ?
    pending = _pending_suivi.get(ADMIN_CHAT_ID)
    if pending and text and is_url(text):
        order_id  = pending["order_id"]
        client_id = pending["client_id"]
        del _pending_suivi[ADMIN_CHAT_ID]
        mettre_a_jour_statut(order_id, "en_cours")
        try:
            await context.bot.send_message(
                chat_id=client_id,
                text=(
                    "╔═══════════════════════════╗\n"
                    "║   📍  SUIVI DE COMMANDE   ║\n"
                    "╚═══════════════════════════╝\n\n"
                    "Votre commande est en route ! 🛵\n\n"
                    f"🆔 Référence : `{order_id}`\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "👇 *Suivez votre livraison ici :*\n"
                    f"{text}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⏰ Livraison estimée : 30-45 min\n\n"
                    "Bon appétit ! 🍽️"
                ),
                parse_mode="Markdown",
            )
            await update.message.reply_text(
                f"✅ Lien de suivi envoyé pour `{order_id}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Erreur envoi suivi : {e}")
        return

    if not update.message.reply_to_message:
        return

    original_mid = update.message.reply_to_message.message_id
    client_id = _reply_map.get(original_mid)
    if not client_id:
        return

    try:
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=client_id,
                photo=update.message.photo[-1].file_id,
                caption=(
                    "╔═══════════════════════════╗\n"
                    "║   💬  SERVICE CLIENT      ║\n"
                    "╚═══════════════════════════╝\n\n"
                    + (update.message.caption or "") +
                    "\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "_Pour répondre : /tchat votre message_"
                ),
                parse_mode="Markdown",
            )
        elif text:
            log_message(client_id, "Client", "", text, "admin")
            await context.bot.send_message(
                chat_id=client_id,
                text=(
                    "╔═══════════════════════════╗\n"
                    "║   💬  SERVICE CLIENT      ║\n"
                    "╚═══════════════════════════╝\n\n"
                    f"{text}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "_Pour répondre : /tchat votre message_"
                ),
                parse_mode="Markdown",
            )
        await update.message.reply_text(
            f"✅ Réponse envoyée à `{client_id}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur envoi : {e}")

# ──────────────────────────────────────────────────────────
#  COMMANDES ADMIN
# ──────────────────────────────────────────────────────────

async def cmd_dispo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    set_statut(True)
    await update.message.reply_text(
        "✅ *Vous êtes maintenant DISPONIBLE.*",
        parse_mode="Markdown",
    )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    set_statut(False)
    await update.message.reply_text(
        "⏸️ *Vous êtes maintenant en PAUSE.*",
        parse_mode="Markdown",
    )

async def cmd_statut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    dispo = get_statut()
    emoji = "✅" if dispo else "⏸️"
    etat  = "DISPONIBLE" if dispo else "EN PAUSE"
    await update.message.reply_text(
        f"{emoji} *Statut actuel : {etat}*\n\n"
        "▸ `/dispo` → passer en disponible\n"
        "▸ `/pause` → passer en pause",
        parse_mode="Markdown",
    )

async def cmd_commandes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    try:
        orders = _read_json(ORDERS_FILE, {})
    except Exception:
        await update.message.reply_text("Aucune commande enregistrée.")
        return

    now_dt = datetime.now()
    lignes = []
    for oid, cmd in orders.items():
        try:
            ts_str = cmd.get("ts") or cmd.get("heure", "")
            if "T" in ts_str:
                cmd_dt = datetime.strptime(ts_str, TS_FMT)
            else:
                for fmt in ("%d/%m/%Y à %H:%M", "%d/%m %H:%M"):
                    try:
                        cmd_dt = datetime.strptime(ts_str, fmt)
                        if cmd_dt.year == 1900:
                            cmd_dt = cmd_dt.replace(year=now_dt.year)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            if (now_dt - cmd_dt).total_seconds() > 86400:
                continue
        except Exception:
            continue

        statut_emoji = {
            "en_attente": "⏳",
            "en_cours":   "🛵",
            "livre":      "✅",
            "annule":     "❌",
        }.get(cmd.get("statut", ""), "❓")

        lignes.append(
            f"{statut_emoji} `{oid}` | *{cmd.get('nom','?')}* | "
            f"{cmd.get('adresse','?')[:30]} | {cmd.get('heure','?')}"
        )

    if not lignes:
        await update.message.reply_text("Aucune commande dans les dernières 24h.")
        return

    texte = "*Commandes des dernières 24h :*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lignes)
    await update.message.reply_text(texte, parse_mode="Markdown")


async def envoyer_suivi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin envoie le lien de suivi Grab au client.
    Usage : /suivi CMD-XXXXX https://...
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Commande réservée à l'admin.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/suivi CMD-XXXXX https://lien-grab.com/...`",
            parse_mode="Markdown",
        )
        return

    order_id   = args[0].upper()
    lien_suivi = args[1]

    if not ORDER_ID_RE.match(order_id):
        await update.message.reply_text(
            "❌ Format invalide. Exemple : `CMD-AB12C`", parse_mode="Markdown"
        )
        return

    commande = charger_commande(order_id)
    if not commande:
        await update.message.reply_text(
            f"❌ Commande `{order_id}` introuvable.", parse_mode="Markdown"
        )
        return

    try:
        await context.bot.send_message(
            chat_id=commande["chat_id"],
            text=(
                "╔═══════════════════════════╗\n"
                "║   📍  SUIVI DE COMMANDE   ║\n"
                "╚═══════════════════════════╝\n\n"
                "Votre commande est en route ! 🛵\n\n"
                f"🆔 Référence : `{order_id}`\n"
                f"📍 Adresse   : {commande.get('adresse', '?')}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👇 *Suivez votre livraison ici :*\n"
                f"{lien_suivi}\n\n"
                "⏰ Livraison estimée : 30-45 min\n\n"
                "Bon appétit ! 🍽️"
            ),
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            f"✅ *Suivi envoyé à {commande.get('nom','?')}* (`{order_id}`)",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur envoi : {e}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    orders = _read_json(ORDERS_FILE, {})
    accounts = _read_json(ACCOUNTS_FILE, [])

    orders_today = [o for o in orders.values() if (o.get("ts") or "")[:10] == today]
    pending = sum(1 for o in orders.values() if o.get("statut") == "en_attente")
    en_cours = sum(1 for o in orders.values() if o.get("statut") == "en_cours")
    dispo = sum(1 for a in accounts if a.get("status") in ("grab_ready", "full") and a.get("phone"))

    await update.message.reply_text(
        f"📊 *Stats du {today}*\n\n"
        f"🛵 Commandes aujourd'hui : *{len(orders_today)}*\n"
        f"⏳ En attente           : *{pending}*\n"
        f"🔄 En cours             : *{en_cours}*\n\n"
        f"📱 Comptes dispo        : *{dispo}*\n\n"
        "🔗 Dashboard → https://passfooddelivery.online",
        parse_mode="Markdown",
    )


async def cmd_tchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user  = update.effective_user
    texte = " ".join(context.args) if context.args else ""

    if not texte:
        await update.message.reply_text(
            "💬 *Contacter le service client*\n\n"
            "Tapez votre message après la commande :\n"
            "`/tchat Votre message ici`",
            parse_mode="Markdown",
        )
        return

    username = f"@{user.username}" if user.username else ""
    log_message(user.id, user.full_name, username, texte, "client")
    try:
        sent = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                "💬 *MESSAGE CLIENT*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *{user.full_name}*  {username or '_(aucun)_'}\n"
                f"🆔 ID : `{user.id}`\n\n"
                f"✉️ {texte}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "↩️ _Réponds à ce message pour répondre au client_"
            ),
            parse_mode="Markdown",
        )
        _reply_map[sent.message_id] = user.id
        await update.message.reply_text(
            "✅ *Message envoyé !* On vous répond rapidement. 🙏",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Erreur tchat : {e}")
        await update.message.reply_text("❌ Erreur lors de l'envoi, réessayez.")


async def cmd_rep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin répond à un client. Usage : /rep USER_ID message"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/rep USER_ID votre message`",
            parse_mode="Markdown",
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID client invalide.")
        return

    message = " ".join(args[1:])
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "╔═══════════════════════════╗\n"
                "║   💬  SERVICE CLIENT      ║\n"
                "╚═══════════════════════════╝\n\n"
                f"{message}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "_Pour répondre : /tchat votre message_"
            ),
            parse_mode="Markdown",
        )
        log_message(target_id, "Client", "", message, "admin")
        await update.message.reply_text(
            f"✅ *Réponse envoyée* à `{target_id}`", parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur envoi : {e}")


async def cmd_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ *Usage :*\n`/canal votre message`", parse_mode="Markdown")
        return
    msg = " ".join(context.args)
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=msg, parse_mode="Markdown")
        await update.message.reply_text("✅ Message envoyé dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    promo_text = (
        "🛵 *GrabDiscount — Offre du moment !*\n\n"
        "🎁 Commandezvia notre service et *économisez jusqu'à 50%* sur vos repas Grab !\n\n"
        "📲 Démarrez votre commande ici 👇\n"
        "→ @GrabDiscountBot\n\n"
        "🏙️ Service disponible à Bangkok\n"
        "⏱️ Réponse en moins de 5 minutes"
    )
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=promo_text, parse_mode="Markdown")
        await update.message.reply_text("✅ Offre promo envoyée dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_annonce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    annonce = (
        "🛵 *Bienvenue sur GrabDiscount !*\n\n"
        "Nous commandons sur Grab à votre place avec nos comptes premium "
        "et vous faisons profiter de *-50% sur tous vos repas*.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Comment ça marche ?*\n"
        "1️⃣ Vous choisissez votre restaurant sur Grab\n"
        "2️⃣ Vous envoyez le screenshot de votre panier\n"
        "3️⃣ On passe la commande pour vous\n"
        "4️⃣ Vous recevez votre repas 🍜\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📲 Pour commander : @GrabDiscountBot\n\n"
        "🇫🇷 Service en français · 🏙️ Bangkok\n"
        "📢 Activez les notifications pour nos offres !"
    )
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=annonce, parse_mode="Markdown")
        await update.message.reply_text("✅ Annonce envoyée dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


# ──────────────────────────────────────────────────────────
#  ADMIN — GESTION ABONNÉS
# ──────────────────────────────────────────────────────────

async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Crée un lien d'invitation canal unique et active l'abonnement.
    Usage : /invite USER_ID [Prénom]
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/invite USER_ID [Prénom]`",
            parse_mode="Markdown",
        )
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide.")
        return

    prenom = context.args[1] if len(context.args) > 1 else "toi"

    # Créer lien d'invitation unique (1 usage, 30 jours)
    expire_date = datetime.now() + timedelta(days=30)
    try:
        link_obj = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=expire_date,
        )
        invite_link = link_obj.invite_link
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur création lien canal : {e}")
        return

    # Récupérer le profil Telegram si possible
    try:
        chat = await context.bot.get_chat(user_id)
        name     = chat.full_name or prenom
        username = f"@{chat.username}" if chat.username else ""
    except Exception:
        name     = prenom
        username = ""

    subscribers.add_subscriber(user_id, name, username, invite_link, days=30)

    exp_str = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 *Bienvenue sur GrabDiscount, {prenom} !*\n\n"
                "Ton abonnement est activé pour *30 jours*.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👇 *Rejoins notre canal privé :*\n"
                f"{invite_link}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Une fois dans le canal, tape /start dans ce bot "
                "pour passer ta première commande ! 🛵\n\n"
                f"📅 Abonnement valable jusqu'au *{exp_str}*\n"
                "_-50% sur tous tes repas Grab Bangkok_ 🍜"
            ),
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            f"✅ *Abonné activé !*\n\n"
            f"👤 {name} `{user_id}`\n"
            f"📅 Expire le {exp_str}\n"
            f"🔗 {invite_link}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Abonné ajouté mais erreur envoi message : {e}"
        )


async def cmd_expire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Expire manuellement un abonné.
    Usage : /expire USER_ID
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/expire USER_ID`", parse_mode="Markdown"
        )
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide.")
        return

    found = subscribers.expire_subscriber(user_id)
    if not found:
        await update.message.reply_text(
            f"❌ Abonné actif `{user_id}` introuvable.", parse_mode="Markdown"
        )
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "⏰ *Ton abonnement GrabDiscount a expiré.*\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Pour continuer à profiter des *-50% sur Grab Bangkok*, "
                "renouvelle ton abonnement.\n\n"
                "💳 *20€/mois* — commandes illimitées\n\n"
                "👇 Contacte-nous pour renouveler :"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Renouveler", url=f"tg://user?id={ADMIN_CHAT_ID}")
            ]]),
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Abonné `{user_id}` expiré. Message envoyé.", parse_mode="Markdown"
    )


async def cmd_abonnes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Liste tous les abonnés actifs."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    all_subs  = subscribers.get_all()
    actifs    = [s for s in all_subs if s.get("status") == "active"]
    expiring  = {s["user_id"] for s in subscribers.get_expiring_soon(3)}
    now_dt    = datetime.now()

    if not actifs:
        await update.message.reply_text("Aucun abonné actif.")
        return

    lines = [f"*Abonnés actifs — {len(actifs)} total :*\n━━━━━━━━━━━━━━━━━━━━━━━━"]
    for s in actifs:
        uid        = s.get("user_id")
        expires_at = s.get("expires_at", "")
        try:
            exp_dt    = datetime.strptime(expires_at, TS_FMT)
            exp_str   = exp_dt.strftime("%d/%m/%Y")
            days_left = (exp_dt - now_dt).days
        except Exception:
            exp_str   = expires_at
            days_left = 999

        warn     = " ⚠️" if uid in expiring else ""
        username = s.get("username") or f"ID:{uid}"
        lines.append(
            f"👤 *{s.get('name','?')}* {username}\n"
            f"   📅 Expire le {exp_str} ({days_left}j){warn}\n"
            f"   🛵 {s.get('orders_count', 0)} commande(s)"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bloque un utilisateur.
    Usage : /block USER_ID
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/block USER_ID`", parse_mode="Markdown"
        )
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID invalide.")
        return

    subscribers.block_subscriber(user_id)
    await update.message.reply_text(
        f"🚫 Utilisateur `{user_id}` bloqué.", parse_mode="Markdown"
    )


async def cmd_renouveler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prolonge l'abonnement de 30 jours.
    Usage : /renouveler USER_ID [jours]
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/renouveler USER_ID [jours]`", parse_mode="Markdown"
        )
        return
    try:
        user_id = int(context.args[0])
        days    = int(context.args[1]) if len(context.args) > 1 else 30
    except ValueError:
        await update.message.reply_text("❌ Paramètres invalides.")
        return

    found = subscribers.extend_subscription(user_id, days=days)
    if not found:
        await update.message.reply_text(
            f"❌ Abonné `{user_id}` introuvable.", parse_mode="Markdown"
        )
        return

    sub     = subscribers.get_subscriber(user_id)
    exp_str = sub.get("expires_at", "?")[:10] if sub else "?"
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 *Ton abonnement GrabDiscount a été renouvelé !*\n\n"
                f"📅 Nouveau terme : *{exp_str}*\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Tape /start pour passer ta prochaine commande. 🛵"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Abonnement `{user_id}` prolongé de {days} jours. Nouveau terme : {exp_str}",
        parse_mode="Markdown",
    )


async def aide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "╔═══════════════════════════╗\n"
        "║   ℹ️  AIDE                ║\n"
        "╚═══════════════════════════╝\n\n"
        "*Comment commander ?*\n\n"
        "1️⃣ /start — Lancer une commande\n"
        "2️⃣ Envoyer un screenshot de ton panier Grab\n"
        "3️⃣ Indiquer ton adresse de livraison\n"
        "4️⃣ On traite ta commande 🛵\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "❌ /annuler — Annuler la commande\n"
        "💬 /tchat — Contacter le service client",
        parse_mode="Markdown",
    )

# ──────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ATTENTE_COMMANDE: [
                MessageHandler(filters.PHOTO, recevoir_image),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    lambda u, c: u.message.reply_text(
                        "📸 *Envoie un screenshot de ton panier Grab.*\n\n"
                        "_Ouvre Grab, mets tes articles dans le panier, puis prends une capture d'écran._",
                        parse_mode="Markdown"
                    )
                ),
            ],
            ATTENTE_ADRESSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_adresse),
                MessageHandler(
                    filters.PHOTO,
                    lambda u, c: u.message.reply_text(
                        "📍 *Envoie ton adresse de livraison en texte.*\n\n"
                        "_Exemple : 42 Sukhumvit Soi 11, Bangkok_",
                        parse_mode="Markdown"
                    )
                ),
            ],
        },
        fallbacks=[
            CommandHandler("annuler", annuler),
            CommandHandler("start",   start),
        ],
        allow_reentry=True,
        conversation_timeout=3600,
    )

    # Handler global — messages hors conversation
    async def hors_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        user  = update.effective_user
        texte = (update.message.text or "").strip()

        if user.id == ADMIN_CHAT_ID:
            return

        if not _has_access(user.id):
            await _refuser_acces(update, context)
            return

        username = f"@{user.username}" if user.username else ""

        if texte:
            log_message(user.id, user.full_name, username, texte, "client")
            now_t = time.time()
            last  = _last_forward.get(user.id, 0)
            if now_t - last >= FORWARD_COOLDOWN:
                _last_forward[user.id] = now_t
                try:
                    sent_fwd = await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=(
                            "💬 *MESSAGE CLIENT*\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"👤 *{user.full_name}*  {username or '_(aucun)_'}\n"
                            f"🆔 ID : `{user.id}`\n\n"
                            f"✉️ {texte}\n\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "↩️ _Réponds à ce message pour répondre au client_"
                        ),
                        parse_mode="Markdown",
                    )
                    _reply_map[sent_fwd.message_id] = user.id
                except Exception as e:
                    logger.error(f"Forward hors_session : {e}")
            await update.message.reply_text(
                "✅ Message reçu — on vous répond rapidement 🙏",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "👋 Bonjour ! Tapez /start pour passer une commande.",
                parse_mode="Markdown",
            )

    _precharger_cache()

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(admin_order_callback, pattern=r"^ao_"))
    app.add_handler(CommandHandler("aide",      aide))
    app.add_handler(CommandHandler("help",      aide))
    app.add_handler(CommandHandler("suivi",     envoyer_suivi))
    app.add_handler(CommandHandler("dispo",     cmd_dispo))
    app.add_handler(CommandHandler("pause",     cmd_pause))
    app.add_handler(CommandHandler("statut",    cmd_statut))
    app.add_handler(CommandHandler("commandes", cmd_commandes))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("tchat",      cmd_tchat))
    app.add_handler(CommandHandler("rep",        cmd_rep))
    app.add_handler(CommandHandler("canal",      cmd_canal))
    app.add_handler(CommandHandler("promo",      cmd_promo))
    app.add_handler(CommandHandler("annonce",    cmd_annonce))
    app.add_handler(CommandHandler("invite",     cmd_invite))
    app.add_handler(CommandHandler("expire",     cmd_expire))
    app.add_handler(CommandHandler("abonnes",    cmd_abonnes))
    app.add_handler(CommandHandler("block",      cmd_block))
    app.add_handler(CommandHandler("renouveler", cmd_renouveler))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO) & filters.User(user_id=ADMIN_CHAT_ID),
        admin_reply_handler,
    ))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, hors_session))

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅  GrabDiscount Bot v5 — démarré")
    print("⏹  Ctrl+C pour arrêter")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


if __name__ == "__main__":
    main()
