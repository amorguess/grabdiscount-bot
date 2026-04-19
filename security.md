# GrabDiscount — Audit Sécurité

## Résumé

| Priorité | Problème | Statut |
|---|---|---|
| 🔴 CRITIQUE | Mots de passe hardcodés en fallback | À corriger |
| 🟠 HAUTE | Pas de rate limiting sur /login | À corriger |
| 🟠 HAUTE | Pas de protection CSRF sur le dashboard | À corriger |
| 🟡 MOYENNE | Mots de passe Grab stockés en clair | Acceptable / à noter |
| 🟡 MOYENNE | SESSION_COOKIE_SECURE = False | Acceptable (Cloudflare) |
| 🟢 OK | Flask bind 127.0.0.1 | ✅ Fait |
| 🟢 OK | Secret Flask depuis .env | ✅ Fait |
| 🟢 OK | Écriture JSON atomique (race conditions) | ✅ Fait |
| 🟢 OK | Bot token via env var | ✅ Fait |

---

## 🔴 CRITIQUE — Mots de passe hardcodés en fallback

**Fichier :** `dashboard.py:58-59`

```python
DASHBOARD_PWD = os.environ.get("DASHBOARD_PASSWORD", "grabadmin2024")
EMPLOYEE_PWD  = os.environ.get("EMPLOYEE_PASSWORD",  "employe2024")
```

Si les variables d'environnement ne sont pas définies dans `.env`, les mots de passe `grabadmin2024` et `employe2024` s'appliquent silencieusement. N'importe qui qui connaît le code GitHub peut se connecter au dashboard.

**Fix :**
```python
DASHBOARD_PWD = os.environ["DASHBOARD_PASSWORD"]   # Crash au démarrage si absent — c'est voulu
EMPLOYEE_PWD  = os.environ["EMPLOYEE_PASSWORD"]
```

Vérifier que `.env` sur le VPS contient bien ces deux variables :
```bash
grep -E "DASHBOARD_PASSWORD|EMPLOYEE_PASSWORD" /root/grabdiscount/.env
```

---

## 🟠 HAUTE — Pas de rate limiting sur /login

**Fichier :** `dashboard.py:265-273`

La route `/login` accepte un nombre illimité de tentatives par mot de passe. Brute-force possible, surtout si le mot de passe est faible.

**Fix recommandé** — bloquer après 5 échecs pendant 15 minutes :

```python
from collections import defaultdict
import time

_login_attempts: dict[str, list[float]] = defaultdict(list)

@app.route("/login", methods=["GET","POST"])
def login():
    ip = request.remote_addr
    now = time.time()
    # Nettoie les tentatives > 15 min
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 900]

    if len(_login_attempts[ip]) >= 5:
        return render_template_string(LOGIN, err="Trop de tentatives. Réessaie dans 15 min."), 429

    err = ""
    if request.method == "POST":
        if request.form.get("pwd") == DASHBOARD_PWD:
            session["ok"] = True
            _login_attempts.pop(ip, None)
            return redirect("/")
        _login_attempts[ip].append(now)
        err = "Mot de passe incorrect"
    return render_template_string(LOGIN, err=err)
```

---

## 🟠 HAUTE — Pas de protection CSRF

**Fichier :** `dashboard.py` (toutes les routes POST)

Les formulaires POST du dashboard (login, actions sur commandes, etc.) n'ont pas de token CSRF. Un attaquant pourrait forger des requêtes depuis un autre site si l'admin est connecté.

**Mitigation rapide** — ajouter le header `SameSite=Strict` sur le cookie de session :

```python
# dashboard.py
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"  # était "Lax"
```

`Strict` empêche le cookie d'être envoyé depuis un autre site, neutralisant la majorité des attaques CSRF. `Lax` protège les navigations GET mais pas les POST cross-site.

**Fix complet** (si besoin) : utiliser `flask-wtf` pour les tokens CSRF sur chaque formulaire.

---

## 🟡 MOYENNE — Mots de passe Grab stockés en clair

**Fichier :** `dashboard.py:406` → `accounts.json`

Les comptes Grab (email + mot de passe) sont stockés en clair dans `/data/accounts.json`. Si le VPS est compromis, tous les comptes sont exposés.

**Acceptable pour l'instant** car :
- accounts.json est en dehors du répertoire web
- L'accès est contrôlé par le dashboard auth
- Les comptes sont jetables (1 commande = 1 compte, jamais réutilisé)

**À terme :** chiffrement des mots de passe au repos avec `cryptography.fernet`, clé dans `.env`.

---

## 🟡 MOYENNE — SESSION_COOKIE_SECURE = False

**Fichier :** `dashboard.py:36-37`

```python
app.config["SESSION_COOKIE_SECURE"] = False  # False car Flask voit HTTP
```

Flask est derrière Cloudflare qui termine le SSL — Flask ne voit que du HTTP. Le cookie de session ne porte donc pas le flag `Secure`, ce qui est techniquement incorrect mais sans impact réel tant que les communications entre nginx et Flask restent en localhost.

**À vérifier :** nginx ne doit pas être accessible depuis l'extérieur sur le port Flask (5001). Seul le port 443 via Cloudflare doit être ouvert.

```bash
# Vérifier que le port 5001 n'est pas exposé à l'extérieur
ufw status | grep 5001
```

---

## 🟢 OK — Ce qui est déjà en place

### Flask bind sur 127.0.0.1
```python
# start.py:137
serve(dashboard.app, host="127.0.0.1", port=PORT, threads=8)
```
Le dashboard n'est pas directement accessible depuis l'extérieur — nginx proxifie.

### Secret Flask depuis .env
```python
# dashboard.py:29-33
_secret = os.environ.get("DASHBOARD_SECRET")
if not _secret:
    import secrets as _s
    _secret = _s.token_urlsafe(32)  # aléatoire si pas défini — invalide les sessions au restart
```
Le secret de session est soit depuis `.env` (persistant), soit aléatoire au démarrage (invalide toutes les sessions à chaque restart). Ajouter `DASHBOARD_SECRET` dans `.env` pour avoir des sessions persistantes.

### Écriture JSON atomique
Tous les fichiers JSON sont écrits via `tmp → os.replace()` avec `fcntl.flock` — pas de corruption possible si le process crash pendant l'écriture.

### Token bot dans env var
`BOT_TOKEN` n'est jamais hardcodé dans le code. ✅

### Accès commandes via subscribers.json
Depuis la refonte bot v5, l'accès aux commandes est contrôlé par `subscribers.json` (statut `active` + expiration), pas par le membership canal Telegram. Plus robuste.

---

## Checklist déploiement

Avant chaque push en prod :

- [ ] `.env` contient `DASHBOARD_PASSWORD` (pas le fallback hardcodé)
- [ ] `.env` contient `EMPLOYEE_PASSWORD` (pas le fallback hardcodé)
- [ ] `.env` contient `DASHBOARD_SECRET` (token 32 chars)
- [ ] Port 5001 non exposé à l'extérieur (`ufw status`)
- [ ] `subscribers.json` et `accounts.json` non committé dans git (`.gitignore`)
- [ ] `cookie.txt` non committé dans git

---

## .gitignore à vérifier

Ces fichiers ne doivent **jamais** être sur GitHub :

```
.env
/data/
icloud_gen/cookie.txt
icloud_gen/emails.txt
icloud_gen/emails_export.txt
```
