# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Projet

GrabDiscount — Service de réductions Grab Food en Thaïlande pour expatriés/voyageurs francophones. Offre unique **VIP 20€/mois** (commandes illimitées). L'admin passe les commandes manuellement avec des comptes Grab en stock (1 compte = 1 commande, jamais réutilisé).

Le code (commentaires, docstrings, messages Telegram, UI dashboard) est **en français**. Conserve cette convention lorsque tu écris du nouveau code.

## Commandes dev

Tout passe par le `Makefile` (cible `help` pour la liste) :

```bash
make install-dev      # crée .venv + installe dépendances dev + monitoring
make lint             # ruff check
make fmt              # ruff format + fix
make fmt-check        # vérif formatage (CI)
make test             # pytest
make test-cov         # pytest --cov
make run              # start.py (dashboard + bot, comme en prod)
make run-dashboard    # dashboard.py seul (port 5001)
make run-bot          # bot.py seul
make deploy           # git push main + pull VPS + systemctl restart
make vps-logs         # journalctl -u grabdiscount -f
```

Lancer un test unique : `.venv/bin/pytest tests/test_subscribers_store.py::test_name -v`

Dashboard v2 (nouveau, en validation en parallèle du legacy) : `python run_dashboard_v2.py` → port 5002.

## Architecture — où vit le code

Le repo est en **migration progressive** d'un code legacy à plat vers un package `app/` typé. Les deux coexistent et fonctionnent ensemble en prod.

### Legacy (racine — toujours en prod)

- `start.py` — point d'entrée systemd : lance dashboard + bot (subprocess avec retry exponential backoff) + scraper restaurants + health check HTTP instantané (Render compat). Le bot tourne en **subprocess indépendant** pour éviter les conflits asyncio.
- `bot.py` — bot Telegram clients (python-telegram-bot v21, `ConversationHandler`). ~80k lignes monolithiques.
- `dashboard.py` — Flask admin (port 5001). ~179k lignes, exclu du lint.
- `subscribers.py` — source de vérité pour `is_active()`, `can_order()`, `add_subscriber()`, plans, pause, parrainage. Lecture/écriture directe de `subscribers.json` avec `fcntl.flock`.
- `monitoring.py` — alertes Telegram + Sentry + résumé quotidien.
- `restaurant_scraper.py` — scrape Grab, produit `restaurants.json` (8 Mo, dans le repo).

### Nouveau package (`app/` — Phase 2+)

- `app/core/` — `config.py` (Settings dataclass frozen, `get_settings()` singleton lazy), `logging.py`, `exceptions.py` (StorageError, ConfigError…).
- `app/storage/` — `base.py` : `JSONStore[T]` générique, **atomic write** (tmp + `os.replace` + fsync) + `fcntl.flock` inter-processus + cache mtime + `mutate()` transactionnel. Typed stores : `accounts.py`, `orders.py`, `messages.py`, `subscribers.py`, `restaurants.py`.
- `app/dashboard/` — Flask factory `create_app()` + blueprints dans `api/` (auth, health, restaurants). Sécurité : `login_required` / `api_login_required` / `employee_required` + `LoginRateLimiter` (sliding window in-memory, 5 tentatives / 15 min).
- `app/integrations/sentry.py` — init Sentry (SDK 2.x, opt-in via `SENTRY_DSN`).
- `run_dashboard_v2.py` — entry point du nouveau dashboard (port 5002 par défaut).

**Règle de migration** : quand tu touches au code legacy, vérifie si l'équivalent existe déjà dans `app/` — préfère étendre le nouveau. Ne rien casser côté legacy tant que le cutover dashboard v2 n'est pas fait.

### Générateurs (Mac uniquement — ne pas exécuter sur VPS)

- `icloud_gen/` — `run.py` génère des emails HME iCloud (cookie.txt obligatoire), `post_process_emails.py` associe identité FR + adresse Bangkok → `accounts.json`, `auto_generate.sh` wrapper LaunchAgent, `sync_accounts_to_vps.py` push vers VPS.
- `identity_gen/`, `lib/` — génération déterministe (seed MD5) d'identités françaises + adresses Bangkok.
- `grab_gen/`, `sms_gen/` — scaffolding d'auto-signup Grab, **pas en prod** (décision stratégique : signup manuel jusqu'à 50+ clients).

