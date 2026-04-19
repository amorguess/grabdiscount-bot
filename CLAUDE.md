# GrabDiscount — Contexte projet pour Claude Code

## C'est quoi ce projet ?
Service de réductions Grab Food à Bangkok pour expatriés français.
Modèle : abonnement **20€/mois** → accès canal privé Telegram → commandes illimitées.
Admin passe les commandes manuellement avec des comptes Grab en stock (1 compte = 1 commande, jamais réutilisé).

## Modèle business
- Client paie 20€/mois → reçoit lien d'invitation canal privé via le bot
- Une fois dans le canal → peut commander via `/start` dans le bot
- Admin reçoit screenshot Grab + compte Grab auto-assigné → passe la commande manuellement
- Canal = communauté permanente (on ne kick jamais, même si expiré)
- Accès commandes contrôlé par `subscribers.json`, pas par membership canal

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
- `subscribers.py` → gestion abonnés (à créer — voir build.md)
- `build.md` → plan complet de tout ce qui reste à faire

## Flux commande (v5 — bot.py)
1. Client `/start` → envoie screenshot panier Grab
2. Bot demande adresse de livraison
3. Admin reçoit screenshot + adresse + compte Grab assigné automatiquement
4. Admin : bouton "En cours" → "Livré" → compte marqué `used`

## Flux abonnement (à builder — voir build.md)
1. Prospect contacte bot → reçoit pitch abonnement
2. Admin confirme paiement → `/invite USER_ID` → lien canal envoyé + ajouté subscribers.json
3. Expiration → `/expire USER_ID` → ne peut plus commander, reste dans le canal

## Flux automatique emails
1. Toutes les 65 min → génère 5 emails iCloud Hide My Email
2. Chaque email → identité française auto-assignée (seed = email)
3. Admin ajoute numéro téléphone manuellement → compte "full"

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

## Données /data/
- `accounts.json` → comptes Grab (email, nom, tél, status: available/grab_ready/full/en_cours/used)
- `orders.json` → commandes clients
- `messages.json` → historique messages bot
- `subscribers.json` → abonnés actifs (à créer)
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
