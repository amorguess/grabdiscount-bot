# GrabDiscount — Contexte projet pour Claude Code

## C'est quoi ce projet ?
Service de réductions Grab Food en Thaïlande pour expatriés/voyageurs francophones.
Formule unique : **VIP 20€/mois** (commandes illimitées).
Admin passe les commandes manuellement avec des comptes Grab en stock (1 compte = 1 commande, jamais réutilisé).

## Modèle business
- Plan unique : **VIP 20€/mois** (illimité). `starter` (cap 20/mois) reste supporté en legacy dans `subscribers.py` pour les anciens comptes mais n'est plus proposé.
- Parrainage : -5€ pour le filleul sur son 1er mois ET -5€ pour le parrain sur son prochain renouvellement (symétrique)
- Pause abonnement : `/pauseabo` admin — ~1 mois/an offert (voyages), expiration prolongée d'autant
- Client paie via Wise : `wise.com/pay/r/_XGgs7i3c4CThlg` (20€)
- Paiement confirmé → admin `/invite USER_ID Prénom` → lien canal privé + accès commandes
- Admin reçoit screenshot Grab + compte Grab auto-assigné → passe la commande manuellement
- Canal = communauté permanente (on ne kick jamais, même si expiré)
- Accès commandes contrôlé par `subscribers.json` + `can_order()`, pas par membership canal
- Horaires service : 10h-00h

## Infrastructure
- **VPS Contabo** : `82.197.70.190` (Ubuntu 24.04, 6 vCPU, 12GB RAM)
- **Domaine public** : `passfooddelivery.online` (Cloudflare → nginx sur VPS)
- **Dashboard legacy** : `127.0.0.1:5001` (via nginx sur domaine) — mdp: `grabadmin2024`
- **Dashboard v2** : `127.0.0.1:5002` (systemd `grabdiscount-v2.service`) — Phase B nginx commentée
- **VS Code VPS** : `http://82.197.70.190:8080` (port UFW-filtré, accès tunnel SSH)
- **GitHub** : https://github.com/amorguess/grabdiscount-bot
- **Données** : `/data/` sur le VPS (accounts.json, orders.json, messages.json, status.json, subscribers.json)
- **Code** : `/root/grabdiscount/` sur le VPS

### Cloisonnement réseau (défense en profondeur)
```
Internet ─► Cloudflare (WAF/SSL) ─► nginx:80/443 ─► Flask sur 127.0.0.1
```
- UFW : **seuls 22/80/443 ouverts** (5001/5002/8080 filtered)
- Flask legacy + v2 bind `127.0.0.1` uniquement (v2 refuse explicitement `HOST=0.0.0.0`)
- nginx = seul frontier public, Cloudflare en amont
- Voir `ops/nginx/grabdiscount.conf` et `ops/DEPLOY_V2.md`

## Bot Telegram
- Token : dans `.env` → `BOT_TOKEN`
- Admin chat ID : `8711205448`
- Canal : `-1003910907077`
- Lien invite canal (partagé, filtré par handle_join_request) : `https://t.me/+MLazLZnaShM3OWE1`
- Le bot tourne comme subprocess de `start.py` via systemd

## Fichiers principaux

### Legacy (encore en prod, port 5001)
- `start.py` → lance dashboard legacy + bot sur VPS (systemd `grabdiscount.service`)
- `dashboard.py` → interface web admin Flask legacy
- `bot.py` → bot Telegram clients (v20+, python-telegram-bot)
- `subscribers.py` → gestion abonnés + plans + pause + parrainage (is_active, can_order, add_subscriber(plan=, parrain_id=), get_monthly_usage, pause_subscriber, resume_subscriber, get_referral_credit, get_filleuls, PLAN_CAPS, PLAN_PRICES)
- `icloud_gen/run.py` → génère emails iCloud HME (nécessite cookie.txt valide)
- `icloud_gen/auto_generate.sh` → wrapper LaunchAgent Mac (lock + notify + post-process)
- `icloud_gen/post_process_emails.py` → associe identité FR + adresse Bangkok → accounts.json
- `identity_gen/` → génère identités françaises + adresses Bangkok (seed MD5 déterministe)
- `restaurant_scraper.py` → scrape restaurants Grab

