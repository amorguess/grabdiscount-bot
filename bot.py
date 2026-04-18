"""
╔══════════════════════════════════════════════════════════╗
║        GRABDISCOUNT BOT — v4                            ║
╚══════════════════════════════════════════════════════════╝
LANCEMENT : python3 bot.py
"""

from __future__ import annotations
import os, re, json, logging, random, string, time, fcntl
from datetime import datetime
from pathlib import Path

# Charge .env si présent (local / Raspberry Pi)
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

WEBAPP_URL = "https://amorguess.github.io/grabdiscount-bot/webapp/"

# ──────────────────────────────────────────────────────────
#  CONFIG  (toujours depuis l'env — jamais en dur)
# ──────────────────────────────────────────────────────────

BOT_TOKEN     = os.environ["BOT_TOKEN"]                        # obligatoire
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])               # obligatoire
CHANNEL_ID    = int(os.environ.get("CHANNEL_ID", -1003910907077))

# (panier minimum, prix client, lien Wise)
BUDGETS = [
    (1000, 500,  "https://wise.com/pay/r/Fk4y8LLVr8a-Z0M"),
    (2000, 1000, "https://wise.com/pay/r/Z_Lts2te9J1YA98"),
]

CUISINES = [
    ("🍔", "Fast Food"),
    ("🍜", "Thai Food"),
    ("🍕", "Pizza"),
    ("🛒", "Supermarché"),
    ("🍱", "Japonais / Sushi"),
    ("🥗", "Healthy / Salade"),
    ("🍗", "Poulet grillé"),
    ("🌮", "Mexicain"),
]

# ──────────────────────────────────────────────────────────
#  ÉTATS
# ──────────────────────────────────────────────────────────

(CHOIX_BUDGET, CHOIX_CUISINE, ATTENTE_COMMANDE,
 ATTENTE_ADRESSE, ATTENTE_CONFIRMATION, ATTENTE_PAIEMENT) = range(6)

# ──────────────────────────────────────────────────────────
#  LOGS
# ──────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
#  STATUT ADMIN
# ──────────────────────────────────────────────────────────

DATA_DIR     = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE  = os.path.join(DATA_DIR, "status.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")

# ── Rate limiting : max 1 transfer admin toutes les 30s par user ──
_last_forward: dict[int, float] = {}
FORWARD_COOLDOWN = 30   # secondes

def get_statut() -> bool:
    """Retourne True si l'admin est disponible, False sinon."""
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f).get("dispo", True)
    except (FileNotFoundError, json.JSONDecodeError):
        return True

def set_statut(dispo: bool) -> None:
    with open(STATUS_FILE, "w") as f:
        json.dump({"dispo": dispo}, f)

def msg_indispo(lang: str) -> str:
    """Message d'attente selon la langue du client."""
    if lang and lang.startswith("fr"):
        return (
            "🍳 Notre équipe va prendre en charge votre commande sous peu.\n"
            "Merci de patienter, nous revenons vers vous très rapidement ! 🙏"
        )
    return (
        "🍳 Our team will handle your order shortly.\n"
        "Thank you for your patience, we'll be right with you! 🙏"
    )

# ──────────────────────────────────────────────────────────
#  UTILITAIRES
# ──────────────────────────────────────────────────────────

def gen_order_id() -> str:
    return "CMD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))

# Format d'affichage (pour les clients)
def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y à %H:%M")

# Format ISO interne — parseable sans ambiguïté
TS_FMT = "%Y-%m-%dT%H:%M:%S"
def now_ts() -> str:
    return datetime.now().strftime(TS_FMT)

def is_url(text: str) -> bool:
    return bool(re.match(r"https?://\S+", text.strip()))

def get_wise_link(budget: int) -> str:
    return next((lien for m, _, lien in BUDGETS if m == budget), "")

def get_prix_client(budget: int) -> int:
    return next((prix for m, prix, _ in BUDGETS if m == budget), 0)

ORDERS_FILE   = os.path.join(DATA_DIR, "orders.json")
CUISINES_FILE = os.path.join(DATA_DIR, "cuisines.json")

# ── Verrou global pour toutes les I/O JSON (évite les race conditions) ──
_io_lock = __import__("threading").Lock()

# ── Cache mémoire (survive aux read/write, résiste aux erreurs disque) ──
_orders_cache: dict = {}

# ── Validation format order_id ─────────────────────────────
ORDER_ID_RE = re.compile(r'^CMD-[A-Z0-9]{5}$')

