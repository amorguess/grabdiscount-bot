# 🛵 GrabDiscount — Guide complet

---

## 📍 Infos clés à retenir

| Quoi | Valeur |
|------|--------|
| **IP VPS** | `82.197.70.190` |
| **Dashboard** | http://82.197.70.190:5001 |
| **Mot de passe dashboard** | `grabadmin2024` |
| **GitHub** | https://github.com/amorguess/grabdiscount-bot |
| **Dossier code (Mac)** | `/Users/donamor/grab/` |
| **Dossier code (VPS)** | `/root/grabdiscount/` |
| **Dossier données (VPS)** | `/data/` |

---

## 🖥️ Terminal — commandes de base

```bash
# Aller dans un dossier
cd /Users/donamor/grab

# Lister les fichiers
ls

# Voir le contenu d'un fichier
cat dashboard.py

# Chercher un mot dans un fichier
grep "mot" fichier.py
```

---

## 🔗 Connexion au VPS depuis ton Mac

**Toujours depuis ton terminal Mac (pas depuis le VPS) :**

```bash
# Se connecter au VPS
ssh root@82.197.70.190

# Entrer le mot de passe Contabo (celui reçu par mail)
# ⚠️ Le curseur ne bouge pas quand tu tapes le mot de passe — c'est normal
```

**Pour quitter le VPS et revenir sur ton Mac :**
```bash
exit
```

**Transfert de fichier Mac → VPS (depuis ton Mac, PAS depuis le VPS) :**
```bash
scp /Users/donamor/grab/accounts.json root@82.197.70.190:/data/
scp /Users/donamor/grab/icloud_gen/cookie.txt root@82.197.70.190:/root/grabdiscount/icloud_gen/
```

---

## 🚀 Déployer une modification de code sur le VPS

**Étape 1 — sur ton Mac, dans le dossier /Users/donamor/grab :**
```bash
cd /Users/donamor/grab
git add -A
git commit -m "ma modification"
git push origin main
```

**Étape 2 — sur le VPS :**
```bash
ssh root@82.197.70.190
cd /root/grabdiscount
git pull origin main
systemctl restart grabdiscount
```

---

## 🤖 Commandes VPS utiles (une fois connecté en SSH)

```bash
# Voir les logs en direct (Ctrl+C pour quitter)
journalctl -u grabdiscount -f

# Redémarrer le service (bot + dashboard)
systemctl restart grabdiscount

# Arrêter le service
systemctl stop grabdiscount

# Vérifier si le service tourne
systemctl status grabdiscount

# Mettre à jour le code
cd /root/grabdiscount && git pull origin main && systemctl restart grabdiscount

# Voir les fichiers de données
ls /data/

# Voir les comptes
cat /data/accounts.json
```

---

## 📂 Structure des fichiers — ce que fait chaque fichier

### Fichiers principaux
| Fichier | Rôle |
|---------|------|
| `start.py` | Point d'entrée — lance tout (dashboard + bot + scraper) |
| `dashboard.py` | Interface web admin (http://82.197.70.190:5001) |
| `bot.py` | Bot Telegram — répond aux clients |
| `restaurant_scraper.py` | Scrape les restaurants Grab (tourne 1x/24h) |
| `requirements.txt` | Liste des librairies Python nécessaires |
| `.env` | Variables secrètes (tokens, mots de passe) |

### Modules
| Dossier | Rôle |
|---------|------|
| `icloud_gen/` | Génère des emails iCloud Hide My Email |
| `identity_gen/` | Génère des identités françaises (nom, prénom, adresse) |
| `grab_gen/` | Automatisation ADB/Appium (nécessite téléphone Android branché) |
| `sms_gen/` | Achat de numéros SMS virtuels (SMSPool / HeroSMS) |

### Données (sur le VPS dans /data/)
| Fichier | Contenu |
|---------|---------|
| `accounts.json` | Tous les comptes Grab créés (email, identité, statut) |
| `orders.json` | Toutes les commandes clients |
| `messages.json` | Toutes les conversations Telegram |
| `status.json` | Statut du bot (disponible/pause) |

---

## 🍎 iCloud — générer des emails (cookie)

Le cookie iCloud expire tous les **2-3 jours**. Quand la génération d'emails tombe en erreur :

1. Sur ton Mac, ouvre Safari et connecte-toi à **icloud.com**
2. Ouvre les outils développeur (Cmd+Option+I → Network)
3. Cherche un appel vers `appleid.apple.com` et copie le cookie
4. Remplace le fichier : `icloud_gen/cookie.txt`
5. Transfère sur le VPS :
```bash
scp /Users/donamor/grab/icloud_gen/cookie.txt root@82.197.70.190:/root/grabdiscount/icloud_gen/
```

---

## 📱 Accès dashboard depuis le téléphone

1. Ouvre ton navigateur (Safari ou Chrome)
2. Va sur : **http://82.197.70.190:5001**
3. Mot de passe : `grabadmin2024`

---

## 🔄 Comment fonctionne le système complet

```
                    ┌─────────────────────────────────┐
                    │         VPS Contabo              │
                    │       82.197.70.190              │
                    │                                  │
                    │  ┌──────────┐  ┌─────────────┐  │
                    │  │  Bot     │  │  Dashboard  │  │
                    │  │Telegram  │  │  Flask :5001│  │
                    │  └────┬─────┘  └──────┬──────┘  │
                    │       │               │          │
                    │  ┌────▼───────────────▼──────┐  │
                    │  │    /data/                  │  │
                    │  │  accounts.json             │  │
                    │  │  orders.json               │  │
                    │  │  messages.json             │  │
                    │  └───────────────────────────┘  │
                    └─────────────────────────────────┘
                           ▲                  ▲
                           │                  │
                    Clients Telegram      Toi (navigateur)
```

**Flux automatique toutes les 65 minutes :**
1. iCloud génère 5 emails HME
2. Chaque email reçoit une identité française (nom, adresse Bangkok)
3. Les comptes sont sauvegardés dans `accounts.json`
4. Le bot les utilise pour créer des comptes Grab à la demande

---

## 🆘 Dépannage rapide

| Problème | Solution |
|----------|---------|
| Dashboard inaccessible | `ssh root@82.197.70.190` puis `systemctl restart grabdiscount` |
| Bot hors ligne | Même commande — le bot redémarre avec le service |
| Génération email échoue | Cookie iCloud expiré → renouveler cookie.txt |
| Logs pour comprendre une erreur | `journalctl -u grabdiscount -f` |
| Mettre à jour après modif code | `git pull origin main && systemctl restart grabdiscount` (sur VPS) |

---

## 🔑 Variables d'environnement (.env)

Fichier sur le VPS : `/root/grabdiscount/.env`

⚠️ Ne jamais committer les vraies valeurs ici. Le fichier `.env` est sur le VPS uniquement.

```
BOT_TOKEN=...
ADMIN_CHAT_ID=...
CHANNEL_ID=...
DASHBOARD_PASSWORD=...
DASHBOARD_SECRET=...
PORT=5001
DATA_DIR=/data
```

---

*Guide créé le 18 avril 2026*
