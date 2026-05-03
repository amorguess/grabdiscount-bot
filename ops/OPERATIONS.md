# GrabDiscount — Manuel d'opérations

> **Objectif**: te permettre d'exploiter le système au quotidien sans assistance technique externe. Tout ce qu'il faut faire, savoir, dépanner.

---

## 1. Architecture en une page

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│   Internet ─► Cloudflare (WAF + SSL) ─► nginx :443 (VPS Contabo)           │
│                                              │                             │
│                                              ├─► /          → :5001        │
│                                              │              dashboard.py   │
│                                              │              (legacy)       │
│                                              │                             │
│                                              └─► /v2/*      → :5002        │
│                                                              app/dashboard │
│                                                              (refactor)    │
│                                                                            │
│   Bot Telegram (subprocess de start.py) ◄── token .env                     │
│   ├─► CHOIX_ZONE  : 🇹🇭 Grab / 🇦🇺 Uber AU / 🇫🇷 Uber FR                    │
│   ├─► ATTENTE_COMMANDE  (screenshot panier)                                │
│   └─► ATTENTE_ADRESSE   → assignation compte de la zone                    │
│                                                                            │
│   Données /data/                                                           │
│   ├─ accounts.json   (pool comptes, 3 zones par compte)                    │
│   ├─ orders.json     (commandes — inclut champ `zone`)                     │
│   ├─ subscribers.json                                                      │
│   ├─ messages.json                                                         │
│   ├─ status.json     (dispo on/off)                                        │
│   └─ audit.log       (NDJSON append-only — actions admin)                  │
│                                                                            │
│   LaunchAgent Mac (com.grabdiscount.email-generation)                      │
│   ├─ toutes les 65 min : run.py generate 5                                 │
│   └─ post_process_emails.py → 3 adresses (TH+AU+FR) par email iCloud       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

## 2. URLs et accès

| Service | URL | Auth |
|---|---|---|
| Dashboard admin (prod) | https://passfooddelivery.online/login | mdp + 2FA TOTP (optionnel) |
| Dashboard v2 (refactor) | https://passfooddelivery.online/v2/* | session partagée |
| VS Code VPS (debug) | http://82.197.70.190:8080 | tunnel SSH uniquement |
| GitHub repo | https://github.com/amorguess/grabdiscount-bot | git creds |
| Bot Telegram | @Grabfoodeat | n/a |

## 3. Routine quotidienne (5 min)

1. **Ouvrir le dashboard**, vérifier la **bannière d'alertes** en haut. Tout vert = rien à faire.
2. Si **🚨 cookie iCloud trop vieux** → cliquer 🍪 Cookie, uploader un fresh cookie depuis Chrome Mac.
3. Si **🚨 stock zone TH < 5 comptes** → ajouter des numéros aux comptes "Sans numéro" puis créer le compte Grab manuellement (cf. checklist § 7).
4. Lire les commandes du jour, répondre aux messages clients.
5. Marquer les commandes terminées comme "Livré" pour libérer les comptes en `used` propre.

## 4. Routine hebdomadaire (15 min)

1. **Stats** : revue MRR / churn / runway zones (page Vue d'ensemble).
2. **Cookie iCloud** : renouveler manuellement même s'il n'expire pas (anti-suspicion Apple).
3. **Backup** : bouton "Backup" du dashboard → télécharger le ZIP.
4. **Audit log** : `https://passfooddelivery.online/api/audit?n=200` → vérifier qu'aucune action suspecte.
5. **Push code Mac → VPS** si modifs faites en local.

## 5. Sécurité (à faire UNE fois, puis oublier)

### 5.1 Activer la 2FA TOTP

```bash
# Sur le VPS
cd /root/grabdiscount
pip install pyotp qrcode
python3 scripts/setup_2fa.py
# Note le secret affiché, scanne le QR dans Authy / Google Auth
# Ajoute dans /root/grabdiscount/.env :
echo "DASHBOARD_TOTP_SECRET=XXXXXXXXXXXX" >> .env
systemctl restart grabdiscount
```

Test : login → un champ "Code 2FA" apparaît → entrer le code 6 chiffres de l'app.

### 5.2 Rotation du mot de passe dashboard

```bash
# Sur le VPS
NEW=$(openssl rand -base64 24 | tr -d '=+/')
# Édite .env → DASHBOARD_PASSWORD=$NEW
nano /root/grabdiscount/.env
systemctl restart grabdiscount
```

⚠ **Ne plus jamais committer `DASHBOARD_PASSWORD` en clair dans CLAUDE.md ou ailleurs.**

### 5.3 (Optionnel) Cloudflare Access devant /login

1. Cloudflare Dashboard → Zero Trust → Access → Applications
2. Add an application → Self-hosted
3. Domain: `passfooddelivery.online`, Path: `/login`
4. Policy: Allow → Emails: `amorguesmipro@gmail.com`
5. Auth method: One-Time PIN par email
→ Plus aucun login direct sans pin email + mdp + TOTP

## 6. Déploiement modifs code

```bash
# Sur Mac
git add -A && git commit -m "feat: ..." && git push origin main

# Sur VPS (SSH)
cd /root/grabdiscount
git pull origin main

# Si requirements.txt a changé :
pip install -r requirements.txt

# Restart le service concerné :
systemctl restart grabdiscount         # legacy + bot
systemctl restart grabdiscount-v2      # v2 dashboard (5002)

# Vérifier :
systemctl status grabdiscount
journalctl -u grabdiscount -n 50 --no-pager
```

## 7. Checklist signup compte Grab manuel

(Voir `tasks/checklist_signup_grab.md` pour la version détaillée.)

1. Sur le dashboard, onglet "Comptes" → 🇹🇭 Grab Thaïlande → choisir un compte "Sans numéro"
2. Acheter un numéro SMSPool TH (Quick Order) — copier le numéro
3. Le coller dans le champ phone du compte → 💾 → statut → "full"
4. Sur l'iPhone : ouvrir l'app Grab → signup avec email iCloud + numéro + identité du compte
5. Rentrer l'OTP reçu sur SMSPool
6. Vérifier email Grab via inbox iCloud HME (lien dans dashboard "Mails")
7. Compte prêt → utilisable sur la prochaine commande

**Les zones AU et FR n'ont pas encore de checklist** : à mettre en place quand premier client demande Uber.

## 8. Migration accounts.json (3 zones)

Une seule fois après mise en prod du système 3 zones :

```bash
# Sur le VPS (data dir = /data/)
cd /root/grabdiscount
python3 scripts/migrate_dual_zone.py --file /data/accounts.json
# → dry-run d'abord, vérifier l'aperçu
python3 scripts/migrate_dual_zone.py --file /data/accounts.json --apply
# → backup auto + écriture
systemctl restart grabdiscount
```

Idempotent : peut être relancé sans risque.

## 9. Alertes — comment réagir

| Alerte | Cause | Action |
|---|---|---|
| 🚨 Cookie iCloud absent | Pas de `cookie.txt` | Ouvrir Chrome Mac → iCloud → cliquer 🍪 Cookie → uploader |
| 🚨 Cookie iCloud trop vieux (>60h) | Inactivité Apple | Renouveler depuis Chrome (auto-renew Mac doit tourner) |
| ⚠️ Cookie vieillit (>36h) | Préventif | Renouveler avant 72h |
| 🚨 Stock TH critique (<5 prêts) | Pas assez de comptes signup | Ajouter numéros + signup manuel (§7) |
| ⚠️ N comptes en échec | Signup raté | "Reset failed" sur l'onglet zone, puis investigate |
| 🚨 Bot Telegram hors ligne | Service down | `systemctl restart grabdiscount` |
| ℹ️ Hors horaire | < 10h ou > minuit | Le bot affichera "service fermé" automatiquement |
| ⚠️ Quota iCloud HME épuisé | 5 emails / 24h générés | Attendre reset (affiché dans l'alerte) |

## 10. Dépannage rapide

### Le dashboard ne charge plus
```bash
systemctl status grabdiscount
journalctl -u grabdiscount -n 100 --no-pager
# Erreur d'import ? → manque dep
pip install -r requirements.txt
systemctl restart grabdiscount
```

### Le bot ne répond pas
```bash
# Vérifier le token
curl "https://api.telegram.org/bot$BOT_TOKEN/getMe"
# Si erreur → token rotaté ? → mettre à jour .env
# Sinon
systemctl restart grabdiscount
```

### Une commande a verrouillé un compte sans le libérer
```bash
# Côté dashboard
# Onglet Comptes → trouver le compte en `en_cours` orphelin
# Cliquer "Libérer" → le compte repasse en `full` ou `used`
```

### Un compte a été marqué `failed` à tort
```bash
# Onglet Comptes → 🔄 Reset failed (zone active)
```

## 11. Variables d'environnement (.env)

```bash
# Bot Telegram
BOT_TOKEN=xxx
ADMIN_CHAT_ID=8711205448
CHANNEL_ID=-1003910907077

# Dashboard
DASHBOARD_PASSWORD=xxx           # mdp principal
DASHBOARD_TOTP_SECRET=xxx        # optionnel — active 2FA si défini
DATA_DIR=/data                   # racine des fichiers JSON

# Externe
SMSPOOL_KEY=xxx                  # SMSPool API
```

## 12. Backups

- **Auto** : (à formaliser — bouton "Backup" zip les JSON dans /tmp)
- **Manuel** : `tar czf accounts_$(date +%F).tar.gz /data/*.json` puis copie hors VPS
- **Restore** : décompresser dans `/data/` puis restart les services

## 13. Roadmap d'amélioration (priorité décroissante)

Voir `tasks/roadmap.md` (à créer) pour le détail. Résumé :

- **P0** : 3 zones intégrées ✅ / alertes ✅ / 2FA + audit ✅
- **P1** : refonte page Vue d'ensemble (MRR / churn / heatmap horaire)
- **P1** : page Settings consolidée (mdp, horaires, tarifs, webhooks)
- **P2** : extraction templates Jinja2, bundler Vite
- **P2** : SSE pour chat, search Cmd+K, bulk actions
- **P3** : migration JSON → SQLite, déprécier dashboard.py au profit de v2

## 14. Contacts d'urgence

- **Hébergeur VPS** : Contabo support
- **Domaine + DNS + WAF** : Cloudflare
- **Téléphonie SMS** : SMSPool
- **Bot Telegram** : @BotFather (regen token si compromis)

---

_Document à jour au 2026-05-03. Mettre à jour à chaque changement structurel majeur._