def _read_json(path: str, default):
    """Lecture JSON thread-safe."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _write_json(path: str, data) -> None:
    """Écriture atomique JSON thread-safe : tmp → rename."""
    tmp = path + ".tmp"
    with _io_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, path)   # atomique sur POSIX

def sauvegarder_commande(order_id: str, chat_id: int, data: dict, statut: str = "paiement_recu") -> None:
    """Sauvegarde la commande en mémoire + sur disque (atomique)."""
    entry = {
        "chat_id": chat_id,
        "nom":     data.get("nom", "Client"),
        "adresse": data.get("adresse", "?"),
        "cuisine": data.get("cuisine", "?"),
        "budget":  data.get("budget", 0),
        "prix":    data.get("prix", 0),
        "heure":   now_str(),
        "ts":      now_ts(),
        "statut":  statut,
    }
    _orders_cache[order_id] = entry
    try:
        orders = _read_json(ORDERS_FILE, {})
        orders.update(_orders_cache)
        _write_json(ORDERS_FILE, orders)
    except Exception as e:
        logger.error(f"Erreur sauvegarde commande : {e}")

def mettre_a_jour_statut(order_id: str, statut: str) -> None:
    """Met à jour le statut (cache + disque atomique)."""
    if order_id in _orders_cache:
        _orders_cache[order_id]["statut"] = statut
    try:
        orders = _read_json(ORDERS_FILE, {})
        if order_id in orders:
            orders[order_id]["statut"] = statut
        _write_json(ORDERS_FILE, orders)
    except Exception as e:
        logger.error(f"Erreur mise à jour statut : {e}")

def charger_commande(order_id: str):
    """Charge une commande : cache mémoire en priorité, puis disque."""
    if order_id in _orders_cache:
        return _orders_cache[order_id]
    orders = _read_json(ORDERS_FILE, {})
    entry = orders.get(order_id)
    if entry:
        _orders_cache[order_id] = entry
    return entry

def log_message(user_id: int, name: str, username: str,
                text: str, direction: str = "client") -> None:
    """Enregistre un message dans messages.json (atomique)."""
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
    """Charge orders.json en mémoire au démarrage."""
    data = _read_json(ORDERS_FILE, {})
    _orders_cache.update(data)
    logger.info(f"Cache orders chargé : {len(_orders_cache)} commandes")

# ──────────────────────────────────────────────────────────
#  ÉTAPE 1 — ACCUEIL
# ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["order_id"] = gen_order_id()

    keyboard = [[
        InlineKeyboardButton(
            "🛒  Ouvrir GrabDiscount",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]]

    await update.message.reply_text(
        "╔═══════════════════════════╗\n"
        "║   🍽️  GRABDISCOUNT        ║\n"
        "║   Livraison -50%          ║\n"
        "╚═══════════════════════════╝\n\n"
        "Commandez sur *Grab* à *moitié prix* grâce à notre service de conciergerie. 🚀\n\n"
        "▸ Vous choisissez votre panier\n"
        "▸ Vous payez 50% du montant\n"
        "▸ On commande pour vous ✅\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *Appuyez pour ouvrir l'app :*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOIX_BUDGET

# ──────────────────────────────────────────────────────────
#  ÉTAPE 2 — CHOIX CUISINE
# ──────────────────────────────────────────────────────────

async def choix_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    budget = int(query.data.split("_")[1])
    prix   = get_prix_client(budget)
    context.user_data["budget"] = budget
    context.user_data["prix"]   = prix

    buttons = []
    for i in range(0, len(CUISINES), 2):
        row = [
            InlineKeyboardButton(f"{e} {n}", callback_data=f"cuisine_{n}")
            for e, n in CUISINES[i:i+2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Annuler", callback_data="annuler")])

    await query.edit_message_text(
        f"✅ *Budget sélectionné*\n"
        f"┌ Panier Grab : *{budget:,}฿*\n".replace(",", " ") +
        f"└ Vous payez  : *{prix:,}฿* _(économie : {budget - prix:,}฿)_\n\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🍽️ *Quel type de cuisine ?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CHOIX_CUISINE

# ──────────────────────────────────────────────────────────
#  ÉTAPE 3 — ENVOI COMMANDE
# ──────────────────────────────────────────────────────────

async def choix_cuisine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    cuisine = query.data.replace("cuisine_", "")
    context.user_data["cuisine"] = cuisine
    budget  = context.user_data["budget"]

    await query.edit_message_text(
        f"✅ *Cuisine choisie :* {cuisine}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 *Envoyez votre commande :*\n\n"
        "Vous pouvez envoyer :\n"
        "   📸 Une *capture d'écran* de votre panier Grab\n"
        "   🔗 Un *lien* de commande Grab / Foodpanda\n\n"
        f"⚠️ Total panier minimum : *{budget:,}฿*".replace(",", " "),
        parse_mode="Markdown",
    )
    return ATTENTE_COMMANDE

# ──────────────────────────────────────────────────────────
#  ÉTAPE 4 — RÉCEPTION COMMANDE
# ──────────────────────────────────────────────────────────

async def recevoir_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data["type_commande"] = "image"
    context.user_data["photo_file_id"] = update.message.photo[-1].file_id

    # ── Alerte admin immédiate dès réception du screenshot commande ──
    username = f"@{user.username}" if user.username else "_(aucun)_"
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=update.message.photo[-1].file_id,
            caption=(
                "👁️ *NOUVEAU CLIENT — screenshot panier reçu*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *{user.full_name}*  {username}\n"
                f"🆔 ID : `{user.id}`\n\n"
                "_En attente adresse & confirmation_"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Notif admin recevoir_image: {e}")

    # Message d'attente si admin absent
    if not get_statut():
        lang = update.effective_user.language_code or ""
        await update.message.reply_text(msg_indispo(lang))

    await update.message.reply_text(
        "📸 *Screenshot reçu !*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📍 *Quelle est votre adresse de livraison ?*\n\n"
        "_Exemple : 42 Sukhumvit Soi 11, Bangkok_",
        parse_mode="Markdown",
    )
    return ATTENTE_ADRESSE


async def recevoir_lien(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texte = update.message.text.strip()
    if is_url(texte):
        context.user_data["type_commande"]  = "lien"
        context.user_data["lien_commande"]  = texte

        # ── Alerte admin immédiate dès réception du lien commande ──
        user = update.effective_user
        username = f"@{user.username}" if user.username else "_(aucun)_"
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    "🔗 *NOUVEAU CLIENT — lien commande reçu*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *{user.full_name}*  {username}\n"
                    f"🆔 ID : `{user.id}`\n\n"
                    f"🔗 {texte}\n\n"
                    "_En attente adresse & confirmation_"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Notif admin recevoir_lien: {e}")

        # Message d'attente si admin absent
        if not get_statut():
            lang = update.effective_user.language_code or ""
            await update.message.reply_text(msg_indispo(lang))

        await update.message.reply_text(
            "🔗 *Lien reçu !*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 *Quelle est votre adresse de livraison ?*\n\n"
            "_Exemple : 42 Sukhumvit Soi 11, Bangkok_",
            parse_mode="Markdown",
        )
        return ATTENTE_ADRESSE
    else:
        await update.message.reply_text(
            "⚠️ Format non reconnu.\n\n"
            "Envoyez :\n"
            "📸 Une *photo* (screenshot panier)\n"
            "🔗 Un *lien* (https://…)\n\n"
            "_/annuler pour recommencer_",
            parse_mode="Markdown",
        )
        return ATTENTE_COMMANDE

# ──────────────────────────────────────────────────────────
#  ÉTAPE 5 — ADRESSE
# ──────────────────────────────────────────────────────────

async def recevoir_adresse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    adresse = update.message.text.strip()
    if len(adresse) < 3:
        await update.message.reply_text("⚠️ Adresse trop courte. Merci de préciser.")
        return ATTENTE_ADRESSE

    context.user_data["adresse"] = adresse
    data   = context.user_data
    budget = data["budget"]
    prix   = data["prix"]

    keyboard = [[
        InlineKeyboardButton("✅ Confirmer", callback_data="confirmer"),
        InlineKeyboardButton("❌ Annuler",   callback_data="annuler"),
    ]]

    type_cmd = "📸 Capture d'écran" if data.get("type_commande") == "image" else "🔗 Lien"

    await update.message.reply_text(
        "╔═══════════════════════════╗\n"
        "║   📋  RÉCAPITULATIF       ║\n"
        "╚═══════════════════════════╝\n\n"
        f"🆔 Réf     : `{data['order_id']}`\n"
        f"🍽️ Cuisine : *{data['cuisine']}*\n"
        f"📦 Commande: {type_cmd}\n"
        f"📍 Adresse : {adresse}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 Panier Grab : *{budget:,}฿*\n".replace(",", " ") +
        f"💰 *Vous payez  : {prix:,}฿*\n".replace(",", " ") +
        f"💸 Économie    : {budget - prix:,}฿\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 *Tout est correct ?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ATTENTE_CONFIRMATION

# ──────────────────────────────────────────────────────────
#  ÉTAPE 6 — PAIEMENT
# ──────────────────────────────────────────────────────────

async def confirmer_commande(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data       = context.user_data
    budget     = data["budget"]
    prix       = data["prix"]
    wise_link  = get_wise_link(budget)

    await query.edit_message_text(
        "╔═══════════════════════════╗\n"
        "║   💳  PAIEMENT            ║\n"
        "╚═══════════════════════════╝\n\n"
        f"Montant à régler : *{prix:,}฿*\n\n".replace(",", " ") +
        "👇 *Payez via ce lien Wise :*\n"
        f"{wise_link}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📸 Une fois le paiement effectué,\n"
        "*envoyez le screenshot de votre reçu*\n"
        "pour valider votre commande. ✅",
        parse_mode="Markdown",
    )
    return ATTENTE_PAIEMENT


async def recevoir_preuve_paiement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Reçoit le screenshot du paiement, notifie l'admin."""
    user     = update.effective_user
    data     = context.user_data
    heure    = now_str()
    order_id = data.get("order_id", "?")

    # ── Sauvegarde commande pour le suivi ──────────────────
    data["nom"] = user.full_name
    sauvegarder_commande(order_id, user.id, data, statut="paiement_recu")

    # ── Confirmation client — paiement reçu, PAS encore confirmé ─
    await update.message.reply_text(
        "🎉 *Paiement reçu !*\n\n"
        f"Merci *{user.first_name}* 🙏\n\n"
        f"🆔 Référence : `{order_id}`\n"
        f"🍽️ Cuisine   : *{data['cuisine']}*\n"
        f"📍 Adresse   : {data['adresse']}\n"
        f"💰 Payé      : *{data['prix']:,}฿*\n".replace(",", " ") +
        f"⏰ Heure     : {heure}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ Votre commande est *en cours de validation*.\n"
        "✅ *Confirmée dans les 15 minutes maximum.*\n\n"
        "_Vous recevrez un message dès que la cuisine est lancée !_ 👨‍🍳",
        parse_mode="Markdown",
    )

    # ── Notification admin ─────────────────────────────────
    username = f"@{user.username}" if user.username else "_(aucun)_"
    type_cmd = "📸 Screenshot" if data.get("type_commande") == "image" else f"🔗 {data.get('lien_commande','?')}"

    caption = (
        "🆕 *NOUVELLE COMMANDE — PAIEMENT REÇU*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Réf    : `{order_id}`\n"
        f"⏰ Heure  : {heure}\n\n"
        f"👤 *{user.full_name}*\n"
        f"📲 {username}\n"
        f"🆔 ID     : `{user.id}`\n\n"
        f"🍽️ Cuisine : *{data['cuisine']}*\n"
        f"📦 Commande: {type_cmd}\n"
        f"📍 Adresse : {data['adresse']}\n\n"
        f"🛒 Panier  : *{data['budget']:,}฿*\n".replace(",", " ") +
        f"💰 Payé    : *{data['prix']:,}฿*\n".replace(",", " ") +
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ _Paiement confirmé — à traiter_\n\n"
        "📤 *Envoyer le suivi au client :*\n"
        f"`/suivi {order_id} https://lien-grab.com/...`"
    )

    # Envoie preuve de paiement à l'admin
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=update.message.photo[-1].file_id,
        caption=caption,
        parse_mode="Markdown",
    )

    # Si commande par screenshot, envoie aussi le screenshot de commande
    if data.get("type_commande") == "image":
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=data["photo_file_id"],
            caption=f"📸 *Screenshot commande* — {order_id}",
            parse_mode="Markdown",
        )

    return ConversationHandler.END