## Flux métier clés

### Commande client
1. `/start` → bot demande screenshot panier Grab.
2. Screenshot → bot demande adresse.
3. Adresse → admin reçoit tout + compte Grab auto-assigné (`status=grab_ready` → `en_cours`).
4. Admin : boutons "En cours" → "Livré" → compte marqué `used`.

### Funnel abonnement (canal-first, bot = dead-end pour prospects)
1. Prospect voit le canal (`COMMUNITY_CHANNEL_LINK` dans `bot.py`) → clique "Demander à rejoindre".
2. `handle_join_request` décline + alerte admin (warm lead).
3. Admin DM le prospect, envoie `WISE_LINK_VIP` (20€).
4. Paiement → admin tape `/invite USER_ID Prénom` → `add_subscriber()` + DM welcome.
5. Prospect re-clique le lien canal → join request auto-approuvé si `is_active(user_id)`.
6. Un non-abonné qui DM le bot tombe sur `_refuser_acces` (2 boutons : rejoindre canal / contacter admin) — **aucun lien Wise exposé**.

### Parrainage (symétrique -5€/-5€)
- Abonné tape `/parrainage` → reçoit `t.me/<bot>?start=ref_<parrain_id>`.
- Filleul ouvre le lien → `_pending_referrals` (RAM) garde le lien.
- Admin `/invite <filleul>` → `add_subscriber(parrain_id=...)` : filleul a `had_referral_discount=True`, parrain reçoit `referral_credit_eur += 5`.

### Commandes bot
- Client : `/start` `/parrainage` `/aide` `/annuler` `/tchat`
- Admin : `/invite` `/expire` `/abonnes` `/block` `/renouveler` `/pauseabo` `/resumeabo` `/dispo` `/pause` `/statut` `/commandes` `/stats` `/canal` `/promo` `/annonce` `/suivi` `/rep`

## Conventions importantes

- **Plans** : `PLAN_CAPS = {"starter": 20, "pro": -1}` ; `DEFAULT_PLAN = "pro"`. `starter` est legacy (anciens comptes), nouveaux clients = `pro` (VIP illimité 20€). Ne pas supprimer `starter` de `subscribers.py`.
- **Accès commandes** ≠ **membership canal** : contrôlé uniquement par `subscribers.json` + `can_order()`. On ne kick jamais du canal (communauté permanente).
- **Horaires service** : 10h–00h (Bangkok). Le bot respecte ça via `/dispo`/`/pause` admin.
- **Atomicité JSON** : toute écriture = `tempfile` + `fsync` + `os.replace` + `fcntl.flock`. Déjà implémenté dans `app/storage/base.py` (nouveau code) et en ligne dans `subscribers.py`/`dashboard.py` (legacy). Ne jamais écrire directement un JSON sans ce pattern — le bot et le dashboard écrivent en concurrence.
- **Pas de fallback hardcodé pour les mots de passe** : `DASHBOARD_PASSWORD` et `DASHBOARD_SECRET` crashent au démarrage si absents (fix sécurité 0a12a4e). Garder cette propriété.
- **Config typée** : dans le nouveau code, consomme `get_settings()` — jamais `os.environ` directement.

## Ruff & lint — périmètre limité

`pyproject.toml` **exclut explicitement le code legacy** du lint (`bot.py`, `dashboard.py`, `subscribers.py`, `start.py`, `monitoring.py`, `restaurant_scraper.py`, `icloud_gen/`, `identity_gen/`, `sms_gen/`, `grab_gen/`, `lib/`, `webapp/`). Ruff ne voit que `app/` + `tests/`. Quand tu migres un module vers `app/`, retire-le de `extend-exclude` dans `pyproject.toml`.

- Line length : 120.
- Format : `double` quotes.
- Les tests ignorent `B` + `SIM`.

