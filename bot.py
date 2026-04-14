"""
╔══════════════════════════════════════════════════════════╗
║        GRABDISCOUNT BOT — v3                            ║
╚══════════════════════════════════════════════════════════╝
LANCEMENT : python3 bot.py
"""

import os
import re
import json
import logging
import random
import string
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
)

WEBAPP_URL = "https://amorguess.github.io/grabdiscount-bot/webapp/"

# ──────────────────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────────────────

BOT_TOKEN     = os.environ.get("BOT_TOKEN",     "8796586342:AAG4HxelgPzuDVLCfZMzcYHRDGRH_C4tig4")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 8711205448))

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

DATA_DIR    = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(DATA_DIR, "status.json")

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

def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y à %H:%M")

def is_url(text: str) -> bool:
    return bool(re.match(r"https?://\S+", text.strip()))

def get_wise_link(budget: int) -> str:
    return next((lien for m, _, lien in BUDGETS if m == budget), "")

def get_prix_client(budget: int) -> int:
    return next((prix for m, prix, _ in BUDGETS if m == budget), 0)

ORDERS_FILE  = os.path.join(DATA_DIR, "orders.json")
CUISINES_FILE = os.path.join(DATA_DIR, "cuisines.json")

def sauvegarder_commande(order_id: str, chat_id: int, data: dict) -> None:
    """Sauvegarde la commande dans orders.json pour pouvoir envoyer le suivi."""
    try:
        try:
            with open(ORDERS_FILE, "r") as f:
                orders = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            orders = {}

        orders[order_id] = {
            "chat_id": chat_id,
            "nom":     data.get("nom", "Client"),
            "adresse": data.get("adresse", "?"),
            "cuisine": data.get("cuisine", "?"),
            "budget":  data.get("budget", 0),
            "prix":    data.get("prix", 0),
            "heure":   now_str(),
        }
        with open(ORDERS_FILE, "w") as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erreur sauvegarde commande : {e}")