# ──────────────────────────────────────────────────────────
#  COMMANDE ADMIN — /suivi
# ──────────────────────────────────────────────────────────

async def cmd_dispo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin passe en mode disponible."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    set_statut(True)
    await update.message.reply_text(
        "✅ *Vous êtes maintenant DISPONIBLE.*\n"
        "Les clients peuvent passer des commandes normalement.",
        parse_mode="Markdown",
    )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin passe en mode absent."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    set_statut(False)
    await update.message.reply_text(
        "⏸️ *Vous êtes maintenant en PAUSE.*\n"
        "Les clients recevront un message d'attente automatique.",
        parse_mode="Markdown",
    )

async def cmd_statut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin vérifie son statut actuel."""
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
    """Admin liste les commandes des dernières 24h."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    try:
        with open(ORDERS_FILE, "r") as f:
            orders = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await update.message.reply_text("Aucune commande enregistrée.")
        return

    now_dt = datetime.now()
    lignes = []
    for oid, cmd in orders.items():
        try:
            # Essaie d'abord le champ ts (ISO), sinon le champ heure (ancien format)
            ts_str = cmd.get("ts") or cmd.get("heure", "")
            if "T" in ts_str:
                cmd_dt = datetime.strptime(ts_str, TS_FMT)
            else:
                # ancien format "d/m/Y à H:M" ou "d/m H:M"
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
            "paiement_recu":        "💰",
            "en_attente_paiement":  "⏳",
            "en_cours":             "🛵",
            "livre":                "✅",
            "annule":               "❌",
        }.get(cmd.get("statut", ""), "❓")

        lignes.append(
            f"{statut_emoji} `{oid}` | *{cmd.get('nom','?')}* | "
            f"{cmd.get('cuisine','?')} | {cmd.get('adresse','?')[:25]} | "
            f"{cmd.get('prix','?')}฿ | {cmd.get('heure','?')}"
        )

    if not lignes:
        await update.message.reply_text("Aucune commande dans les dernières 24h.")
        return

    texte = "*Commandes des dernières 24h :*\n━━━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lignes)
    await update.message.reply_text(texte, parse_mode="Markdown")