### Refactor v2 (nouvelle archi `app/`, port 5002, parallèle au legacy)
- `run_dashboard_v2.py` → entry point v2 (refuse `HOST=0.0.0.0`, bind 127.0.0.1)
- `app/core/` → config (`Settings` via pydantic), logging structuré, version
- `app/storage/` → stores atomiques (`accounts`, `orders`, `messages`, `subscribers`, `status`, `restaurants`) avec `AtomicJSONFile` + verrous
- `app/dashboard/app.py` → `create_app()` factory Flask + `ProxyFix` (X-Forwarded-*)
- `app/dashboard/stores.py` → `Stores` dataclass (DI) attaché à `app.config["STORES"]`
- `app/dashboard/security.py` → `login_required`, `api_login_required`, `employee_required` (HMAC), `LoginRateLimiter` (sliding window)
- `app/dashboard/api/` → blueprints : auth / health / admin (stats, dispo) / accounts / orders / messages / restaurants
- `tests/` → 202 tests, 96% coverage sur `app/`
- `ops/nginx/grabdiscount.conf` → conf nginx de référence (Cloudflare real IP, rate limit zones, Phase B commentée)
- `ops/systemd/grabdiscount-v2.service` → unit systemd hardened (NoNewPrivileges, ProtectSystem=strict, ReadWritePaths=/data /root/grabdiscount)
- `ops/DEPLOY_V2.md` → procédure de déploiement zéro-port-exposé + rollback

## Flux commande (v5 — bot.py)
1. Client `/start` → envoie screenshot panier Grab
2. Bot demande adresse de livraison
3. Admin reçoit screenshot + adresse + compte Grab assigné automatiquement
4. Admin : bouton "En cours" → "Livré" → compte marqué `used`

## Flux abonnement (mode funnel par le canal)
**Principe** : tout le marketing/pitching se fait sur le canal communauté. Le bot ne vend pas — il ne sert qu'aux abonnés actifs pour commander.

1. Prospect découvre le canal (bouche-à-oreille, post externe, parrainage)
2. Clique `t.me/+MLazLZnaShM3OWE1` → Telegram propose "Demander à rejoindre"
3. `handle_join_request` : décline si non abonné + alerte admin (warm lead)
4. Admin DM le prospect → envoie lien Wise (Starter 20€ ou Pro 30€)
5. Prospect paie → envoie screenshot à l'admin (via @Grabfoodeat)
6. Admin : `/invite USER_ID Prénom [starter|pro]` → ajoute à `subscribers.json` + DM welcome avec bouton "Rejoindre le canal"
7. Prospect re-clique le lien canal → Telegram relance un Join Request → `handle_join_request` auto-approuve (is_active=True)
8. Abonné peut désormais utiliser le bot : `/start` ouvre le flux commande (screenshot → adresse → admin)
9. Cap Starter atteint (20 cmd/mois) → bot bloque + upsell Pro
10. Pause : `/pauseabo USER_ID [jours=30]` prolonge expires_at d'autant
11. Expiration → `/expire USER_ID` → ne peut plus commander, reste dans le canal (pas de kick)

