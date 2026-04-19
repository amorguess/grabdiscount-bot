# GrabDiscount — Self-Improving Agent

## Concept

Un agent IA qui tourne en arrière-plan, observe les données du service (commandes, abonnés, messages), identifie ce qui ne fonctionne pas, et améliore le bot automatiquement — avec différents niveaux d'autonomie selon le risque du changement.

**Boucle fondamentale :**
```
Observe → Analyse (Claude) → Propose → Applique → Mesure → Recommence
```

---

## Ce que l'agent observe

Toutes les données sont déjà disponibles dans `/data/` :

### Métriques de conversion
- `_prospects_notified` (bot.py) → `subscribers.json` actifs = taux de conversion prospect→abonné
- Abonnés expirés sans renouvellement = taux de churn
- Délai entre `/start` et commande passée = friction dans le flux

### Qualité des messages bot
- Client envoie un message dans les 2 min après un message bot = confusion probable
- Commandes annulées = friction ou incompréhension
- `/tchat` après `/start` = client bloqué quelque part

### Opérations
- Nombre de comptes `grab_ready` aux heures de pointe (from `orders.json` timestamps)
- Fréquence des commandes par tranche horaire = heures de pointe réelles
- Délai admin "En attente" → "En cours" = temps de réponse

### Abonnés
- Taux de renouvellement après expiration
- Nombre de commandes par abonné (valeur client)
- Clients qui n'ont jamais commandé malgré un abonnement actif

---

## Architecture

```
agent.py
├── collect_metrics()          → lit orders.json, messages.json, subscribers.json
├── analyze_with_claude()      → envoie les métriques à Claude API
├── apply_safe_changes()       → applique les changements niveau 1 sans confirmation
├── report_to_admin()          → envoie le rapport + suggestions à l'admin via Telegram
└── run()                      → orchestration complète
```

**Nouveau fichier :** `messages_config.json`
```json
{
  "start_welcome": "🛵 *GrabDiscount*...",
  "screenshot_prompt": "📸 *Envoie ton screenshot...*",
  "address_prompt": "📍 *Quelle est ton adresse...*",
  "order_confirmed": "✅ *Commande reçue !*..."
}
```
`bot.py` lit ce fichier au lieu d'avoir les messages hardcodés. L'agent peut réécrire ces messages sans toucher au code.

---

## Niveaux d'autonomie

### Niveau 0 — Rapport uniquement (démarrer ici)
L'agent analyse et envoie un rapport Telegram à l'admin chaque lundi matin.  
Aucune modification automatique. L'admin décide.

### Niveau 1 — Auto-safe (faible risque)
L'agent peut modifier `messages_config.json` — messages du bot, texte des réponses.  
Le bot recharge ce fichier à chaque message → pas de restart nécessaire.  
**Guardrail :** changement limité à 20% du texte original maximum.

### Niveau 2 — Avec confirmation admin
L'agent propose un changement, envoie un bouton Telegram "Appliquer / Ignorer".  
S'applique uniquement si l'admin confirme dans les 24h.  
**Exemples :** modifier un message de bienvenue, ajouter une nouvelle commande bot, changer une règle métier.

### Niveau 3 — Jamais automatique
- Modifications de logique business (prix, durée abonnement)
- Changements de code Python
- Ajout de nouvelles features

---

## Implémentation — agent.py