async def envoyer_suivi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin envoie le lien de suivi Grab au client.
    Usage : /suivi CMD-XXXXX https://grab.com/tracking/...
    """
    # Vérification : seul l'admin peut utiliser cette commande
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

    order_id    = args[0].upper()
    lien_suivi  = args[1]

    # Validation format CMD-XXXXX
    if not ORDER_ID_RE.match(order_id):
        await update.message.reply_text(
            "❌ Format invalide. Exemple : `CMD-AB12C`", parse_mode="Markdown"
        )
        return

    # Chargement de la commande
    commande = charger_commande(order_id)
    if not commande:
        await update.message.reply_text(
            f"❌ Commande `{order_id}` introuvable.",
            parse_mode="Markdown",
        )
        return

    client_chat_id = commande["chat_id"]
    nom_client     = commande.get("nom", "Client")

    # Envoi du suivi au client
    try:
        await context.bot.send_message(
            chat_id=client_chat_id,
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
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏰ Livraison estimée : 30-45 min\n\n"
                "Bon appétit ! 🍽️"
            ),
            parse_mode="Markdown",
        )
        # Confirmation à l'admin
        await update.message.reply_text(
            f"✅ *Suivi envoyé à {nom_client}* (`{order_id}`)",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Erreur envoi : {e}",
        )

# ──────────────────────────────────────────────────────────
#  ANNULATION
# ──────────────────────────────────────────────────────────

async def _notifier_annulation(context, user) -> None:
    """Notifie l'admin qu'un client a annulé."""
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

async def annuler_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
        parse_mode="Markdown",
    )
    await _notifier_annulation(context, update.effective_user)
    context.user_data.clear()
    return ConversationHandler.END


async def annuler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END

async def annuler_impossible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Appelé si le client tente d'annuler après l'envoi du lien de paiement."""
    await update.message.reply_text(
        "⚠️ *Annulation impossible.*\n\n"
        "Le lien de paiement a déjà été généré.\n\n"
        "Si vous avez un problème, contactez-nous :\n"
        "`/tchat votre message`",
        parse_mode="Markdown",
    )
    return ATTENTE_PAIEMENT  # reste dans l'état, attend le reçu

