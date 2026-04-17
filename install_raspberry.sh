#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  GrabDiscount — Script d'installation Raspberry Pi
#  Compatible : Raspberry Pi 4 / Pi 5 — Raspberry Pi OS 64-bit
# ═══════════════════════════════════════════════════════════════
#
#  UTILISATION :
#    curl -fsSL https://raw.githubusercontent.com/amorguess/grabdiscount-bot/main/install_raspberry.sh | bash
#
#  OU après avoir cloné le repo :
#    chmod +x install_raspberry.sh && ./install_raspberry.sh
#
# ═══════════════════════════════════════════════════════════════

set -e  # Arrête le script si une commande échoue

# ── Couleurs ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[✅]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️ ]${NC} $1"; }
err()  { echo -e "${RED}[❌]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[ℹ️ ]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🛵  GrabDiscount — Installation Pi        ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Vérification : on est bien sur un Pi ────────────────────
if ! uname -m | grep -qE "aarch64|armv7"; then
    warn "Architecture non-ARM détectée — tu n'es peut-être pas sur un Raspberry Pi"
    warn "Le script continue quand même..."
fi

# ── 1. Mise à jour système ───────────────────────────────────
log "Mise à jour du système..."
sudo apt update -qq && sudo apt upgrade -y -qq
log "Système à jour"

# ── 2. Dépendances système ───────────────────────────────────
log "Installation des dépendances système..."
sudo apt install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    htop \
    nano \
    ufw
log "Dépendances installées"

# ── 3. Répertoire de données persistent ─────────────────────
log "Création du répertoire de données /data..."
sudo mkdir -p /data
sudo chown pi:pi /data 2>/dev/null || sudo chown $USER:$USER /data
log "Répertoire /data prêt"

# ── 4. Clonage du projet ─────────────────────────────────────
INSTALL_DIR="$HOME/grabdiscount"

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
DASHBOARD_PORT=5001
DASHBOARD_SECRET=fvmmXXXcieNckT22HUpYUDWLrYk18FYWCCN5aVdMzsQ

# Données (disque persistant)
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

# ── 8. Service systemd (démarrage automatique) ───────────────
log "Configuration du service systemd..."

PYTHON_PATH="$INSTALL_DIR/venv/bin/python3"
USER_NAME=$(whoami)

sudo tee /etc/systemd/system/grabdiscount.service > /dev/null << SERVICEEOF
[Unit]
Description=GrabDiscount Bot + Dashboard
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_PATH $INSTALL_DIR/start.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Redémarre automatiquement si le service plante
StartLimitIntervalSec=60
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
SERVICEEOF

sudo systemctl daemon-reload
sudo systemctl enable grabdiscount
sudo systemctl start grabdiscount
log "Service systemd activé et démarré"

# ── 9. Firewall (optionnel) ───────────────────────────────────
log "Configuration du firewall..."
sudo ufw allow ssh -q
sudo ufw allow 5001/tcp -q   # Dashboard
sudo ufw --force enable -q
log "Firewall configuré (SSH + port 5001 ouverts)"

# ── 10. Trouver l'IP locale ───────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')

# ── Résumé final ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   🎉  Installation terminée avec succès !               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║   📊 Dashboard : http://$LOCAL_IP:5001              ║"
echo "║   🔑 Mot de passe : grabadmin2024                       ║"
echo "║   📁 Données : /data/                                   ║"
echo "║                                                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║   Commandes utiles :                                     ║"
echo "║                                                          ║"
echo "║   Voir les logs en direct :                              ║"
echo "║   sudo journalctl -u grabdiscount -f                     ║"
echo "║                                                          ║"
echo "║   Redémarrer le service :                                ║"
echo "║   sudo systemctl restart grabdiscount                    ║"
echo "║                                                          ║"
echo "║   Arrêter le service :                                   ║"
echo "║   sudo systemctl stop grabdiscount                       ║"
echo "║                                                          ║"
echo "║   Mettre à jour le code :                                ║"
echo "║   cd ~/grabdiscount && git pull && sudo systemctl restart grabdiscount ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
log "Le bot Telegram est actif et le dashboard est accessible sur ton réseau local"
log "Pour accéder depuis l'extérieur : installe Tailscale (gratuit)"
echo ""
info "Tailscale (accès depuis partout) :"
info "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
echo ""
