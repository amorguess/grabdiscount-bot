#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  GrabDiscount — Script d'installation VPS Ubuntu
#  Compatible : Ubuntu 22.04 LTS / Contabo / Hetzner / Vultr
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✅]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️ ]${NC} $1"; }
err()  { echo -e "${RED}[❌]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[ℹ️ ]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🛵  GrabDiscount — Installation VPS       ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Mise à jour système ───────────────────────────────────
log "Mise à jour du système..."
apt update -qq && apt upgrade -y -qq
log "Système à jour"

# ── 2. Dépendances système ───────────────────────────────────
log "Installation des dépendances..."
apt install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    htop \
    nano \
    ufw \
    screen
log "Dépendances installées"

# ── 3. Répertoire de données ─────────────────────────────────
log "Création du répertoire /data..."
mkdir -p /data
log "Répertoire /data prêt"

# ── 4. Clonage du projet ─────────────────────────────────────
INSTALL_DIR="/root/grabdiscount"

if [ -d "$INSTALL_DIR" ]; then
    warn "Dossier $INSTALL_DIR existe déjà — mise à jour..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    log "Clonage du projet..."
    git clone https://github.com/amorguess/grabdiscount-bot.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
log "Projet installé dans $INSTALL_DIR"

# ── 5. Environnement Python virtuel ─────────────────────────
log "Création de l'environnement Python virtuel..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r requirements.txt -q
log "Dépendances Python installées"

# ── 6. Fichier .env ──────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
    log "Création du fichier .env..."
    cat > "$INSTALL_DIR/.env" << 'ENVEOF'
# ─────────────────────────────────────────
#  GrabDiscount — Variables d'environnement
# ─────────────────────────────────────────

BOT_TOKEN=8796586342:AAG4HxelgPzuDVLCfZMzcYHRDGRH_C4tig4
ADMIN_CHAT_ID=8711205448
CHANNEL_ID=-1003910907077

# Dashboard
DASHBOARD_PASSWORD=grabadmin2024
PORT=5001
DASHBOARD_SECRET=fvmmXXXcieNckT22HUpYUDWLrYk18FYWCCN5aVdMzsQ

# Données
DATA_DIR=/data

# SMS
SMSPOOL_KEY=kK3UHswUUanyRyz1K1zqaLHF2l78ut46
HEROSMS_KEY=05ef0b6f9230A0e7951514952f60e553

ENVEOF
    log "Fichier .env créé"
else
    warn ".env existe déjà — non modifié"
fi

# ── 7. Copie des données existantes vers /data ───────────────
log "Initialisation des données dans /data..."
for f in orders.json messages.json accounts.json status.json cuisines.json; do
    if [ -f "$INSTALL_DIR/$f" ] && [ ! -f "/data/$f" ]; then
        cp "$INSTALL_DIR/$f" "/data/$f"
        log "Copié : $f → /data/"
    fi
done

# ── 8. Service systemd ───────────────────────────────────────
log "Configuration du service systemd..."

PYTHON_PATH="$INSTALL_DIR/venv/bin/python3"

cat > /etc/systemd/system/grabdiscount.service << SERVICEEOF
[Unit]
Description=GrabDiscount Bot + Dashboard
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_PATH $INSTALL_DIR/start.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
StartLimitIntervalSec=60
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable grabdiscount
systemctl start grabdiscount
log "Service systemd activé et démarré"

# ── 9. Firewall ───────────────────────────────────────────────
log "Configuration du firewall..."
ufw allow ssh -q
ufw allow 5001/tcp -q
ufw --force enable -q
log "Firewall configuré (SSH + port 5001)"

# ── Résumé ────────────────────────────────────────────────────
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "VPS_IP")

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   🎉  Installation terminée avec succès !               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║   📊 Dashboard : http://$PUBLIC_IP:5001            ║"
echo "║   🔑 Mot de passe : grabadmin2024                       ║"
echo "║   📁 Données : /data/                                   ║"
echo "║                                                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║   Commandes utiles :                                     ║"
echo "║   Logs en direct : journalctl -u grabdiscount -f        ║"
echo "║   Redémarrer    : systemctl restart grabdiscount         ║"
echo "║   Arrêter       : systemctl stop grabdiscount            ║"
echo "║   Mettre à jour :                                        ║"
echo "║   cd ~/grabdiscount && git pull &&                       ║"
echo "║   systemctl restart grabdiscount                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
log "Bot Telegram actif — Dashboard accessible sur http://$PUBLIC_IP:5001"