# ──────────────────────────────────────────────────────────
#  AIDE
# ──────────────────────────────────────────────────────────

async def aide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "╔═══════════════════════════╗\n"
        "║   ℹ️  AIDE                ║\n"
        "╚═══════════════════════════╝\n\n"
        "*Comment commander ?*\n\n"
        "1️⃣ /start — Lancer une commande\n"
        "2️⃣ Choisir votre budget\n"
        "3️⃣ Choisir votre cuisine\n"
        "4️⃣ Envoyer screenshot ou lien panier\n"
        "5️⃣ Indiquer votre adresse\n"
        "6️⃣ Confirmer et payer via Wise\n"
        "7️⃣ Envoyer le reçu de paiement\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "❌ /annuler — Annuler la commande\n"
        "💬 /tchat — Contacter le service client",
        parse_mode="Markdown",
    )

# ──────────────────────────────────────────────────────────
#  CHAT CLIENT ↔ ADMIN
# ──────────────────────────────────────────────────────────

async def cmd_tchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Client envoie un message libre à l'admin via /tchat."""
    user  = update.effective_user
    texte = " ".join(context.args) if context.args else ""

    if not texte:
        await update.message.reply_text(
            "💬 *Contacter le service client*\n\n"
            "Tapez votre message après la commande :\n"
            "`/tchat Votre message ici`\n\n"
            "_Exemple : /tchat Je voudrais modifier mon adresse_",
            parse_mode="Markdown",
        )
        return

    username = f"@{user.username}" if user.username else ""
    log_message(user.id, user.full_name, username, texte, "client")
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                "💬 *MESSAGE CLIENT*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *{user.full_name}*  {username or '_(aucun)_'}\n"
                f"🆔 ID : `{user.id}`\n\n"
                f"✉️ {texte}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 Répondre : `/rep {user.id} votre réponse`\n"
                "📊 _Ou depuis le dashboard_"
            ),
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            "✅ *Message envoyé au service client !*\n\n"
            "Nous vous répondrons dans les plus brefs délais. 🙏",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Erreur tchat : {e}")
        await update.message.reply_text("❌ Erreur lors de l'envoi, réessayez.")


async def cmd_rep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin répond à un client.
    Usage : /rep USER_ID message
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/rep USER_ID votre message`\n\n"
            "_Exemple : /rep 123456789 Votre commande est en route !_",
            parse_mode="Markdown",
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID client invalide (doit être un nombre).")
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
        # Log la réponse admin dans messages.json
        log_message(target_id, "Client", "", message, "admin")
        await update.message.reply_text(
            f"✅ *Réponse envoyée* à `{target_id}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur envoi : {e}")

# ──────────────────────────────────────────────────────────
#  COMMANDES CANAL
# ──────────────────────────────────────────────────────────

