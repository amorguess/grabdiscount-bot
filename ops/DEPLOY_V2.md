# Déploiement dashboard v2 — zéro port exposé

## Topologie finale

```
Internet
   │
   ▼
Cloudflare (SSL termination, WAF)
   │
   ▼  (80/443 seuls ports ouverts via UFW)
nginx sur passfooddelivery.online
   │
   ├── /v2/*  → 127.0.0.1:5002  (dashboard v2 — cette session)
   ├── /api/restaurants → 127.0.0.1:5001 (Mini App, legacy cache)
   └── /*    → 127.0.0.1:5001  (dashboard legacy)
```

**Aucun port applicatif n'est exposé au net.** UFW ferme 5001/5002/8080,
Flask bind `127.0.0.1` (refuse `HOST=0.0.0.0`), nginx est l'unique frontier.

## Étapes (sur Mac)

```bash
git add -A
git commit -m "feat: dashboard v2 phase 2 quater + ops nginx/systemd"
git push origin main
```

## Étapes (sur VPS, en SSH)

```bash
# 1. Pull le code
cd /root/grabdiscount && git pull origin main

# 2. Installer les deps du package app/ (si pas déjà fait)
#    pyproject.toml utilise le dossier courant comme package
python3 -m venv .venv 2>/dev/null
.venv/bin/pip install -e .

# 3. Installer le service systemd v2
cp ops/systemd/grabdiscount-v2.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable grabdiscount-v2
systemctl start grabdiscount-v2

# 4. Vérifier que ça écoute bien en local (et PAS sur l'extérieur)
ss -tlnp | grep 5002
#   → Doit afficher :  127.0.0.1:5002   (PAS 0.0.0.0:5002)

# 5. Tester depuis le VPS (pas internet)
curl http://127.0.0.1:5002/api/health
#   → {"status":"ok","version":"0.1.0"}

# 6. Déployer la conf nginx (Phase B activée : décommenter /v2/ dans le fichier)
vim /etc/nginx/sites-enabled/grabdiscount
#   → décommenter le bloc `location /v2/ { ... }`
nginx -t && systemctl reload nginx

# 7. Tester depuis internet
curl https://passfooddelivery.online/v2/api/health
#   → {"status":"ok","version":"0.1.0"}
```

## Rollback

```bash
# Désactive l'accès public v2
vim /etc/nginx/sites-enabled/grabdiscount  # recommenter /v2/
nginx -t && systemctl reload nginx

# Stoppe le worker v2 (legacy continue de tourner intact)
systemctl stop grabdiscount-v2
systemctl disable grabdiscount-v2
```

## Quand bascule complète (Phase C)

Quand tout le flux critique tourne sur v2 en prod depuis ≥ 1 semaine sans incident :

```bash
# Dans /etc/nginx/sites-enabled/grabdiscount :
#   - supprime le block `location /v2/`
#   - change `proxy_pass http://127.0.0.1:5001` → `5002` partout
# Puis :
nginx -t && systemctl reload nginx
systemctl stop grabdiscount
systemctl disable grabdiscount
```

## Vérifications sécurité post-déploiement

```bash
# Confirmer aucun port app exposé
ufw status
nmap -p 5001,5002,8080 82.197.70.190   # depuis une machine externe
#   → "filtered" partout

# Confirmer le binding local Flask
ss -tlnp | grep -E "5001|5002"
#   → tout doit être 127.0.0.1:*
```