```python
"""
agent.py — Self-improving agent pour GrabDiscount
==================================================
Tourne une fois par semaine (lundi 9h Bangkok) via monitoring.py.
Analyse les données, identifie les problèmes, améliore le bot.
"""
import os, json, datetime
from pathlib import Path
import anthropic
import requests

DATA_DIR   = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
CODE_DIR   = Path(__file__).parent
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_ID   = int(os.environ.get("ADMIN_CHAT_ID", 0))
CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

ORDERS_F   = DATA_DIR / "orders.json"
SUBS_F     = DATA_DIR / "subscribers.json"
MESSAGES_F = DATA_DIR / "messages.json"
MSG_CFG_F  = CODE_DIR / "messages_config.json"

client = anthropic.Anthropic(api_key=CLAUDE_KEY)


def collect_metrics() -> dict:
    """Collecte toutes les métriques des derniers 7 jours."""
    now     = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    ts_fmt  = "%Y-%m-%dT%H:%M:%S"

    # Chargement des données
    try:
        orders = json.loads(ORDERS_F.read_text())
    except Exception:
        orders = {}
    try:
        subs = json.loads(SUBS_F.read_text())
    except Exception:
        subs = []
    try:
        messages = json.loads(MESSAGES_F.read_text())
    except Exception:
        messages = {}

    # Métriques commandes
    recent_orders = [
        o for o in orders.values()
        if (o.get("ts") or "")[:10] >= week_ago.strftime("%Y-%m-%d")
    ]
    order_statuses = {}
    for o in recent_orders:
        s = o.get("statut", "inconnu")
        order_statuses[s] = order_statuses.get(s, 0) + 1

    # Heures de pointe
    hourly = {}
    for o in recent_orders:
        try:
            h = datetime.datetime.strptime(o["ts"], ts_fmt).hour
            hourly[h] = hourly.get(h, 0) + 1
        except Exception:
            pass
    peak_hours = sorted(hourly.items(), key=lambda x: x[1], reverse=True)[:3]

    # Métriques abonnés
    active_subs  = [s for s in subs if s.get("status") == "active"]
    expired_subs = [s for s in subs if s.get("status") == "expired"]
    # Abonnés actifs qui n'ont jamais commandé
    inactive_subs = [s for s in active_subs if s.get("orders_count", 0) == 0]

    # Confusion client — messages envoyés dans les 2 min après un message bot
    confusion_count = 0
    for uid, conv in messages.items():
        msgs = conv.get("messages", [])
        for i, m in enumerate(msgs[:-1]):
            if m.get("from") == "admin":
                next_m = msgs[i + 1]
                if next_m.get("from") == "client":
                    try:
                        t1 = datetime.datetime.strptime(m["ts"], ts_fmt)
                        t2 = datetime.datetime.strptime(next_m["ts"], ts_fmt)
                        if (t2 - t1).total_seconds() < 120:
                            confusion_count += 1
                    except Exception:
                        pass

    return {
        "periode":           "7 derniers jours",
        "commandes_total":   len(recent_orders),
        "commandes_statuts": order_statuses,
        "heures_pointe":     peak_hours,
        "abonnes_actifs":    len(active_subs),
        "abonnes_expires":   len(expired_subs),
        "abonnes_inactifs":  len(inactive_subs),   # abonnés sans commande
        "confusion_client":  confusion_count,       # réponses < 2min après bot
        "taux_annulation":   order_statuses.get("annule", 0) / max(len(recent_orders), 1),
    }


def analyze_with_claude(metrics: dict) -> dict:
    """
    Envoie les métriques à Claude et demande :
    1. Une analyse des problèmes
    2. Des suggestions concrètes avec niveau de risque
    3. Pour les suggestions niveau 1 : le nouveau texte de message
    """
    # Charge les messages actuels pour que Claude puisse les améliorer
    try:
        current_messages = json.loads(MSG_CFG_F.read_text())
    except Exception:
        current_messages = {}

    prompt = f"""Tu es l'agent d'amélioration du bot GrabDiscount — service de commandes Grab Food à Bangkok pour expatriés français.

## Métriques de la semaine :
{json.dumps(metrics, ensure_ascii=False, indent=2)}

## Messages actuels du bot :
{json.dumps(current_messages, ensure_ascii=False, indent=2)}

## Contexte métier :
- Abonnement 20€/mois → client envoie screenshot panier Grab → admin passe la commande
- Bot Telegram en français, clientèle d'expatriés français à Bangkok
- 1 compte Grab = 1 commande, jamais réutilisé

## Ta mission :
1. Identifie les 2-3 problèmes les plus importants dans ces métriques
2. Pour chaque problème, propose UNE action concrète avec son niveau de risque :
   - NIVEAU_1 : modifier un message du bot (donne le nouveau texte exact)
   - NIVEAU_2 : changement nécessitant confirmation admin (décris le changement)
   - NIVEAU_3 : changement structurel (à discuter avec l'admin)

Réponds UNIQUEMENT en JSON valide, format :
{{
  "analyse": "résumé en 2-3 phrases des problèmes identifiés",
  "suggestions": [
    {{
      "probleme": "description du problème",
      "action": "description de l'action",
      "niveau": 1,
      "message_key": "clé dans messages_config.json si niveau 1",
      "nouveau_texte": "nouveau texte si niveau 1, sinon null"
    }}
  ]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Extrait le JSON même si Claude ajoute du texte avant/après
    start = text.find("{")
    end   = text.rfind("}") + 1
    return json.loads(text[start:end])


def apply_safe_changes(analysis: dict) -> list[str]:
    """Applique automatiquement les suggestions niveau 1 (messages uniquement)."""
    applied = []
    try:
        cfg = json.loads(MSG_CFG_F.read_text())
    except Exception:
        cfg = {}

    for s in analysis.get("suggestions", []):
        if s.get("niveau") != 1:
            continue
        key      = s.get("message_key")
        new_text = s.get("nouveau_texte")
        if not key or not new_text:
            continue

        old_text = cfg.get(key, "")
        # Guardrail : changement max 40% du texte (évite les hallucinations radicales)
        if old_text and len(new_text) < len(old_text) * 0.6:
            continue
        cfg[key] = new_text
        applied.append(f"• `{key}` mis à jour")

    if applied:
        MSG_CFG_F.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

    return applied


def report_to_admin(metrics: dict, analysis: dict, applied: list[str]) -> None:
    """Envoie le rapport complet à l'admin via Telegram."""
    lines = [
        "🤖 *Rapport hebdomadaire — Agent IA*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 *Semaine écoulée :*",
        f"🛵 {metrics['commandes_total']} commandes",
        f"👥 {metrics['abonnes_actifs']} abonnés actifs",
        f"❌ Taux annulation : {metrics['taux_annulation']:.0%}",
        f"😕 Confusions client : {metrics['confusion_client']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔍 *Analyse :*",
        analysis.get("analyse", "—"),
        "",
    ]

    for i, s in enumerate(analysis.get("suggestions", []), 1):
        niveau_emoji = {1: "🟢", 2: "🟡", 3: "🔴"}.get(s.get("niveau"), "⚪")
        lines.append(
            f"{niveau_emoji} *Suggestion {i}* (Niveau {s.get('niveau')})\n"
            f"_{s.get('probleme','')}_\n"
            f"→ {s.get('action','')}"
        )

    if applied:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━",
                  "✅ *Changements appliqués automatiquement :*"] + applied

    pending_n2 = [s for s in analysis.get("suggestions", []) if s.get("niveau") == 2]
    if pending_n2:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━",
                  "⏳ *En attente de ta confirmation :*"]
        for s in pending_n2:
            lines.append(f"• {s.get('action','')}")
        lines.append("\n→ Réponds `/agent approuver` ou `/agent ignorer`")

    text = "\n".join(lines)
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def run() -> None:
    """Point d'entrée principal — appelé par monitoring.py chaque lundi."""
    if not CLAUDE_KEY:
        return
    try:
        metrics  = collect_metrics()
        analysis = analyze_with_claude(metrics)
        applied  = apply_safe_changes(analysis)
        report_to_admin(metrics, analysis, applied)
    except Exception as e:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID,
                      "text": f"❌ *Agent IA erreur :*\n`{e}`",
                      "parse_mode": "Markdown"},
                timeout=5,
            )
        except Exception:
            pass
```

