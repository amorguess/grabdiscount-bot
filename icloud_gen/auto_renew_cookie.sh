#!/bin/bash
# auto_renew_cookie.sh — Renouvelle le cookie iCloud et l'envoie sur le VPS
# Tourne automatiquement tous les 2 jours via launchd

GRAB_DIR="/Users/donamor/grab"
COOKIE="$GRAB_DIR/icloud_gen/cookie.txt"
VPS="root@82.197.70.190"
VPS_PATH="/root/grabdiscount/icloud_gen/cookie.txt"
BOT_TOKEN=$(grep BOT_TOKEN "$GRAB_DIR/.env" 2>/dev/null | cut -d= -f2)
ADMIN_ID="8711205448"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# 1. Extraire le cookie depuis Chrome
log "🔍 Extraction cookie iCloud depuis Chrome…"
python3 "$GRAB_DIR/icloud_gen/grab_cookie_from_chrome.py"

if [ $? -ne 0 ] || [ ! -s "$COOKIE" ]; then
    log "❌ Échec extraction cookie"
    # Notif Telegram
    if [ -n "$BOT_TOKEN" ]; then
        curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d chat_id="$ADMIN_ID" \
            -d text="⚠️ Cookie iCloud expiré — reconnecte-toi sur icloud.com dans Chrome" > /dev/null
    fi
    exit 1
fi

# 2. Envoyer sur le VPS
log "📤 Envoi du cookie sur le VPS…"
scp -o StrictHostKeyChecking=no -o BatchMode=yes "$COOKIE" "$VPS:$VPS_PATH"

if [ $? -ne 0 ]; then
    log "❌ Échec envoi SCP"
    exit 1
fi

log "✅ Cookie renouvelé et envoyé sur le VPS"
