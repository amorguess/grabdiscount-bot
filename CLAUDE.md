# GrabDiscount — Contexte projet pour Claude Code

## C'est quoi ce projet ?
Service de réductions Grab Food à Bangkok pour expatriés français.
Les clients commandent via Telegram, on utilise des comptes Grab avec réductions.

## Infrastructure
- **VPS Contabo** : `82.197.70.190` (Ubuntu 24.04, 6 vCPU, 12GB RAM)
- **Dashboard admin** : `http://82.197.70.190:5001` (mot de passe: grabadmin2024)
- **VS Code VPS** : `http://82.197.70.190:8080`
- **GitHub** : https://github.com/amorguess/grabdiscount-bot
- **Données** : `/data/` sur le VPS (accounts.json, orders.json, messages.json)
- **Code** : `/root/grabdiscount/` sur le VPS

## Bot Telegram
- Token : dans `.env` → `BOT_TOKEN`
- Admin chat ID : `8711205448`
- Canal : `-1003910907077`
- Le bot tourne comme subprocess de `start.py` via systemd

## Fichiers principaux
- `start.py` → lance tout (dashboard + bot + scraper)
- `dashboard.py` → interface web admin Flask
- `bot.py` → bot Telegram clients
- `icloud_gen/run.py` → génère emails iCloud (nécessite cookie.txt valide)
- `identity_gen/` → génère identités françaises (nom, prénom, adresse Bangkok)
- `restaurant_scraper.py` → scrape restaurants Grab

## Flux automatique
1. Toutes les 65 min → génère 5 emails iCloud Hide My Email
2. Chaque email → identité française auto-assignée (seed = email)
3. Admin ajoute numéro téléphone manuellement → compte "full"
4. Bot Telegram gère les commandes clients

## Compte full = 
Email iCloud + Identité (nom, prénom, adresse Bangkok) + Numéro tél (manuel)

## Déployer une modification
```bash
# Sur Mac
git add -A && git commit -m "description" && git push origin main

# Sur VPS
cd /root/grabdiscount && git pull origin main && systemctl restart grabdiscount
```

## Commandes VPS utiles
```bash
systemctl restart grabdiscount   # redémarrer
journalctl -u grabdiscount -f    # voir les logs
systemctl status grabdiscount    # vérifier statut
```

## Ce qui NE fonctionne PAS sur VPS
- ADB / Android / Appium (pas de téléphone branché)
- Chrome / Selenium (pas de navigateur graphique)
- iCloud login (nécessite Chrome sur Mac)

## Variables d'environnement (.env sur VPS)
- BOT_TOKEN, ADMIN_CHAT_ID, CHANNEL_ID
- DASHBOARD_PASSWORD=grabadmin2024
- DATA_DIR=/data
- SMSPOOL_KEY (SMSPool - peu utilisé)