## Tests

- `pytest` avec `asyncio_mode = "auto"`.
- `tests/conftest.py` : fixture autouse qui set toutes les env vars obligatoires + pointe `DATA_DIR` vers `tmp_path` → aucun test ne touche le vrai `/data/`.
- Tests existants couvrent : `app/storage/*`, config, exceptions, logging, Sentry, sécurité dashboard (auth + rate limit), API restaurants. Pas encore de tests pour `bot.py`/`dashboard.py` legacy.
- Markers : `slow`, `integration`.

## Infrastructure & déploiement

- **VPS Contabo** : `82.197.70.190` (Ubuntu 24.04). Code dans `/root/grabdiscount/`, données dans `/data/`.
- Service systemd : `grabdiscount` (lance `start.py`).
- Dashboard admin : `http://82.197.70.190:5001` (legacy) — derrière Cloudflare+nginx, donc `ProxyFix` activé, `SESSION_COOKIE_SECURE=False` (SSL terminé en amont).
- Déploiement : `make deploy` (git push → ssh pull → restart).

**Ne fonctionne PAS sur VPS** : ADB/Android/Appium (pas de téléphone), Chrome/Selenium (pas de GUI), iCloud login (nécessite Chrome sur Mac). Les dossiers `grab_gen/`, `icloud_gen/` (génération), `identity_gen/` sont **Mac-only**.

## Variables d'environnement

Obligatoires (crash si manquant) : `BOT_TOKEN`, `ADMIN_CHAT_ID`, `CHANNEL_ID`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET`.
Optionnelles : `EMPLOYEE_PASSWORD` (défaut = `DASHBOARD_PASSWORD`), `DATA_DIR` (défaut = racine repo), `DASHBOARD_PORT` (5001), `SENTRY_DSN`, `SMSPOOL_KEY`, `ICLOUD_EMAIL`/`ICLOUD_APPPASS`, `GIT_TOKEN`.

Template complet dans `.env.example`. Générer `DASHBOARD_SECRET` : `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Fichiers données (`/data/` sur VPS)

- `accounts.json` — comptes Grab. `status` : `available` → `grab_ready` → `full` → `en_cours` → `used`.
- `orders.json` — commandes clients.
- `messages.json` — historique bot.
- `subscribers.json` — abonnés (`user_id, plan, status, expires_at, paused_until, monthly_orders, parrain_id, filleuls[], referral_credit_eur, had_referral_discount, district, source, frequency_stated, onboarded_at`).
- `status.json` — admin dispo/pause.
- `config.json` — budgets/prix dashboard.

## État stratégique (2026-04-21)

- 0 client, 0 abonné — **pas encore lancé**. ~113 comptes iCloud prêts.
- Signup Grab **manuel** (checklist `tasks/checklist_signup_grab.md`), ~3 min/commande. Seuil d'automatisation : 50+ clients actifs ou >20 cmd/jour (plan usine archivé dans `tasks/plan_usine_grab.md`).
- Dashboard v2 (`app/dashboard/`) en construction, legacy toujours en prod.
- Auto-gen emails iCloud désactivée côté VPS (`_auto_gen["enabled"]=False`) — tout passe par le LaunchAgent Mac pour éviter la double génération.

## Principes de travail

- **Simplicité** : fais le changement le plus petit qui résout le problème. Pas d'abstractions préventives, pas de refacto en bonus.
- **Causes racines** : diagnostique avant de patcher. Pas de fix temporaire qui masque un bug.
- **Vérifie avant de dire "fait"** : run les tests, check les logs, prouve que ça marche. Diff le comportement avant/après quand pertinent.
- **Demande si ambigu** : préfère demander qu'inventer une décision archi. Les tâches non-triviales (3+ étapes ou choix archi) méritent une passe de planification.
- **Capture les leçons** : après une correction utilisateur, mets à jour `tasks/lessons.md` avec le pattern (pas l'anecdote).
- **Subagents liberalement** : pour exploration/recherche parallèle, protège le contexte principal.