### Bot pour prospect = dead-end redirigé
Si un non-abonné tape `/start` (ou autre) au bot, `_refuser_acces` renvoie un message minimal avec 2 boutons : [📢 Rejoindre le canal] [💬 Contacter l'admin]. Aucun lien Wise direct exposé au prospect — l'admin contrôle le funnel.

### Parrainage
- Abonné tape `/parrainage` → récupère `t.me/<bot>?start=ref_<parrain_id>`
- Filleul ouvre le lien → `start()` parse `ref_X` → stocke dans `_pending_referrals` (RAM)
- Filleul tape /start → pitch affiche "🎁 Tu as été parrainé → -5€"
- Admin fait `/invite <filleul>` → `add_subscriber(parrain_id=...)` → filleul a `had_referral_discount=True`, parrain reçoit `referral_credit_eur += 5`
- Admin notifie parrain automatiquement (DM "Ton filleul X vient de s'abonner")

## Commandes bot
**Client** : `/start` `/parrainage` `/aide` `/annuler` `/tchat`
**Admin** : `/invite` `/expire` `/abonnes` `/block` `/renouveler` `/pauseabo` `/resumeabo` `/dispo` `/pause` `/statut` `/commandes` `/stats` `/canal` `/promo` `/annonce` `/suivi` `/rep`

## Flux automatique emails (Mac uniquement — cookie iCloud)
1. LaunchAgent `com.grabdiscount.email-generation` → toutes les 65 min → `auto_generate.sh`
2. `run.py generate 5` → 5 nouveaux emails iCloud HME dans emails.txt
3. `post_process_emails.py` → associe identité FR + adresse Bangkok → `accounts.json` (status=available)
4. Admin ajoute numéro téléphone manuellement via dashboard → compte "full"
5. Alerte Telegram après 3 échecs consécutifs (cookie expiré)

**Note** : auto-gen dashboard VPS désactivé (`_auto_gen["enabled"]=False`) pour éviter double génération.

## Compte full = 
Email iCloud + Identité (nom, prénom, adresse Bangkok) + Numéro tél (manuel)

## État actuel (2026-04-21)
- ✅ Bot VPS actif, token rotation faite
- ✅ iCloud auto-gen Mac opérationnel (LaunchAgent + post_process + sync VPS)
- ✅ Join Request auto-approval activé (bot admin du canal)
- ✅ Plans Starter/Pro + parrainage (-5€/-5€) + pause abonnement — schéma + bot livrés
- ✅ **Premier compte Grab créé end-to-end** (2026-04-20, `bratty-meshes.0a@icloud.com`) — flux manuel validé
- ✅ **Refactor pro Phase 2 quater livré** (2026-04-21) : Flask factory + blueprints + security (auth/session/rate-limit HMAC) + tous admin routes (stats, dispo, accounts, orders, messages, restaurants)
- ✅ **Dashboard v2 déployé en parallèle sur VPS** : `systemd grabdiscount-v2.service` actif sur `127.0.0.1:5002`, nginx Phase A (tout → legacy 5001), Phase B `/v2/*` prête à activer
- ✅ **202 tests passing, 96% coverage** sur `app/`
- ✅ **Cloisonnement sécurité validé** : UFW = 22/80/443 only, Flask bind localhost (HOST=0.0.0.0 refusé explicite), nginx seul frontier, Cloudflare en amont
- ⏳ Dashboard v2 : pas encore exposé publiquement (nginx Phase B commentée) — décommenter `/v2/` dans `ops/nginx/grabdiscount.conf` pour activer
- ⏳ **Pas encore lancé** — 0 client, 0 abonné
- 📋 ~113 comptes iCloud prêts (available), signup Grab à la volée
- 🧪 Tests à faire : /start depuis compte secondaire, paiement Wise → /invite, parrainage link, cap_reached upsell

## Décision stratégique (2026-04-20) : signup Grab manuel, pas d'auto
**Rationale** : 0 client aujourd'hui, marge Starter 20€ vs coût auto ~500€ dev + proxies. Automatiser = optim prématurée.
**Flux actuel** : quand un client commande → je crée le compte à la volée (~3 min, checklist `tasks/checklist_signup_grab.md`) → je passe la commande depuis l'iPhone.
**Seuil pour automatiser** : 50+ clients actifs OU >20 commandes/jour (charge manuelle >1h/jour).
**Plan usine archivé** : `tasks/plan_usine_grab.md` (7 stages, 6 jours dev) — prêt à réactiver quand seuil atteint.
**Session tokens Grab** : stratégie retenue pour future auto = extraction tokens via `adb shell run-as com.grabtaxi.passenger` + injection sur AVD disposable (évite passkey + re-SMS).

## Apprentissages clés (2026-04-20, manuel)
- SMSPool TH **Quick Order = one-shot** (~$0.11) → numéro recyclé après 1 SMS. Pour re-login = Long-term order ($3-5/mois) OU snapshot emulator OU extraction tokens.
- Grab OTP arrive sous 20s via SMSPool (pas de blacklist VoIP quand le flow est manuel/humain)
- Vérif email Grab obligatoire sous 48h sinon suspension
- HME forwarde vers `ltreves2@gmail.com` (Apple ID de génération). Check **spam Gmail** si pas reçu.
- Passkey obligatoire au signup (stockée iCloud Keychain sur iPhone — reste après désinstall app). Alternative login : phone+OTP (SMS ou WhatsApp) persiste.
- Grab propose 4 méthodes login : passkey / iCloud / Gmail / phone number

## Déployer une modification
```bash
# Sur Mac
git add -A && git commit -m "description" && git push origin main

# Sur VPS
cd /root/grabdiscount && git pull origin main && systemctl restart grabdiscount
```

## Commandes VPS utiles
```bash
# Legacy (bot + dashboard 5001)
systemctl restart grabdiscount   # redémarrer
journalctl -u grabdiscount -f    # voir les logs
systemctl status grabdiscount    # vérifier statut

# Dashboard v2 (5002)
systemctl restart grabdiscount-v2
journalctl -u grabdiscount-v2 -f
systemctl status grabdiscount-v2

# Vérifier cloisonnement (aucun port app exposé au net)
ss -tlnp | grep -E "5001|5002"   # doit TOUJOURS être 127.0.0.1:*
ufw status                        # doit montrer 22/80/443 only
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

## Données /data/
- `accounts.json` → comptes Grab (email, nom, tél, status: available/grab_ready/full/en_cours/used)
- `orders.json` → commandes clients
- `messages.json` → historique messages bot
- `subscribers.json` → abonnés (user_id, plan, status, expires_at, paused_until, monthly_orders, parrain_id, filleuls[], referral_credit_eur, had_referral_discount)
- `status.json` → statut admin dispo/pause

---

# Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
