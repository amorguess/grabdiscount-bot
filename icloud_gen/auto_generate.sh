#!/bin/bash
# auto_generate.sh — Génère automatiquement des emails iCloud HME
# Lancé toutes les 65 min par LaunchAgent com.grabdiscount.email-generation

set -u

GRAB_DIR="/Users/donamor/grab"
ICLOUD_DIR="$GRAB_DIR/icloud_gen"
RUN_PY="$ICLOUD_DIR/run.py"
LOG_FILE="$ICLOUD_DIR/generation.log"
LOCK_FILE="/tmp/grabdiscount_autogen.lock"
EMAILS_BEFORE_FILE="/tmp/grabdiscount_emails_count_before"
COUNT=5  # Emails par run

# Telegram alert
BOT_TOKEN=$(grep -E '^BOT_TOKEN=' "$GRAB_DIR/.env" 2>/dev/null | cut -d= -f2-)
ADMIN_ID="8711205448"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

notify() {
    [ -n "$BOT_TOKEN" ] || return
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d chat_id="$ADMIN_ID" \
        --data-urlencode "text=$1" > /dev/null
}

# ─── Lock pour éviter runs simultanés ───
if [ -e "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        log "⏳ Run déjà en cours (PID $PID), skip"
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

# ─── Vérifier cookie.txt existe ───
if [ ! -s "$ICLOUD_DIR/cookie.txt" ]; then
    log "❌ cookie.txt manquant ou vide"
    notify "⚠️ GrabDiscount: cookie.txt iCloud manquant — relance \`python3 run.py login\`"
    exit 1
fi

# ─── Compter emails avant ───
EMAILS_BEFORE=$(wc -l < "$ICLOUD_DIR/emails.txt" 2>/dev/null || echo 0)

# ─── Génération ───
log "🚀 Démarrage génération de $COUNT emails (total avant: $EMAILS_BEFORE)"
cd "$ICLOUD_DIR"
OUTPUT=$(/usr/bin/python3 "$RUN_PY" generate "$COUNT" 2>&1)
EXIT_CODE=$?

# ─── Compter emails après ───
EMAILS_AFTER=$(wc -l < "$ICLOUD_DIR/emails.txt" 2>/dev/null || echo 0)
GENERATED=$((EMAILS_AFTER - EMAILS_BEFORE))

# ─── Log détaillé ───
log "─── Sortie run.py ───"
echo "$OUTPUT" >> "$LOG_FILE"
log "─── Fin sortie ───"
log "Emails générés: $GENERATED (exit=$EXIT_CODE)"

# ─── Suivi état ───
if [ "$GENERATED" -gt 0 ]; then
    log "✅ $GENERATED emails générés"

    # ─── Associer identité + adresse Bangkok + injecter dans accounts.json ───
    log "🔗 Association identité/adresse → accounts.json"
    POST_OUT=$(/usr/bin/python3 "$ICLOUD_DIR/post_process_emails.py" 2>&1)
    POST_EXIT=$?
    echo "$POST_OUT" >> "$LOG_FILE"
    if [ "$POST_EXIT" -ne 0 ]; then
        log "⚠ post_process_emails.py exit=$POST_EXIT"
        notify "⚠️ GrabDiscount: échec post-process (identité/adresse). Voir generation.log"
    fi

    # Reset compteur d'échecs si existait
    rm -f /tmp/grabdiscount_autogen_fails
else
    log "⚠️ Aucun email généré"
    # Compter échecs consécutifs
    FAILS=$(cat /tmp/grabdiscount_autogen_fails 2>/dev/null || echo 0)
    FAILS=$((FAILS + 1))
    echo "$FAILS" > /tmp/grabdiscount_autogen_fails

    # Alerter après 3 échecs consécutifs
    if [ "$FAILS" -ge 3 ]; then
        notify "⚠️ GrabDiscount: $FAILS échecs consécutifs de génération iCloud. Cookie probablement expiré."
        log "🚨 Alerte Telegram envoyée (${FAILS} échecs)"
    fi
fi

exit $EXIT_CODE