async def cmd_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin poste un message personnalisé dans le canal.
    Usage : /canal Votre message ici
    """
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Usage :*\n`/canal votre message`",
            parse_mode="Markdown",
        )
        return
    msg = " ".join(context.args)
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=msg,
            parse_mode="Markdown",
        )
        await update.message.reply_text("✅ Message envoyé dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin poste une offre promo dans le canal."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    promo_text = (
        "🛵 *GrabDiscount — Offre du moment !*\n\n"
        "🎁 Commandez via notre service et *économisez 50%* sur votre repas Grab !\n\n"
        "✅ 500 ฿ pour un panier de 1 000 ฿\n"
        "✅ 1 000 ฿ pour un panier de 2 000 ฿\n\n"
        "📲 Démarrez votre commande ici 👇\n"
        "→ @GrabDiscountBot\n\n"
        "🏙️ Service disponible partout en Thaïlande\n"
        "⏱️ Réponse en moins de 5 minutes"
    )
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=promo_text,
            parse_mode="Markdown",
        )
        await update.message.reply_text("✅ Offre promo envoyée dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_annonce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin poste le message de bienvenue/présentation dans le canal."""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    annonce = (
        "🛵 *Bienvenue sur GrabDiscount !*\n\n"
        "Nous commandons sur Grab à votre place avec nos comptes premium "
        "et vous faisons profiter de *-50% sur tous vos repas*.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Comment ça marche ?*\n"
        "1️⃣ Vous choisissez votre restaurant\n"
        "2️⃣ Vous payez 500 ฿ (au lieu de 1 000 ฿)\n"
        "3️⃣ On passe la commande pour vous sur Grab\n"
        "4️⃣ Vous recevez votre repas 🍜\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📲 Pour commander : @GrabDiscountBot\n\n"
        "🇫🇷 Service en français · 🏙️ Toute la Thaïlande\n"
        "📢 Activez les notifications pour nos offres !"
    )
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=annonce,
            parse_mode="Markdown",
        )
        await update.message.reply_text("✅ Annonce de bienvenue envoyée dans le canal !")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