---

## Intégration dans monitoring.py

```python
# Dans _daily_summary_loop(), après send_daily_summary() :
if datetime.datetime.now(bangkok_tz).weekday() == 0:  # lundi
    try:
        import agent
        agent.run()
    except Exception:
        pass
```

---

## messages_config.json (initial)

Créer ce fichier dans le répertoire du code pour activer le niveau 1 :

```json
{
  "start_welcome": "🛵 *GrabDiscount* — Livraison à Bangkok\n\nComment commander :\n1️⃣ Ouvre Grab et choisis ton restaurant\n2️⃣ Prends un *screenshot de ton panier*\n3️⃣ Envoie-le ici avec ton adresse\n4️⃣ On passe la commande pour toi 🍽️\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n📸 *Envoie ton screenshot de panier Grab :*",
  "screenshot_received": "📸 *Screenshot reçu !*\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n📍 *Quelle est ton adresse de livraison ?*\n\n_Exemple : 42 Sukhumvit Soi 11, Bangkok_",
  "order_confirmed": "✅ *Commande reçue !*\n\n⏳ On traite ta commande — tu seras notifié dès qu'elle est passée.",
  "order_in_progress": "👨‍🍳 *Votre commande est en cours de préparation !*\n\n🕐 Vous recevrez votre lien de suivi dans quelques minutes.",
  "order_delivered": "✅ *Commande livrée !*\n\nMerci d'avoir commandé via GrabDiscount ! 🙏\n\n_Pour la prochaine fois : /start_ 🛵",
  "access_denied_prospect": "🛵 *Bienvenue sur GrabDiscount !*\n\nÉconomisez jusqu'à *50%* sur toutes vos commandes Grab Bangkok.\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n💳 Abonnement mensuel : *20€/mois*\n✅ Commandes illimitées\n✅ Service en français 🇫🇷\n✅ Réponse en moins de 5 minutes\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n👇 Pour s'abonner :"
}
```

`bot.py` charge ce fichier au démarrage et à chaque message (avec cache 60s) — l'agent peut modifier les messages sans restart.

---

## Variables d'environnement à ajouter

```bash
# .env sur le VPS
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Ordre de build

```
[ ] Créer messages_config.json avec les textes actuels
[ ] Modifier bot.py pour lire messages_config.json (cache 60s)
[ ] Créer agent.py (collect + analyze + apply + report)
[ ] Intégrer agent.run() dans monitoring.py (lundi 9h Bangkok)
[ ] Tester manuellement : python3 -c "import agent; agent.run()"
[ ] Ajouter ANTHROPIC_API_KEY dans .env VPS
```

---

## Ce que l'agent ne fera jamais automatiquement

- Modifier la logique de vérification d'abonnement
- Changer les prix ou durées d'abonnement
- Accéder à l'API Telegram pour envoyer des messages à des clients (hors rapport admin)
- Modifier dashboard.py ou start.py
- Supprimer des données