def charger_commande(order_id: str):
    """Charge une commande depuis orders.json."""
    try:
        with open(ORDERS_FILE, "r") as f:
            orders = json.load(f)
        return orders.get(order_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

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
    context.user_data["type_commande"] = "image"
    context.user_data["photo_file_id"] = update.message.photo[-1].file_id

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
    sauvegarder_commande(order_id, user.id, data)

    # ── Confirmation client ────────────────────────────────
    await update.message.reply_text(
        "╔═══════════════════════════╗\n"
        "║   🎉  COMMANDE VALIDÉE !  ║\n"
        "╚═══════════════════════════╝\n\n"
        f"Merci pour votre paiement *{user.first_name}* ! 🙏\n\n"
        f"🆔 Référence : `{order_id}`\n"
        f"🍽️ Cuisine   : *{data['cuisine']}*\n"
        f"📍 Adresse   : {data['adresse']}\n"
        f"💰 Payé      : *{data['prix']:,}฿*\n".replace(",", " ") +
        f"⏰ Heure     : {heure}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ Votre commande est en cours de traitement.\n"
        "🕐 *Vous recevrez votre lien de suivi Grab dans les 5 minutes.*\n\n"
        "_Nouvelle commande : /start_",
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

    now_ts = datetime.now()
    lignes = []
    for oid, cmd in orders.items():
        try:
            cmd_dt = datetime.strptime(cmd.get("heure", ""), "%d/%m %H:%M").replace(year=now_ts.year)
            if (now_ts - cmd_dt).total_seconds() > 86400:
                continue
        except Exception:
            continue
        lignes.append(
            f"🆔 `{oid}` | {cmd.get('nom','?')} | {cmd.get('cuisine','?')} | "
            f"{cmd.get('adresse','?')} | {cmd.get('statut','?')} | {cmd.get('heure','?')}"
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

async def annuler_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def annuler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ *Commande annulée.*\n\nTapez /start pour recommencer.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END

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
        "💬 Un problème ? Contactez-nous.",
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text(
                    "📸 Merci d'envoyer le *screenshot de votre reçu Wise* pour valider.",
                    parse_mode="Markdown"
                )),
            ],
        },
        fallbacks=[
            CommandHandler("annuler", annuler),
            CommandHandler("start",   start),
        ],
        allow_reentry=True,
    )

    # Handler global — capte tout message hors conversation
    async def hors_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Tapez /start pour passer une commande !",
            parse_mode="Markdown",
        )

    # ── Handler Mini App (web_app_data) ──────────────────────
    async def recevoir_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reçoit les données envoyées par tg.sendData() depuis la Mini App."""
        context.user_data.clear()
        data_str = update.message.web_app_data.data
        user = update.effective_user
        heure = datetime.now().strftime("%d/%m %H:%M")
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

            # Sauvegarde en attente de preuve de paiement
            orders = {}
            try:
                with open(ORDERS_FILE) as f:
                    orders = json.load(f)
            except Exception:
                pass
            orders[order_id] = {
                "order_id": order_id,
                "chat_id":  user.id,
                "nom":      user.full_name,
                "username": user.username or "",
                "budget": budget, "prix": prix,
                "cuisine": cuisine, "adresse": address,
                "lien_commande": link,
                "heure": heure, "statut": "en_attente_paiement",
            }
            with open(ORDERS_FILE, "w") as f:
                json.dump(orders, f, ensure_ascii=False, indent=2)

            # Mémorise dans user_data pour capturer la preuve de paiement
            context.user_data["webapp_order_id"] = order_id

            # Confirmation client — lui demande d'envoyer le reçu
            await update.message.reply_text(
                "╔═══════════════════════════╗\n"
                "║   💳  PAIEMENT EN COURS   ║\n"
                "╚═══════════════════════════╝\n\n"
                f"🆔 Réf : `{order_id}`\n"
                f"🍽️ {cuisine}\n"
                f"📍 {address}\n"
                f"💰 À payer : *{prix:,}฿* via Wise\n\n".replace(",", " ") +
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📸 *Envoyez le screenshot de votre reçu Wise*\n"
                "pour que nous validions et passions la commande ! ✅",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("👋 Commande reçue !")

    # ── Reçu Wise après flux Mini App ──────────────────────
    async def recevoir_paiement_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
        order_id = context.user_data.get("webapp_order_id")
        if not order_id:
            # Cherche une commande récente (< 2h) en attente de paiement pour ce user
            user_id = update.effective_user.id
            try:
                with open(ORDERS_FILE) as f:
                    orders = json.load(f)
                now_ts = datetime.now()
                for oid, cmd in orders.items():
                    if (
                        cmd.get("chat_id") == user_id
                        and cmd.get("statut") == "en_attente_paiement"
                    ):
                        try:
                            cmd_dt = datetime.strptime(cmd.get("heure", ""), "%d/%m %H:%M").replace(
                                year=now_ts.year
                            )
                            diff = (now_ts - cmd_dt).total_seconds()
                            if 0 <= diff <= 7200:
                                order_id = oid
                                context.user_data["webapp_order_id"] = order_id
                                break
                        except Exception:
                            pass
            except Exception:
                pass
        if not order_id:
            # Photo reçue hors contexte → message générique
            await update.message.reply_text(
                "👋 Tapez /start pour passer une commande !",
                parse_mode="Markdown",
            )
            return

        user      = update.effective_user
        heure_now = now_str()
        commande  = charger_commande(order_id)

        # Mise à jour du statut dans orders.json
        try:
            with open(ORDERS_FILE) as f:
                orders = json.load(f)
            if order_id in orders:
                orders[order_id]["statut"] = "paiement_recu"
            with open(ORDERS_FILE, "w") as f:
                json.dump(orders, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        context.user_data.pop("webapp_order_id", None)

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

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, recevoir_webapp))
    app.add_handler(CommandHandler("aide",   aide))
    app.add_handler(CommandHandler("help",   aide))
    app.add_handler(CommandHandler("suivi",  envoyer_suivi))
    app.add_handler(CommandHandler("dispo",     cmd_dispo))
    app.add_handler(CommandHandler("pause",     cmd_pause))
    app.add_handler(CommandHandler("statut",    cmd_statut))
    app.add_handler(CommandHandler("commandes", cmd_commandes))
    # Photo hors conversation — reçu Wise webapp OU message générique
    app.add_handler(MessageHandler(filters.PHOTO, recevoir_paiement_webapp))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, hors_session))

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅  GrabDiscount Bot v3 — démarré")
    print("⏹  Ctrl+C pour arrêter")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