# ──────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOIX_BUDGET: [
                CallbackQueryHandler(choix_budget,     pattern=r"^budget_"),
                CallbackQueryHandler(annuler_callback, pattern=r"^annuler$"),
            ],
            CHOIX_CUISINE: [
                CallbackQueryHandler(choix_cuisine,    pattern=r"^cuisine_"),
                CallbackQueryHandler(annuler_callback, pattern=r"^annuler$"),
            ],
            ATTENTE_COMMANDE: [
                MessageHandler(filters.PHOTO,                   recevoir_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_lien),
            ],
            ATTENTE_ADRESSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_adresse),
            ],
            ATTENTE_CONFIRMATION: [
                CallbackQueryHandler(confirmer_commande, pattern=r"^confirmer$"),
                CallbackQueryHandler(annuler_callback,   pattern=r"^annuler$"),
            ],
            ATTENTE_PAIEMENT: [
                MessageHandler(filters.PHOTO, recevoir_preuve_paiement),
                # /annuler bloqué une fois le lien de paiement envoyé
                CommandHandler("annuler", annuler_impossible),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text(
                    "📸 Merci d'envoyer le *screenshot de votre reçu Wise* pour valider.\n\n"
                    "_Si vous avez un problème : /tchat votre message_",
                    parse_mode="Markdown"
                )),
            ],
        },
        fallbacks=[
            CommandHandler("annuler", annuler),
            CommandHandler("start",   start),
        ],
        allow_reentry=True,
        conversation_timeout=3600,   # 1h → session zombie nettoyée auto
    )

    # Handler global — capte tout message texte hors conversation
    async def hors_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        user  = update.effective_user
        texte = (update.message.text or "").strip()

        # Ignore les messages de l'admin lui-même
        if user.id == ADMIN_CHAT_ID:
            return

        username = f"@{user.username}" if user.username else ""

        if texte:
            # ── Log pour le dashboard ──────────────────────
            log_message(user.id, user.full_name, username, texte, "client")

            # ── Rate limiting : max 1 notif admin / 30s ───
            now_t = time.time()
            last  = _last_forward.get(user.id, 0)
            if now_t - last >= FORWARD_COOLDOWN:
                _last_forward[user.id] = now_t
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=(
                            "💬 *MESSAGE CLIENT*\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"👤 *{user.full_name}*  {username or '_(aucun)_'}\n"
                            f"🆔 ID : `{user.id}`\n\n"
                            f"✉️ {texte}\n\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📤 Répondre : `/rep {user.id} votre réponse`\n"
                            "📊 _Ou depuis le dashboard_"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Forward hors_session : {e}")

            await update.message.reply_text(
                "✅ *Message transmis à notre équipe !*\n\n"
                "Nous vous répondrons très rapidement. 🙏\n\n"
                "_Pour passer une commande : /start_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "👋 Tapez /start pour passer une commande !",
                parse_mode="Markdown",
            )

    # ── Handler Mini App (web_app_data) ──────────────────────
    async def recevoir_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reçoit les données envoyées par tg.sendData() depuis la Mini App."""
        # Ne pas effacer user_data (Bug #5) — juste les clés webapp
        context.user_data.pop("webapp_order_id", None)
        context.user_data.pop("webapp_pending", None)

        data_str = update.message.web_app_data.data
        user = update.effective_user
        try:
            data = json.loads(data_str)
        except Exception:
            await update.message.reply_text("❌ Données invalides reçues.")
            return

        action = data.get("action")

        if action == "new_order":
            order_id = data.get("order_id", gen_order_id())
            budget   = data.get("budget", 0)
            prix     = data.get("prix", 0)
            cuisine  = data.get("cuisine", "?")
            address  = data.get("address", "?")
            link     = data.get("link", "")
            wise_link = get_wise_link(budget)

            # Sauvegarde en attente de confirmation (avant paiement)
            sauvegarder_commande(order_id, user.id, {
                "nom": user.full_name,
                "adresse": address,
                "cuisine": cuisine,
                "budget": budget,
                "prix": prix,
                "lien_commande": link,
            }, statut="en_attente_confirmation")

            # Mémorise dans user_data
            context.user_data["webapp_order_id"]  = order_id
            context.user_data["webapp_wise_link"]  = wise_link
            context.user_data["webapp_pending"]    = True   # avant paiement → annulation possible

            # ── Étape confirmation AVANT paiement (annulation encore possible) ──
            keyboard = [[
                InlineKeyboardButton("✅ Confirmer & Payer", callback_data=f"webapp_confirm_{order_id}"),
                InlineKeyboardButton("❌ Annuler",           callback_data=f"webapp_cancel_{order_id}"),
            ]]
            await update.message.reply_text(
                "╔═══════════════════════════╗\n"
                "║   📋  RÉCAPITULATIF       ║\n"
                "╚═══════════════════════════╝\n\n"
                f"🆔 Réf     : `{order_id}`\n"
                f"🍽️ Cuisine : *{cuisine}*\n"
                f"📍 Adresse : {address}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛒 Panier Grab : *{budget:,}฿*\n".replace(",", " ") +
                f"💰 *Vous payez  : {prix:,}฿*\n".replace(",", " ") +
                f"💸 Économie    : {budget - prix:,}฿\n".replace(",", " ") +
                "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "👇 *Tout est correct ? Vous pouvez encore annuler.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await update.message.reply_text("👋 Commande reçue !")

    # ── Callback confirmation/annulation webapp ──────────────
    async def webapp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data  # "webapp_confirm_CMD-XXXXX" ou "webapp_cancel_CMD-XXXXX"

        if data.startswith("webapp_confirm_"):
            order_id  = data.replace("webapp_confirm_", "")
            wise_link = context.user_data.get("webapp_wise_link", "")
            context.user_data["webapp_pending"] = False  # plus d'annulation possible

            # Mise à jour statut → en attente de paiement
            mettre_a_jour_statut(order_id, "en_attente_paiement")

            await query.edit_message_text(
                "╔═══════════════════════════╗\n"
                "║   💳  PAIEMENT            ║\n"
                "╚═══════════════════════════╝\n\n"
                f"🆔 Réf : `{order_id}`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👇 *Payez via ce lien Wise :*\n"
                f"{wise_link}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📸 Une fois payé, *envoyez le screenshot de votre reçu*\n"
                "pour valider votre commande. ✅\n\n"
                "⚠️ _Annulation impossible après cette étape_",
                parse_mode="Markdown",
            )

        elif data.startswith("webapp_cancel_"):
            order_id = data.replace("webapp_cancel_", "")
            # Annulation valide : encore avant paiement
            if context.user_data.get("webapp_pending", True):
                mettre_a_jour_statut(order_id, "annule")
                context.user_data.pop("webapp_order_id", None)
                context.user_data.pop("webapp_wise_link", None)
                context.user_data.pop("webapp_pending", None)
                await query.edit_message_text(
                    "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    "⚠️ *Annulation impossible.*\nLe paiement est déjà en cours.\n\n"
                    "Contactez-nous : `/tchat votre message`",
                    parse_mode="Markdown",
                )

    # ── Reçu Wise après flux Mini App ──────────────────────
    async def recevoir_paiement_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
        order_id = context.user_data.get("webapp_order_id")
        if not order_id:
            # Cherche dans le cache/fichier une commande récente (< 4h) en attente de paiement
            user_id  = update.effective_user.id
            now_dt   = datetime.now()
            # Parcours cache mémoire en priorité
            all_orders = {**_orders_cache}
            try:
                with open(ORDERS_FILE) as f:
                    all_orders.update(json.load(f))
            except Exception:
                pass
            for oid, cmd in all_orders.items():
                if cmd.get("chat_id") != user_id:
                    continue
                if cmd.get("statut") != "en_attente_paiement":
                    continue
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
                    if 0 <= (now_dt - cmd_dt).total_seconds() <= 14400:  # 4h
                        order_id = oid
                        context.user_data["webapp_order_id"] = order_id
                        break
                except Exception:
                    pass

        if not order_id:
            # Notifie quand même l'admin (photo envoyée hors session)
            user_fb = update.effective_user
            uname_fb = f"@{user_fb.username}" if user_fb.username else "_(aucun)_"
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=update.message.photo[-1].file_id,
                    caption=(
                        "📸 *PHOTO reçue — hors session*\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 *{user_fb.full_name}*  {uname_fb}\n"
                        f"🆔 ID : `{user_fb.id}`\n\n"
                        "_Aucune commande en cours trouvée_"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            await update.message.reply_text(
                "👋 Tapez /start pour passer une commande !",
                parse_mode="Markdown",
            )
            return

        user      = update.effective_user
        heure_now = now_str()
        commande  = charger_commande(order_id)

        # Mise à jour du statut via la fonction dédiée
        mettre_a_jour_statut(order_id, "paiement_recu")
        context.user_data.pop("webapp_order_id", None)
        context.user_data.pop("webapp_wise_link", None)
        context.user_data.pop("webapp_pending", None)

        # Confirmation au client
        await update.message.reply_text(
            "╔═══════════════════════════╗\n"
            "║   🎉  COMMANDE VALIDÉE !  ║\n"
            "╚═══════════════════════════╝\n\n"
            f"Merci *{user.first_name}* ! Paiement reçu ✅\n\n"
            f"🆔 Référence : `{order_id}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🕐 *Vous recevrez votre lien de suivi Grab dans les 5 minutes.*\n\n"
            "_Nouvelle commande : /start_",
            parse_mode="Markdown",
        )

        # Notification admin avec reçu + détails
        username_str = f"@{user.username}" if user.username else "_(aucun)_"
        budget  = commande.get("budget", 0) if commande else 0
        prix    = commande.get("prix", 0) if commande else 0
        cuisine = commande.get("cuisine", "?") if commande else "?"
        adresse = commande.get("adresse", "?") if commande else "?"
        lien    = commande.get("lien_commande", "") if commande else ""

        caption = (
            "🆕 *NOUVELLE COMMANDE — PAIEMENT REÇU*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Réf    : `{order_id}`\n"
            f"⏰ Heure  : {heure_now}\n\n"
            f"👤 *{user.full_name}*  {username_str}\n"
            f"🆔 ID     : `{user.id}`\n\n"
            f"🍽️ Cuisine : *{cuisine}*\n"
            f"🔗 Lien    : {lien or '_(non renseigné)_'}\n"
            f"📍 Adresse : {adresse}\n\n"
            f"🛒 Panier  : *{budget:,}฿*\n".replace(",", " ") +
            f"💰 Payé    : *{prix:,}฿*\n".replace(",", " ") +
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ _Paiement confirmé — à traiter_\n\n"
            "📤 *Envoyer le suivi au client :*\n"
            f"`/suivi {order_id} https://lien-grab.com/...`"
        )
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=update.message.photo[-1].file_id,
            caption=caption,
            parse_mode="Markdown",
        )

    # Préchargement du cache mémoire depuis le disque
    _precharger_cache()

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, recevoir_webapp))
    # Callbacks inline (confirmation/annulation webapp)
    app.add_handler(CallbackQueryHandler(webapp_callback, pattern=r"^webapp_(confirm|cancel)_"))
    app.add_handler(CommandHandler("aide",      aide))
    app.add_handler(CommandHandler("help",      aide))
    app.add_handler(CommandHandler("suivi",     envoyer_suivi))
    app.add_handler(CommandHandler("dispo",     cmd_dispo))
    app.add_handler(CommandHandler("pause",     cmd_pause))
    app.add_handler(CommandHandler("statut",    cmd_statut))
    app.add_handler(CommandHandler("commandes", cmd_commandes))
    app.add_handler(CommandHandler("tchat",     cmd_tchat))
    app.add_handler(CommandHandler("rep",       cmd_rep))
    app.add_handler(CommandHandler("canal",     cmd_canal))
    app.add_handler(CommandHandler("promo",     cmd_promo))
    app.add_handler(CommandHandler("annonce",   cmd_annonce))
    # Photo hors conversation — reçu Wise webapp OU message générique
    app.add_handler(MessageHandler(filters.PHOTO, recevoir_paiement_webapp))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, hors_session))

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅  GrabDiscount Bot v3 — démarré")
    print("⏹  Ctrl+C pour arrêter")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


if __name__ == "__main__":
    main()
