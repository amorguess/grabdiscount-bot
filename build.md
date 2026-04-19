# GrabDiscount — Build Plan

## Stack actuel
- **VPS** : Contabo 82.197.70.190 (Ubuntu 24.04)
- **Backend** : Python / Flask / Waitress
- **Bot** : python-telegram-bot v20
- **Data** : JSON flat files dans /data/
- **Frontend** : Jinja2 + JS vanilla
- **Mini App** : GitHub Pages (webapp/index.html)
- **Domaine** : passfooddelivery.online (Cloudflare + nginx)

---

## Fichiers existants

| Fichier | Rôle | État |
|---|---|---|
| `start.py` | Point d'entrée — lance tout | ✅ stable |
| `dashboard.py` | Interface admin Flask (~3500 lignes) | ✅ stable |
| `bot.py` | Bot Telegram clients v5 | ✅ refait |
| `monitoring.py` | Alertes Telegram (crash, 0 emails) | ✅ stable |
| `restaurant_scraper.py` | Scrape restaurants Grab | ✅ stable |
| `icloud_gen/run.py` | Génère emails iCloud Hide My Email | ✅ stable |
| `identity_gen/` | Génère identités françaises | ✅ stable |
| `webapp/index.html` | Mini App Telegram (GitHub Pages) | ⚠️ à améliorer |

---

## Fichiers à créer

### 1. `subscribers.py` — Gestion abonnés
**Priorité : haute**

Gère la liste des abonnés actifs. Découplé du canal Telegram (on ne kick personne).

```
subscribers.json (dans /data/)
[
  {
    "user_id": 123456789,
    "username": "@tonino",
    "name": "Tonino",
    "status": "active",          // active | expired | blocked
    "subscribed_at": "2026-04-19T20:00:00",
    "expires_at": "2026-05-19T20:00:00",
    "invite_link": "https://t.me/+xxxxx",
    "orders_count": 0
  }
]
```

Fonctions :
- `is_active(user_id)` → bool — remplace le check membership canal dans bot.py
- `add_subscriber(user_id, name, username, days=30)` → crée entrée + génère invite link
- `expire_subscriber(user_id)` → passe à "expired"
- `get_expiring_soon(days=3)` → abonnés qui expirent dans 3 jours (pour rappels auto)

---

### 2. Commandes admin dans `bot.py`

**`/invite USER_ID [Prénom]`**
- Crée lien d'invitation canal unique (1 usage, 30 jours)
- Ajoute dans subscribers.json
- Envoie au client : lien + message de bienvenue

**`/expire USER_ID`**
- Marque l'abonné comme expiré dans subscribers.json
- Envoie au client : "Ton abonnement a expiré, renouvelle pour continuer"
- Ne kick pas du canal → reste dans la communauté

**`/abonnes`**
- Liste tous les abonnés actifs avec date d'expiration
- Indique ceux qui expirent dans 3 jours

**`/block USER_ID`**
- Bloque totalement un utilisateur (spam, problème)

---

### 3. Rappels automatiques dans `monitoring.py`

Cron quotidien (8h Bangkok) qui :
- Cherche abonnés expirant dans 3 jours → envoie rappel au client + alerte admin
- Cherche abonnés expirés depuis hier → envoie message "expiré" au client

---

### 4. Onglet "Abonnés" dans `dashboard.py`

Route `/abonnes` — tableau :

| Nom | Username | Statut | Expire le | Commandes | Actions |
|---|---|---|---|---|---|
| Tonino | @tonino | 🟢 Actif | 19/05/2026 | 3 | Renouveler / Expirer / Message |

- Bouton **Renouveler** → extend de 30 jours
- Bouton **Expirer** → marque expiré
- Bouton **Message** → envoie message direct via bot
- Badge rouge si expiration dans ≤ 3 jours

---

### 5. Flow `/start` pour nouveaux prospects

Quelqu'un qui n'est pas encore abonné contacte le bot :

```
Bienvenue sur GrabDiscount 🛵

Économisez 50% sur toutes vos commandes Grab Bangkok.

💳 Abonnement mensuel : 20€/mois
✅ Accès illimité aux commandes
✅ Service en français
✅ Réponse en moins de 5 minutes

👇 Pour s'abonner, contactez-nous :
[📩 Contacter l'admin]
```

Bouton inline → ouvre une conversation avec l'admin.

---

### 6. `webapp/index.html` — Mini App améliorée

À faire :
- Supprimer le flux budget/cuisine (obsolète)
- Simplifier : bouton "Ouvrir Grab" + instructions screenshot
- Ou : page d'accueil avec statut abonnement + historique commandes

---

## Ordre de build recommandé

```
[x] bot.py v5 — flux simplifié screenshot → adresse   ✅ FAIT
[ ] subscribers.py — fichier + fonctions de base
[ ] bot.py — commandes /invite, /expire, /abonnes
[ ] monitoring.py — rappels expiration auto
[ ] dashboard.py — onglet Abonnés
[ ] bot.py — flow /start prospects non-abonnés
[ ] webapp — simplification mini app
```

---

## Architecture data (cible)

```
/data/
  accounts.json      → comptes Grab (email, nom, tél, statut)
  orders.json        → commandes clients
  messages.json      → historique messages bot
  subscribers.json   → abonnés (user_id, statut, expiration)  ← À CRÉER
  status.json        → statut admin (dispo/pause)
```

---

## Règles métier

- **On ne kick jamais** du canal — les anciens clients restent pour futurs projets
- **1 compte Grab = 1 commande** — jamais réutilisé
- **Accès commandes** contrôlé par `subscribers.json`, pas par membership canal
- **Abonnement** = 30 jours glissants depuis la date d'activation
- **Stripe plus tard** — pour l'instant paiement manuel confirmé par admin

---

## Pour plus tard (v2)

- Stripe webhook → `/invite` automatique à réception du paiement
- Timeline commande éditée en temps réel (un seul message mis à jour)
- "Même commande qu'avant ?" — one-tap reorder
- `/status` client → affiche date expiration + nb commandes du mois
- Stats dashboard : MRR (Monthly Recurring Revenue) en €
