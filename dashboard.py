#!/usr/bin/env python3
"""GrabDiscount — QG Admin v3"""
from __future__ import annotations
import os, json, re, subprocess, threading, datetime, functools, requests, fcntl
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for, make_response
from werkzeug.middleware.proxy_fix import ProxyFix
import monitoring

app = Flask(__name__)
# Derrière Cloudflare + nginx : on fait confiance aux headers X-Forwarded-*
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)

@app.after_request
def no_cache(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response

# Secret Flask : obligatoire depuis .env, jamais hardcodé
_secret = os.environ.get("DASHBOARD_SECRET")
if not _secret:
    import secrets as _s
    _secret = _s.token_urlsafe(32)
app.secret_key = _secret

# Cookies sécurisés sur HTTPS
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = False  # False car Flask voit HTTP (Cloudflare termine SSL)

_CODE_DIR   = Path(__file__).parent                             # dossier du code
BASE        = Path(os.environ.get("DATA_DIR", str(_CODE_DIR)))  # données → DATA_DIR si dispo
ORDERS_F    = BASE / "orders.json"
MESSAGES_F  = BASE / "messages.json"
ACCOUNTS_F  = BASE / "accounts.json"
CONFIG_F    = BASE / "config.json"
EXPORT_F    = _CODE_DIR / "icloud_gen" / "emails_export.txt"    # emails générés = code
EMAILS_F    = _CODE_DIR / "icloud_gen" / "emails.txt"
STATUS_F    = BASE / "status.json"

DEFAULT_CONFIG = {
    "budgets": [
        {"panier": 1000, "prix": 500,  "wise": "https://wise.com/pay/r/Fk4y8LLVr8a-Z0M"},
        {"panier": 2000, "prix": 1000, "wise": "https://wise.com/pay/r/Z_Lts2te9J1YA98"},
    ]
}

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_ID      = int(os.environ.get("ADMIN_CHAT_ID", 0))
DASHBOARD_PWD = os.environ.get("DASHBOARD_PASSWORD", "grabadmin2024")  # fallback si env var absente
EMPLOYEE_PWD  = os.environ.get("EMPLOYEE_PASSWORD", "employe2024")     # mot de passe espace employé

# Token simple pour l'espace employé (pas de cookie)
import hashlib as _hl
_EMP_TOKEN = _hl.sha256(f"emp:{EMPLOYEE_PWD}:grabdiscount".encode()).hexdigest()
_EMPLOYE_ID = "emp_" + _hl.sha256(EMPLOYEE_PWD.encode()).hexdigest()[:16]

def _get_employe_id():
    """ID stable de l'employé — dérivé du mot de passe, pas de session."""
    return _EMPLOYE_ID

# ── Verrou I/O pour éviter les race conditions ─────────────
_io_lock = threading.Lock()

_gen_status = {"running": False, "log": "", "last_run": None}

# ── Auto-génération toutes les 65 min ─────────────────────
_auto_gen = {
    "enabled":    False,       # géré par LaunchAgent Mac (com.grabdiscount.email-generation)
    "interval":   65,          # minutes entre chaque run
    "count":      5,           # emails par run
    "total":      0,           # total généré depuis le démarrage
    "next_run":   None,        # ISO string prochain lancement
    "last_run":   None,
    "last_count": 0,
    "log":        [],          # historique des runs (max 20)
}
_auto_timer: threading.Timer | None = None
_auto_lock  = threading.Lock()

# ── HELPERS ───────────────────────────────────────────────
def rj(p, default=None):
    """Lecture JSON avec verrou partagé."""
    try:
        with open(p, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except Exception:
        return default if default is not None else {}

def wj(p, data):
    """Écriture atomique JSON : tmp → rename, avec verrou exclusif."""
    tmp = str(p) + ".tmp"
    with _io_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp, str(p))

def tg(chat_id, text):
    if not BOT_TOKEN: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=8)
        return r.json().get("ok", False)
    except: return False

def stats():
    orders = rj(ORDERS_F, {})
    msgs   = rj(MESSAGES_F, {})
    total  = len(orders)
    pend   = sum(1 for o in orders.values() if o.get("statut") in ("en_attente_paiement","en_attente_confirmation"))
    paid   = sum(1 for o in orders.values() if o.get("statut") in ("paiement_recu","en_cours"))
    done   = sum(1 for o in orders.values() if o.get("statut") == "livre")
    rev    = sum(o.get("prix",0) for o in orders.values() if o.get("statut") not in ("annule","en_attente_confirmation","en_attente_paiement"))
    unread = sum(m.get("unread",0) for m in msgs.values())
    # Revenue 7 derniers jours
    daily = {}
    for o in orders.values():
        if o.get("statut") in ("annule","en_attente_confirmation","en_attente_paiement"): continue
        try:
            d = o.get("ts","")[:10] or datetime.datetime.strptime(o.get("heure",""), "%d/%m/%Y à %H:%M").strftime("%Y-%m-%d")
            daily[d] = daily.get(d,0) + o.get("prix",0)
        except: pass
    days, revs = [], []
    for i in range(6,-1,-1):
        d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        days.append(d[5:])   # MM-DD
        revs.append(daily.get(d,0))
    return {"total":total,"pending":pend,"paid":paid,"done":done,"revenue":rev,
            "margin":rev//2,"unread":unread,"days":days,"revs":revs}

def icloud_quota():
    """Calcule quota Apple HME : max ~5 emails par session / 24h."""
    accounts = rj(ACCOUNTS_F, [])
    now = datetime.datetime.now()
    recent = []
    for a in accounts:
        try:
            ts = datetime.datetime.strptime(a["created"], "%Y-%m-%dT%H:%M:%S")
            if (now - ts).total_seconds() < 86400:
                recent.append(ts)
        except: pass
    used_today = len(recent)
    DAILY_LIMIT = 5
    remaining = max(0, DAILY_LIMIT - used_today)
    # Reset = 24h après le plus ancien des recent
    if recent:
        oldest = min(recent)
        reset_at = oldest + datetime.timedelta(hours=24)
        secs = max(0, (reset_at - now).total_seconds())
        h, m = int(secs//3600), int((secs%3600)//60)
        reset_str = f"{h}h {m:02d}m"
    else:
        reset_str = "Disponible maintenant"
    return {"used": used_today, "limit": DAILY_LIMIT, "remaining": remaining, "reset": reset_str}

# ── AUTH ──────────────────────────────────────────────────
def auth(f):
    @functools.wraps(f)
    def wrap(*a, **kw):
        if not session.get("ok"): return redirect("/login")
        return f(*a, **kw)
    return wrap

def emp_auth(f):
    """Auth employé via cookie emp_tok (persistant 7j)."""
    @functools.wraps(f)
    def wrap(*a, **kw):
        if request.cookies.get("emp_tok") != _EMP_TOKEN:
            return jsonify({"ok": False, "error": "auth"}), 401
        return f(*a, **kw)
    return wrap

# ─────────────────────────────────────────────────────────────
#  AUTO-GÉNÉRATION iCloud HME (toutes les 65 min)
# ─────────────────────────────────────────────────────────────

def _run_auto_gen():
    """Lance une génération silencieuse puis replanifie si toujours activée."""
    global _auto_timer
    with _auto_lock:
        if not _auto_gen["enabled"]:
            return
        if _gen_status["running"]:
            # Déjà en cours — on replanifie sans générer
            _schedule_next()
            return

    _gen_status["running"] = True
    ts = datetime.datetime.now()
    count = _auto_gen["count"]
    log_entry = {"ts": ts.strftime("%H:%M"), "count": 0, "ok": False}

    try:
        import subprocess as _sp
        proc = _sp.run(
            ["python3", str(_CODE_DIR / "icloud_gen" / "run.py"), "generate", str(count)],
            capture_output=True, text=True, cwd=str(_CODE_DIR), timeout=120
        )
        out = proc.stdout + proc.stderr
        # Compte les emails réellement générés
        generated = len([l for l in out.splitlines() if l.strip().startswith("✅") and "@icloud.com" in l])
        log_entry["count"] = generated
        log_entry["ok"]    = generated > 0
        with _auto_lock:
            _auto_gen["total"]      += generated
            _auto_gen["last_run"]    = ts.isoformat()
            _auto_gen["last_count"]  = generated
            _auto_gen["log"].insert(0, log_entry)
            _auto_gen["log"]         = _auto_gen["log"][:20]   # garde 20 entrées
        if generated:
            _reload_accounts()
        else:
            monitoring.alert_zero_emails(_auto_gen.get("total", 0))
    except Exception as e:
        log_entry["error"] = str(e)
        with _auto_lock:
            _auto_gen["log"].insert(0, log_entry)
        monitoring.alert_email_gen_error(str(e))
    finally:
        _gen_status["running"] = False

    with _auto_lock:
        if _auto_gen["enabled"]:
            _schedule_next()

def _schedule_next():
    """Planifie le prochain run dans interval minutes."""
    global _auto_timer
    if _auto_timer:
        _auto_timer.cancel()
    interval_s = _auto_gen["interval"] * 60
    next_dt    = datetime.datetime.now() + datetime.timedelta(seconds=interval_s)
    _auto_gen["next_run"] = next_dt.isoformat()
    _auto_timer = threading.Timer(interval_s, _run_auto_gen)
    _auto_timer.daemon = True
    _auto_timer.start()

def _schedule_immediate(delay_min: int = 5):
    """Lance une génération dans `delay_min` minutes (utilisé au démarrage)."""
    global _auto_timer
    if _auto_timer:
        _auto_timer.cancel()
    delay_s = delay_min * 60
    next_dt = datetime.datetime.now() + datetime.timedelta(seconds=delay_s)
    _auto_gen["next_run"] = next_dt.isoformat()
    _auto_timer = threading.Timer(delay_s, _run_auto_gen)
    _auto_timer.daemon = True
    _auto_timer.start()

@app.route("/login", methods=["GET","POST"])
def login():
    err = ""
    if request.method == "POST":
        if request.form.get("pwd") == DASHBOARD_PWD:
            session["ok"] = True
            return redirect("/")
        err = "Mot de passe incorrect"
    return render_template_string(LOGIN, err=err)

@app.route("/logout")
def logout():
    session.clear(); return redirect("/login")

# ── API ───────────────────────────────────────────────────
@app.route("/api/dispo", methods=["GET","POST"])
@auth
def api_dispo():
    s = rj(STATUS_F, {"dispo": True})
    if request.method == "POST":
        s["dispo"] = bool(request.json.get("dispo", True))
        wj(STATUS_F, s)
    return jsonify(s)

@app.route("/api/bot/health")
@auth
def api_bot_health():
    """Vérifie si le bot Telegram répond via l'API."""
    import subprocess as _sp
    # Méthode 1 : vérifier via l'API Telegram (getMe)
    if BOT_TOKEN:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
            d = r.json()
            if d.get("ok"):
                name = d["result"].get("first_name", "Bot")
                return jsonify({"alive": True, "msg": f"@{d['result'].get('username','bot')} en ligne"})
        except Exception:
            pass
    # Méthode 2 : vérifier via pgrep
    try:
        r = _sp.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True)
        pids = [p.strip() for p in r.stdout.strip().splitlines() if p.strip()]
        alive = len(pids) > 0
        return jsonify({"alive": alive, "msg": f"PIDs: {', '.join(pids)}" if alive else "Bot hors ligne"})
    except Exception as e:
        return jsonify({"alive": False, "msg": str(e)})

@app.route("/api/cookie/upload", methods=["POST"])
@auth
def api_cookie_upload():
    """Upload du fichier cookie iCloud."""
    try:
        f = request.files.get("cookie")
        if not f:
            return jsonify({"ok": False, "error": "Aucun fichier reçu"})
        cookie_path = _CODE_DIR / "icloud_gen" / "cookie.txt"
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(cookie_path))
        return jsonify({"ok": True, "msg": "Cookie mis à jour ✅"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/restaurants")
def api_restaurants_public():
    """Endpoint public pour la Mini App Telegram — pas d'auth, CORS ouvert."""
    try:
        r = Path(BASE / "restaurants.json")
        resp = make_response(r.read_bytes())
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    except Exception:
        return jsonify({"restaurants": [], "total": 0}), 200

@app.route("/api/restaurants/count")
@auth
def api_restaurants_count():
    try:
        r = Path(BASE / "restaurants.json")
        d = json.loads(r.read_text())
        return jsonify({"total": d.get("total",0), "last_updated": d.get("last_updated",""),
                        "zones_done": d.get("zones_done"), "zones_total": d.get("zones_total")})
    except Exception:
        return jsonify({"total": 0, "last_updated": ""})

@app.route("/api/stats")
@auth
def api_stats(): return jsonify(stats())

@app.route("/api/orders")
@auth
def api_orders(): return jsonify(rj(ORDERS_F, {}))

@app.route("/api/messages")
@auth
def api_messages(): return jsonify(rj(MESSAGES_F, {}))

@app.route("/api/accounts")
@auth
def api_accounts():
    return jsonify({"accounts": rj(ACCOUNTS_F, []), "quota": icloud_quota()})

@app.route("/api/packs")
@auth
def api_packs():
    """
    Retourne la liste des packs identité :
    1 pack = 1 email iCloud + 1 identité française + 1 adresse Bangkok + SMS attribué.
    Les identités sont générées de façon déterministe (seed = email).
    """
    import sys as _sys
    _sys.path.insert(0, str(BASE))
    try:
        from identity_gen import generate_identity, get_bangkok_address
    except ImportError:
        return jsonify({"ok": False, "msg": "identity_gen non installé", "packs": []})

    accounts = rj(ACCOUNTS_F, [])
    packs = []
    for a in accounts:
        email = a.get("email", "")
        if not email:
            continue
        # Identité déterministe (même résultat à chaque appel)
        try:
            ident   = generate_identity(seed=email)
            addr    = get_bangkok_address(seed=email)
        except Exception:
            ident = {"prenom": "?", "nom": "?", "full_name": "?"}
            addr  = "?"

        packs.append({
            "email":        email,
            "status":       a.get("status", "available"),
            "prenom":       a.get("grab_prenom") or ident.get("prenom", ""),
            "nom":          a.get("grab_nom")    or ident.get("nom", ""),
            "full_name":    a.get("grab_name")   or ident.get("full_name", ""),
            "bangkok_addr": a.get("grab_bangkok_addr") or addr,
            "phone":        a.get("grab_phone", ""),
            "password":     a.get("grab_password", ""),
            "created_at":   a.get("created", ""),
            "grab_created": a.get("grab_created", ""),
            "_locked":      a.get("_locked", False),
            "_fail_count":  a.get("_fail_count", 0),
            "_last_error":  a.get("_last_error", ""),
        })

    # Tri : grab_ready en premier, puis available, puis failed
    order = {"grab_ready": 0, "available": 1, "failed": 3}
    packs.sort(key=lambda p: order.get(p["status"], 2))
    return jsonify({"ok": True, "packs": packs, "total": len(packs)})


@app.route("/api/accounts/update", methods=["POST"])
@auth
def api_accounts_update():
    d = request.json or {}
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == d.get("email"):
            a["status"]      = d.get("status", a["status"])
            a["grab_phone"]  = d.get("grab_phone", a.get("grab_phone",""))
            a["grab_notes"]  = d.get("grab_notes", a.get("grab_notes",""))
            if d.get("status") == "used" and not a.get("used_at"):
                a["used_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            elif d.get("status") == "available":
                a["used_at"] = None
    wj(ACCOUNTS_F, accounts)
    return jsonify({"ok": True})

@app.route("/api/packs/mark_created", methods=["POST"])
@auth
def api_packs_mark_created():
    """Marque un pack comme créé manuellement avec le numéro fourni."""
    d = request.json or {}
    email = (d.get("email") or "").strip()
    phone = (d.get("phone") or "").strip()
    if not email:
        return jsonify({"ok": False, "msg": "email requis"})

    import sys as _sys
    _sys.path.insert(0, str(BASE))
    try:
        from identity_gen import generate_identity, get_bangkok_address
        ident = generate_identity(seed=email)
        addr  = get_bangkok_address(seed=email)
    except Exception:
        ident = {"full_name": "?", "prenom": "?", "nom": "?"}
        addr  = ""

    accounts = rj(ACCOUNTS_F, [])
    found = False
    for a in accounts:
        if a["email"] == email:
            a["status"]            = "grab_ready"
            a["grab_phone"]        = phone
            a["grab_created"]      = datetime.datetime.now().isoformat()
            a["grab_password"]     = "Grab2024lol!"
            a["grab_name"]         = ident.get("full_name", "")
            a["grab_prenom"]       = ident.get("prenom", "")
            a["grab_nom"]          = ident.get("nom", "")
            a["grab_bangkok_addr"] = addr
            a.pop("_locked", None)
            a["_fail_count"]       = 0
            a.pop("_last_error", None)
            found = True
            break
    if not found:
        return jsonify({"ok": False, "msg": "email non trouvé"})
    wj(ACCOUNTS_F, accounts)
    return jsonify({"ok": True})


@app.route("/api/packs/set_phone", methods=["POST"])
@auth
def api_packs_set_phone():
    """Assigne manuellement un numéro de téléphone à un compte."""
    d = request.json or {}
    email = (d.get("email") or "").strip()
    phone = (d.get("phone") or "").strip()
    if not email:
        return jsonify({"ok": False, "msg": "email requis"})
    accounts = rj(ACCOUNTS_F, [])
    found = False
    for a in accounts:
        if a.get("email") == email:
            a["grab_phone"] = phone
            if phone and a.get("status") in ("available", None, ""):
                a["status"] = "full"
            elif not phone and a.get("status") == "full":
                a["status"] = "available"
            found = True
            break
    if not found:
        return jsonify({"ok": False, "msg": "Compte non trouvé"})
    wj(ACCOUNTS_F, accounts)
    return jsonify({"ok": True})


@app.route("/api/packs/reset_failed", methods=["POST"])
@auth
def api_packs_reset_failed():
    """Remet tous les comptes failed en available."""
    accounts = rj(ACCOUNTS_F, [])
    reset = 0
    for a in accounts:
        if a.get("status") == "failed":
            a["status"]      = "available"
            a["_fail_count"] = 0
            a.pop("_last_error", None)
            reset += 1
    wj(ACCOUNTS_F, accounts)
    return jsonify({"ok": True, "reset": reset})


@app.route("/api/generate/status")
@auth
def api_gen_status():
    return jsonify(_gen_status)

@app.route("/api/generate/start", methods=["POST"])
@auth
def api_gen_start():
    if _gen_status["running"]:
        return jsonify({"ok": False, "msg": "Génération déjà en cours"})
    quota = icloud_quota()
    if quota["remaining"] == 0:
        return jsonify({"ok": False, "msg": f"Quota atteint — reset dans {quota['reset']}"})

    count = request.get_json(silent=True) or {}
    n_emails = max(1, min(int(count.get("count", 5)), 25))

    def _run():
        _gen_status["running"] = True
        _gen_status["log"] = f"Lancement du générateur iCloud… ({n_emails} emails)\n"
        try:
            proc = subprocess.Popen(
                ["python3", str(_CODE_DIR / "icloud_gen" / "run.py"), "generate", str(n_emails)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(_CODE_DIR)
            )
            for line in proc.stdout:
                _gen_status["log"] += line
            proc.wait()
            _gen_status["log"] += "\n✅ Terminé"
            _gen_status["last_run"] = datetime.datetime.now().isoformat()
            # Recharge accounts.json si de nouveaux emails ont été générés
            _reload_accounts()
        except Exception as e:
            _gen_status["log"] += f"\n❌ Erreur : {e}"
        finally:
            _gen_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})

def _make_unique_identity(email: str, used_names: set) -> dict:
    """Génère une identité (prenom, nom) unique parmi les comptes existants."""
    try:
        from identity_gen import generate_identity, get_bangkok_address
    except ImportError:
        return {"grab_prenom": "", "grab_nom": "", "grab_name": "", "grab_bangkok_addr": ""}
    suffix = 0
    while True:
        seed = email if suffix == 0 else f"{email}_{suffix}"
        ident = generate_identity(seed=seed)
        key = (ident["prenom"], ident["nom"])
        if key not in used_names:
            used_names.add(key)
            addr = get_bangkok_address(seed=seed)
            return {
                "grab_prenom":      ident["prenom"],
                "grab_nom":         ident["nom"],
                "grab_name":        ident["full_name"],
                "grab_bangkok_addr": addr,
            }
        suffix += 1
        if suffix > 100:
            used_names.add(key)
            addr = get_bangkok_address(seed=seed)
            return {"grab_prenom": ident["prenom"], "grab_nom": ident["nom"], "grab_name": ident["full_name"], "grab_bangkok_addr": addr}


def _reload_accounts():
    """Importe tous les nouveaux emails dans accounts.json.
    Lit emails.txt (généré par cmd_generate) ET emails_export.txt (cmd_list).
    Chaque nouveau compte reçoit immédiatement une identité unique + adresse Bangkok.
    """
    existing = {a["email"]: a for a in rj(ACCOUNTS_F, [])}
    now_ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    added = 0

    # Noms déjà utilisés → garantit l'unicité des nouvelles identités
    used_names = {(a.get("grab_prenom", ""), a.get("grab_nom", "")) for a in existing.values() if a.get("grab_prenom")}

    def _new_account(email, ts):
        entry = {
            "email": email, "created": ts,
            "status": "available", "grab_phone": "",
            "grab_notes": "", "used_at": None,
        }
        entry.update(_make_unique_identity(email, used_names))
        return entry

    # ── 1. emails.txt — format simple, une adresse par ligne ──
    try:
        for line in EMAILS_F.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            email = line.split()[0]
            if "@icloud.com" not in email: continue
            if email not in existing:
                existing[email] = _new_account(email, now_ts)
                added += 1
    except FileNotFoundError:
        pass
    except Exception as e:
        _gen_status["log"] += f"\n⚠ reload emails.txt: {e}"

    # ── 2. emails_export.txt — format avec date, généré par cmd_list ──
    try:
        for line in EXPORT_F.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "@icloud.com" not in line: continue
            email = line.split()[0]
            if email not in existing:
                m = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", line)
                ts = datetime.datetime.strptime(m.group(1), "%d/%m/%Y %H:%M").strftime("%Y-%m-%dT%H:%M:%S") if m else now_ts
                existing[email] = _new_account(email, ts)
                added += 1
    except FileNotFoundError:
        pass
    except Exception as e:
        _gen_status["log"] += f"\n⚠ reload emails_export.txt: {e}"

    wj(ACCOUNTS_F, list(existing.values()))
    if added:
        _gen_status["log"] += f"\n✅ {added} nouveau(x) email(s) ajouté(s) au dashboard"

# ─────────────────────────────────────────────────────────────
#  AUTO-GEN API
# ─────────────────────────────────────────────────────────────

@app.route("/api/autogen/status")
@auth
def api_autogen_status():
    with _auto_lock:
        s = dict(_auto_gen)
    # Signal si cet hôte peut réellement générer (cookie iCloud requis).
    # Sur VPS le cookie n'existe pas → la génération est faite par le Mac LaunchAgent.
    s["can_generate"] = (_CODE_DIR / "icloud_gen" / "cookie.txt").exists()
    return jsonify(s)

@app.route("/api/autogen/toggle", methods=["POST"])
@auth
def api_autogen_toggle():
    global _auto_timer
    d = request.get_json(silent=True) or {}
    enable = d.get("enabled", not _auto_gen["enabled"])
    with _auto_lock:
        _auto_gen["enabled"] = bool(enable)
        if "interval" in d:
            _auto_gen["interval"] = max(10, int(d["interval"]))
        if "count" in d:
            _auto_gen["count"] = max(1, min(int(d["count"]), 5))
    if enable:
        _schedule_next()
    else:
        if _auto_timer:
            _auto_timer.cancel()
            _auto_timer = None
        with _auto_lock:
            _auto_gen["next_run"] = None
    return jsonify({"ok": True, "enabled": _auto_gen["enabled"], "next_run": _auto_gen.get("next_run")})

@app.route("/api/autogen/runnow", methods=["POST"])
@auth
def api_autogen_runnow():
    """Lance une génération immédiate sans attendre le timer."""
    if _gen_status["running"]:
        return jsonify({"ok": False, "msg": "Génération déjà en cours"})
    threading.Thread(target=_run_auto_gen, daemon=True).start()
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
#  GESTION COMMANDES CLIENTS — validation, annulation, timer
# ─────────────────────────────────────────────────────────────

HOURS_F = BASE / "hours.json"   # horaires d'ouverture
_order_timers: dict = {}         # order_id → {"validated_at": ISO, "warned": bool}
_order_timers_lock = threading.Lock()

DEFAULT_HOURS = {"open": "10:00", "close": "22:00", "tz": "Asia/Bangkok", "enabled": True}

def get_hours():
    h = rj(HOURS_F, DEFAULT_HOURS)
    if "open" not in h: h.update(DEFAULT_HOURS)
    return h

def is_open() -> bool:
    """Vérifie si le service est dans les horaires."""
    h = get_hours()
    if not h.get("enabled", True): return True  # pas de restriction
    import pytz
    from datetime import time as dtime
    try:
        tz  = pytz.timezone(h.get("tz", "Asia/Bangkok"))
        now = datetime.datetime.now(tz)
        op  = dtime(*map(int, h["open"].split(":")))
        cl  = dtime(*map(int, h["close"].split(":")))
        return op <= now.time() <= cl
    except: return True

def tg_client(chat_id, text):
    """Envoie un message Telegram à un client."""
    return tg(chat_id, text)

def _start_order_timer(order_id: str, chat_id: int):
    """Lance le timer de sécurité pour une commande validée."""
    import time as _t
    def _watch():
        validated_at = _t.time()
        warned = False
        while True:
            _t.sleep(60)
            elapsed = _t.time() - validated_at
            orders = rj(ORDERS_F, {})
            o = orders.get(order_id, {})
            status = o.get("statut", "")
            if status in ("livre", "annule", "en_cours_livraison"):
                break
            if elapsed > 15*60 and not warned:
                tg_client(chat_id,
                    "⏳ Légère attente sur votre commande, nous revenons vers vous dans quelques minutes.")
                warned = True
                with _order_timers_lock:
                    if order_id in _order_timers:
                        _order_timers[order_id]["warned"] = True
            if elapsed > 30*60:
                # Auto-annulation
                orders = rj(ORDERS_F, {})
                if orders.get(order_id, {}).get("statut") not in ("livre", "annule", "en_cours_livraison"):
                    orders[order_id]["statut"] = "annule"
                    orders[order_id]["annule_at"] = datetime.datetime.now().isoformat()
                    wj(ORDERS_F, orders)
                    tg_client(chat_id,
                        "😔 Nous ne pouvons pas traiter votre commande pour le moment.\n"
                        "Un remboursement vous sera effectué sous 24h. Désolé pour la gêne 🙏")
                break
    t = threading.Thread(target=_watch, daemon=True)
    t.start()

@app.route("/api/orders/<order_id>/validate", methods=["POST"])
@auth
def api_order_validate(order_id):
    """
    Admin valide une commande :
    1. Assigne un compte Grab 'grab_ready' depuis le pool
    2. Envoie message de confirmation au client
    3. Lance le timer de sécurité (15min warn, 30min auto-cancel)
    """
    orders = rj(ORDERS_F, {})
    o = orders.get(order_id)
    if not o:
        return jsonify({"ok": False, "msg": "Commande introuvable"})

    # Assigner compte Grab depuis le pool
    accounts = rj(ACCOUNTS_F, [])
    grab_acc = None
    for acc in accounts:
        if acc.get("status") == "grab_ready":
            grab_acc = acc
            break
    if not grab_acc:
        # Fallback : prendre n'importe quel compte disponible
        for acc in accounts:
            if acc.get("status") in ("available", "phone_assigned"):
                grab_acc = acc
                break

    now_iso = datetime.datetime.now().isoformat()

    # Mettre à jour la commande
    o["statut"]       = "en_cours"
    o["validated_at"] = now_iso
    o["grab_account"] = grab_acc["email"] if grab_acc else None
    orders[order_id]  = o
    wj(ORDERS_F, orders)

    # Marquer le compte comme "in_use"
    if grab_acc:
        for acc in accounts:
            if acc["email"] == grab_acc["email"]:
                acc["status"]    = "in_use"
                acc["in_use_at"] = now_iso
                acc["order_id"]  = order_id
                break
        wj(ACCOUNTS_F, accounts)

    # Message au client
    chat_id  = o.get("chat_id") or o.get("user_id")
    adresse  = o.get("adresse", "votre adresse")
    if chat_id:
        tg_client(int(chat_id),
            f"✅ *Commande confirmée !*\n\n"
            f"👨‍🍳 La cuisine a été prévenue, votre repas est en préparation.\n"
            f"🛵 Un livreur prend en charge votre commande.\n\n"
            f"📍 Livraison à : {adresse}\n"
            f"⏱️ Temps estimé : 30-45 min\n\n"
            f"Je vous envoie le suivi dès que le livreur est en route !"
        )
        # Lancer timer sécurité
        with _order_timers_lock:
            _order_timers[order_id] = {"validated_at": now_iso, "warned": False}
        _start_order_timer(order_id, int(chat_id))

    return jsonify({
        "ok": True,
        "grab_account": grab_acc["email"] if grab_acc else None,
        "msg": "Commande validée"
    })

@app.route("/api/orders/<order_id>/cancel", methods=["POST"])
@auth
def api_order_cancel(order_id):
    """Admin annule une commande → message client."""
    orders = rj(ORDERS_F, {})
    o = orders.get(order_id)
    if not o:
        return jsonify({"ok": False, "msg": "Commande introuvable"})

    reason = (request.get_json(silent=True) or {}).get("reason", "")

    o["statut"]     = "annule"
    o["annule_at"]  = datetime.datetime.now().isoformat()
    o["annule_by"]  = "admin"
    orders[order_id] = o
    wj(ORDERS_F, orders)

    # Libérer le compte Grab si assigné
    if o.get("grab_account"):
        accounts = rj(ACCOUNTS_F, [])
        for acc in accounts:
            if acc["email"] == o["grab_account"]:
                acc["status"]   = "grab_ready"
                acc["in_use_at"] = None
                acc["order_id"]  = None
                break
        wj(ACCOUNTS_F, accounts)

    chat_id = o.get("chat_id") or o.get("user_id")
    if chat_id:
        msg = "😔 Votre commande a été annulée.\nUn remboursement vous sera effectué sous 24h. Désolé 🙏"
        if reason:
            msg = f"😔 Votre commande a été annulée : {reason}\n\nRemboursement sous 24h 🙏"
        tg_client(int(chat_id), msg)

    return jsonify({"ok": True})

@app.route("/api/orders/<order_id>/delivered", methods=["POST"])
@auth
def api_order_delivered(order_id):
    """Admin marque commande comme livrée → message client."""
    orders = rj(ORDERS_F, {})
    o = orders.get(order_id)
    if not o:
        return jsonify({"ok": False, "msg": "Commande introuvable"})

    o["statut"]       = "livre"
    o["delivered_at"] = datetime.datetime.now().isoformat()
    orders[order_id]  = o
    wj(ORDERS_F, orders)

    # Libérer le compte Grab
    if o.get("grab_account"):
        accounts = rj(ACCOUNTS_F, [])
        for acc in accounts:
            if acc["email"] == o["grab_account"]:
                acc["status"]   = "grab_ready"
                acc["in_use_at"] = None
                acc["order_id"]  = None
                break
        wj(ACCOUNTS_F, accounts)

    chat_id = o.get("chat_id") or o.get("user_id")
    if chat_id:
        tg_client(int(chat_id),
            "🎉 *Votre commande est arrivée !*\n\n"
            "Bon appétit ! 🍽️\n"
            "N'hésitez pas à recommander — /order"
        )
    return jsonify({"ok": True})

@app.route("/api/orders/pending")
@auth
def api_orders_pending():
    """Commandes en attente de validation par l'admin."""
    orders = rj(ORDERS_F, {})
    pending = []
    for oid, o in orders.items():
        if o.get("statut") in ("paiement_recu", "en_attente_confirmation", "en_cours"):
            pending.append({"id": oid, **o})
    pending.sort(key=lambda x: x.get("ts",""), reverse=True)
    return jsonify(pending)

@app.route("/api/grab/pool")
@auth
def api_grab_pool():
    """Compte les comptes Grab disponibles dans le pool."""
    accounts = rj(ACCOUNTS_F, [])
    ready  = sum(1 for a in accounts if a.get("status") == "grab_ready")
    in_use = sum(1 for a in accounts if a.get("status") == "in_use")
    total  = len(accounts)
    return jsonify({"ready": ready, "in_use": in_use, "total": total})

@app.route("/api/hours", methods=["GET", "POST"])
@auth
def api_hours():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        h = get_hours()
        h.update({k: v for k, v in d.items() if k in ("open","close","tz","enabled")})
        wj(HOURS_F, h)
        return jsonify({"ok": True, "hours": h})
    return jsonify(get_hours())

@app.route("/api/hours/check")
@auth
def api_hours_check():
    return jsonify({"open": is_open(), "hours": get_hours()})

# ── CONFIG (tarifs) ───────────────────────────────────────────

def get_config():
    """Retourne la config, initialise avec les valeurs par défaut si absente."""
    if not CONFIG_F.exists():
        wj(CONFIG_F, DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    c = rj(CONFIG_F, {})
    if not c.get("budgets"):
        wj(CONFIG_F, DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    return c

@app.route("/api/config", methods=["GET"])
@auth
def api_config_get():
    return jsonify(get_config())

@app.route("/api/config", methods=["POST"])
@auth
def api_config_post():
    d = request.get_json(silent=True) or {}
    c = get_config()
    if "budgets" in d:
        budgets = d["budgets"]
        if not isinstance(budgets, list):
            return jsonify({"ok": False, "msg": "budgets doit être une liste"})
        c["budgets"] = budgets
    wj(CONFIG_F, c)
    return jsonify({"ok": True, "config": c})

# ── BACKUP Telegram ────────────────────────────────────────────

def _backup_to_telegram():
    """Envoie accounts.json et orders.json en DM à l'admin Telegram."""
    if not BOT_TOKEN or not ADMIN_ID:
        return False
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    results = []
    for fpath, label in [(ACCOUNTS_F, "accounts"), (ORDERS_F, "orders")]:
        try:
            data = rj(fpath, {})
            count = len(data) if isinstance(data, (list, dict)) else "?"
            caption = f"💾 Backup {label} — {now} — {count} entrées"
            with open(fpath, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                    data={"chat_id": ADMIN_ID, "caption": caption},
                    files={"document": (fpath.name, f, "application/json")},
                    timeout=20
                )
            results.append(r.json().get("ok", False))
        except Exception as e:
            results.append(False)
    return all(results)

def _backup_scheduler_thread():
    """Thread qui envoie un backup tous les jours à 03:00 Bangkok (UTC+7)."""
    import time as _time
    while True:
        try:
            import pytz
            tz = pytz.timezone("Asia/Bangkok")
            now = datetime.datetime.now(tz)
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            secs = (target - now).total_seconds()
        except Exception:
            secs = 86400  # fallback 24h si pytz absent
        _time.sleep(secs)
        try:
            _backup_to_telegram()
        except Exception:
            pass

_backup_thread = threading.Thread(target=_backup_scheduler_thread, daemon=True)
_backup_thread.start()

@app.route("/api/backup", methods=["POST"])
@auth
def api_backup():
    """Déclenche un backup manuel vers Telegram."""
    def _run():
        _backup_to_telegram()
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "Backup lancé vers Telegram"})

# ── HEALTH ────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Endpoint de monitoring sans auth — retourne ok + timestamp."""
    return jsonify({"ok": True, "ts": datetime.datetime.utcnow().isoformat() + "Z"})

# ─────────────────────────────────────────────────────────────
#  GRAB ACCOUNT CREATION PIPELINE
# ─────────────────────────────────────────────────────────────

_grab_pipeline_status = {"running": False, "log": "", "last_result": None}

@app.route("/api/grabgen/run", methods=["POST"])
@auth
def api_grabgen_run():
    if _grab_pipeline_status["running"]:
        return jsonify({"ok": False, "msg": "Pipeline déjà en cours"})
    d = request.get_json(silent=True) or {}
    onoff_email  = d.get("onoff_email", "")
    onoff_pass   = d.get("onoff_pass", "")
    phone        = d.get("phone", "")
    icloud_email = d.get("icloud_email", "")
    channel      = d.get("channel", "sms")

    if not all([onoff_email, onoff_pass, phone]):
        return jsonify({"ok": False, "msg": "onoff_email, onoff_pass et phone requis"})

    def _run():
        import asyncio as _aio
        _grab_pipeline_status["running"] = True
        _grab_pipeline_status["log"]     = "🚀 Pipeline démarré…\n"
        try:
            sys.path.insert(0, str(BASE))
            from grab_gen.pipeline import run_pipeline
            result = _aio.run(run_pipeline(
                onoff_email  = onoff_email,
                onoff_pass   = onoff_pass,
                phone_number = phone,
                icloud_email = icloud_email,
                headless     = True,
                otp_channel  = channel,
            ))
            if result:
                _grab_pipeline_status["log"]        += f"\n✅ Compte créé !\n📧 {result['icloud_email']}\n🔑 {result['password']}"
                _grab_pipeline_status["last_result"] = result
                _reload_accounts()
            else:
                _grab_pipeline_status["log"] += "\n❌ Pipeline échoué — voir screenshots /tmp/grab_*.png"
        except Exception as e:
            _grab_pipeline_status["log"] += f"\n❌ Erreur : {e}"
        finally:
            _grab_pipeline_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/grabgen/status")
@auth
def api_grabgen_status():
    return jsonify(_grab_pipeline_status)

# ── Orchestrateur permanent ────────────────────────────────
_orch_thread = None

@app.route("/api/orch/start", methods=["POST"])
@auth
def api_orch_start():
    global _orch_thread
    from grab_gen.orchestrator import start_background, get_state
    s = get_state()
    if s.get("running"):
        return jsonify({"ok": False, "msg": "Deja en cours"})
    _orch_thread = start_background()
    return jsonify({"ok": True})

@app.route("/api/orch/stop", methods=["POST"])
@auth
def api_orch_stop():
    from grab_gen.orchestrator import stop
    stop()
    return jsonify({"ok": True})

@app.route("/api/orch/status")
@auth
def api_orch_status():
    try:
        from grab_gen.orchestrator import get_state
        return jsonify(get_state())
    except Exception as e:
        return jsonify({"running": False, "error": str(e)})

@app.route("/api/orch/devices")
@auth
def api_orch_devices():
    try:
        from grab_gen.orchestrator import get_adb_devices
        return jsonify({"devices": get_adb_devices()})
    except ImportError:
        return jsonify({"devices": [], "error": "grab_gen non disponible sur ce serveur"})

@app.route("/api/grabgen/config", methods=["GET", "POST"])
@auth
def api_grabgen_config():
    """Sauvegarde les credentials OnOff dans .env."""
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        env_path = BASE / ".env"
        try:
            lines = env_path.read_text().splitlines() if env_path.exists() else []
            for key in ["ONOFF_EMAIL", "ONOFF_PASS"]:
                val = d.get(key.lower().replace("onoff_", "onoff_"), "")
                if val:
                    lines = [l for l in lines if not l.startswith(f"{key}=")]
                    lines.append(f"{key}={val}")
            env_path.write_text("\n".join(lines) + "\n")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})
    return jsonify({
        "onoff_email": os.environ.get("ONOFF_EMAIL", ""),
        "configured":  bool(os.environ.get("ONOFF_EMAIL")),
    })

@app.route("/api/grabgen/explore", methods=["POST"])
@auth
def api_grabgen_explore():
    """Lance l'exploration de l'interface Grab signup (calibrage sélecteurs)."""
    def _explore():
        import asyncio as _aio, sys as _sys
        _sys.path.insert(0, str(BASE))
        from grab_gen.grab_reg import GrabRegistration
        async def _run():
            async with GrabRegistration(headless=True) as gr:
                return await gr.explore_signup()
        return _aio.run(_run())
    try:
        result = _explore()
        return jsonify({"ok": True, "data": result})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/reply", methods=["POST"])
@auth
def api_reply():
    d = request.json or {}
    uid, text = int(d.get("user_id",0)), d.get("text","").strip()
    if not uid or not text: return jsonify({"ok":False})
    ok = tg(uid, f"╔═══════════════════════╗\n║   💬  SERVICE CLIENT   ║\n╚═══════════════════════╝\n\n{text}\n\n_Répondre : /tchat votre message_")
    if ok:
        msgs = rj(MESSAGES_F, {})
        k = str(uid)
        if k in msgs:
            msgs[k]["messages"].append({"text":text,"ts":datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),"heure":datetime.datetime.now().strftime("%d/%m à %H:%M"),"from":"admin","read":True})
            msgs[k]["unread"] = 0
            wj(MESSAGES_F, msgs)
    return jsonify({"ok":ok})

@app.route("/api/mark_read", methods=["POST"])
@auth
def api_mark_read():
    uid = str(request.json.get("user_id",""))
    msgs = rj(MESSAGES_F, {})
    if uid in msgs:
        msgs[uid]["unread"] = 0
        for m in msgs[uid]["messages"]: m["read"] = True
        wj(MESSAGES_F, msgs)
    return jsonify({"ok":True})

@app.route("/api/order/status", methods=["POST"])
@auth
def api_order_status():
    d = request.json or {}
    oid, s = d.get("order_id",""), d.get("statut","")
    orders = rj(ORDERS_F, {})
    if oid not in orders: return jsonify({"ok":False,"err":"introuvable"})
    orders[oid]["statut"] = s
    wj(ORDERS_F, orders)
    cid = orders[oid].get("chat_id")
    if s == "en_cours" and cid:
        tg(cid, f"🛵 *Commande en cours !*\n🆔 `{oid}` — suivi dans quelques minutes 🙏")
    elif s == "livre" and cid:
        tg(cid, f"✅ *Livré !* Bon appétit {orders[oid].get('nom','')} 🍽️\nMerci d'avoir choisi GrabDiscount 🛵")
    return jsonify({"ok":True})

@app.route("/api/order/tracking", methods=["POST"])
@auth
def api_order_tracking():
    d = request.json or {}
    oid, lien = d.get("order_id",""), d.get("lien","").strip()
    orders = rj(ORDERS_F, {})
    cmd = orders.get(oid)
    if not cmd or not lien: return jsonify({"ok":False})
    ok = tg(cmd["chat_id"], f"╔═══════════════════════╗\n║   📍  SUIVI COMMANDE  ║\n╚═══════════════════════╝\n\nEn route ! 🛵\n\n🆔 `{oid}`\n📍 {cmd.get('adresse','?')}\n\n👇 *Suivre ici :*\n{lien}\n\n⏰ 30–45 min · Bon appétit ! 🍽️")
    if ok:
        orders[oid]["statut"] = "en_cours"
        wj(ORDERS_F, orders)
    return jsonify({"ok":ok})

# ─────────────────────────────────────────────────────────────
#  ICLOUD MAIL READER
# ─────────────────────────────────────────────────────────────

def _read_icloud_mails(hme_address: str, max_count: int = 10) -> list:
    """
    Lit les derniers mails reçus sur une adresse Hide My Email iCloud.
    Utilise le cookie iCloud existant dans icloud_gen/cookie.txt
    """
    cookie_path = _CODE_DIR / "icloud_gen" / "cookie.txt"
    try:
        cookie_txt = cookie_path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"error": f"Cookie introuvable : {e}"}]

    # Parse cookie.txt → dict
    cookies: dict = {}
    for line in cookie_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        for part in line.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()

    if not cookies:
        return [{"error": "Cookie vide ou invalide"}]

    # Construire la string Cookie pour HTTP
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

    try:
        # Découvrir les endpoints iCloud mail disponibles
        headers = {
            "Cookie": cookie_str,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://www.icloud.com",
            "Referer": "https://www.icloud.com/",
        }

        # Essayer l'API mail iCloud
        urls_to_try = [
            "https://p66-mailws.icloud.com/wm/mbox",
            "https://p65-mailws.icloud.com/wm/mbox",
            "https://p64-mailws.icloud.com/wm/mbox",
            "https://p63-mailws.icloud.com/wm/mbox",
        ]

        # D'abord, chercher le bon endpoint depuis le cookie (dsid)
        dsid = cookies.get("dsid") or cookies.get("X-Apple-ID-Session-Id") or ""
        apple_id_token = cookies.get("X-Apple-Web-Auth-Token") or cookies.get("x-apple-web-auth-token") or ""

        # Tenter de récupérer les infos de compte pour trouver le bon mailws
        try:
            setup_r = requests.get(
                "https://setup.icloud.com/setup/ws/1/accountLogin",
                headers={**headers, "Content-Type": "application/json"},
                timeout=8,
            )
            if setup_r.status_code == 200:
                sdata = setup_r.json()
                mail_url = sdata.get("webservices", {}).get("mail", {}).get("url", "")
                if mail_url:
                    urls_to_try = [mail_url + "/wm/mbox"] + urls_to_try
        except Exception:
            pass

        mails = []
        last_error = None
        for base_url in urls_to_try:
            try:
                # Récupérer la liste des messages dans INBOX
                list_r = requests.get(
                    base_url,
                    params={"limit": max_count * 2, "offset": 0},
                    headers={**headers, "Content-Type": "application/json"},
                    timeout=10,
                )
                if list_r.status_code in (401, 403):
                    last_error = "Cookie expiré (401/403)"
                    continue
                if list_r.status_code != 200:
                    last_error = f"HTTP {list_r.status_code}"
                    continue

                data = list_r.json()
                messages = data.get("messages", []) or data.get("items", []) or []
                if not messages:
                    # Essayer format différent
                    messages = data if isinstance(data, list) else []

                for msg in messages[:max_count * 2]:
                    to_field = msg.get("to", []) or []
                    if isinstance(to_field, str):
                        to_field = [to_field]
                    to_emails = [t.get("email", t) if isinstance(t, dict) else t for t in to_field]
                    # Vérifier si ce message concerne notre adresse HME (ou inclure tout)
                    subject = msg.get("subject", "") or ""
                    from_field = msg.get("from", {}) or {}
                    from_email = from_field.get("email", "") if isinstance(from_field, dict) else str(from_field)
                    from_name = from_field.get("name", "") if isinstance(from_field, dict) else ""
                    date_str = msg.get("date", "") or msg.get("received", "") or ""
                    body = msg.get("preview", "") or msg.get("body", "") or ""

                    s_lower = subject.lower() + body.lower() + from_email.lower()
                    is_grab = any(kw in s_lower for kw in ["grab", "verification", "verify", "code", "otp"])

                    mails.append({
                        "from": f"{from_name} <{from_email}>" if from_name else from_email,
                        "to": ", ".join(to_emails),
                        "subject": subject,
                        "date": date_str,
                        "preview": body[:200] if body else "",
                        "is_grab": is_grab,
                    })
                if mails:
                    break
            except requests.Timeout:
                last_error = "Timeout"
                continue
            except Exception as ex:
                last_error = str(ex)
                continue

        if not mails and last_error:
            return [{"error": last_error or "Impossible de lire les mails (cookie peut-être expiré)"}]
        return mails[:max_count]

    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────────────────────
#  ESPACE EMPLOYÉ — ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/employe/diag")
def employe_diag():
    """Page de diagnostic — montre les cookies reçus par le serveur."""
    tok = request.cookies.get("emp_tok", "")
    ok = tok == _EMP_TOKEN
    return f"""<html><body style="font-family:monospace;padding:20px;background:#111;color:#eee">
    <h2>🔍 Diagnostic employé</h2>
    <p>Cookie emp_tok reçu : <b style="color:{'#0f0' if tok else '#f44'}">{tok[:20]+'...' if tok else 'AUCUN'}</b></p>
    <p>Token attendu (début) : <b style="color:#aaa">{_EMP_TOKEN[:20]}...</b></p>
    <p>Cookie valide : <b style="color:{'#0f0' if ok else '#f44'}">{'✅ OUI' if ok else '❌ NON'}</b></p>
    <p>Tous les cookies reçus : <code>{dict(request.cookies)}</code></p>
    <br><a href="/employe/login" style="color:#3bf">→ Aller au login</a>
    &nbsp;&nbsp;<a href="/employe" style="color:#3bf">→ Aller à /employe</a>
    </body></html>"""

@app.route("/employe", methods=["GET"])
def employe_page():
    if request.cookies.get("emp_tok") != _EMP_TOKEN:
        return redirect("/employe/login")

    import sys as _sys
    _sys.path.insert(0, str(_CODE_DIR))
    try:
        from identity_gen import generate_identity, get_bangkok_address
    except ImportError:
        generate_identity = None
        get_bangkok_address = None

    employe_id = _get_employe_id()
    accounts_raw = rj(ACCOUNTS_F, [])
    accounts = []
    for a in accounts_raw:
        status = a.get("status", "available")
        claimed_by = a.get("claimed_by")
        no_phone = not a.get("grab_phone", "").strip()
        if status in ("available", "full", None, "") and not claimed_by and no_phone:
            pass
        elif claimed_by == employe_id:
            pass
        else:
            continue
        email = a.get("email", "")
        if not email:
            continue
        try:
            ident = generate_identity(seed=email) if generate_identity else {}
            addr  = get_bangkok_address(seed=email) if get_bangkok_address else ""
        except Exception:
            ident = {"prenom": "?", "nom": "?", "full_name": "?"}
            addr  = ""
        accounts.append({
            "email":       email,
            "status":      status,
            "claimed_by":  claimed_by,
            "claimed_at":  a.get("claimed_at"),
            "full_name":   a.get("grab_name") or ident.get("full_name", ""),
            "bangkok_addr":a.get("grab_bangkok_addr") or addr,
            "phone":       a.get("grab_phone", ""),
        })

    accounts_json = json.dumps(accounts, ensure_ascii=False)
    return render_template_string(EMPLOYE_PAGE, accounts=accounts, accounts_json=accounts_json)

@app.route("/employe/login", methods=["GET"])
def employe_login_page():
    return render_template_string(EMPLOYE_LOGIN)

@app.route("/employe/login", methods=["POST"])
def employe_login():
    pwd = request.form.get("pwd", "")
    if pwd == EMPLOYEE_PWD:
        resp = make_response(jsonify({"ok": True}))
        # Cookie persistant 7 jours, même sur HTTP
        resp.set_cookie("emp_tok", _EMP_TOKEN, max_age=7*24*3600, path="/", samesite="Lax", httponly=False)
        return resp
    return jsonify({"ok": False, "error": "Mot de passe incorrect"})

@app.route("/employe/logout")
def employe_logout():
    session.clear()
    resp = make_response(redirect("/employe/login"))
    resp.set_cookie("emp_tok", "", max_age=0, path="/")
    return resp

@app.route("/api/employe/accounts")
@emp_auth
def api_employe_accounts():
    """Retourne les comptes disponibles + ceux pris en charge par cet employé."""
    import sys as _sys
    _sys.path.insert(0, str(_CODE_DIR))
    try:
        from identity_gen import generate_identity, get_bangkok_address
    except ImportError:
        generate_identity = None
        get_bangkok_address = None

    employe_id = _get_employe_id()
    accounts = rj(ACCOUNTS_F, [])
    result = []
    for a in accounts:
        status = a.get("status", "available")
        claimed_by = a.get("claimed_by")
        # Montrer : disponibles (sans numéro) + ceux pris en charge par cet employé
        no_phone = not a.get("grab_phone", "").strip()
        if status in ("available", "full", None, "") and not claimed_by and no_phone:
            pass  # inclure
        elif claimed_by == employe_id:
            pass  # inclure
        else:
            continue

        email = a.get("email", "")
        if not email:
            continue

        try:
            ident = generate_identity(seed=email) if generate_identity else {}
            addr = get_bangkok_address(seed=email) if get_bangkok_address else ""
        except Exception:
            ident = {"prenom": "?", "nom": "?", "full_name": "?"}
            addr = ""

        result.append({
            "email": email,
            "status": status,
            "claimed_by": claimed_by,
            "claimed_at": a.get("claimed_at"),
            "prenom": a.get("grab_prenom") or ident.get("prenom", ""),
            "nom": a.get("grab_nom") or ident.get("nom", ""),
            "full_name": a.get("grab_name") or ident.get("full_name", ""),
            "bangkok_addr": a.get("grab_bangkok_addr") or addr,
            "password": "Grab2024lol!",
            "phone": a.get("grab_phone", ""),
            "created_at": a.get("created", ""),
        })
    return jsonify({"ok": True, "accounts": result})

@app.route("/api/employe/claim", methods=["POST"])
@emp_auth
def api_employe_claim():
    """Verrouille un compte pour cet employé."""
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email requis"})
    employe_id = _get_employe_id()
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a.get("email") == email:
            if a.get("claimed_by") and a.get("claimed_by") != employe_id:
                return jsonify({"ok": False, "error": "Compte déjà pris en charge par un autre employé"})
            a["claimed_by"] = employe_id
            a["claimed_at"] = datetime.datetime.now().isoformat()
            a["status"] = "claimed"
            wj(ACCOUNTS_F, accounts)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Compte non trouvé"})

@app.route("/api/employe/unclaim", methods=["POST"])
@emp_auth
def api_employe_unclaim():
    """Libère un compte verrouillé par cet employé."""
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email requis"})
    employe_id = _get_employe_id()
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a.get("email") == email:
            if a.get("claimed_by") != employe_id:
                return jsonify({"ok": False, "error": "Ce compte n'est pas le vôtre"})
            a["claimed_by"] = None
            a["claimed_at"] = None
            a["status"] = "available"
            wj(ACCOUNTS_F, accounts)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Compte non trouvé"})

@app.route("/api/employe/set_phone", methods=["POST"])
@emp_auth
def api_employe_set_phone():
    """Enregistre un numéro de téléphone pour un compte pris en charge."""
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip()
    phone = (d.get("phone") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email requis"})
    employe_id = _get_employe_id()
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a.get("email") == email:
            if a.get("claimed_by") != employe_id:
                return jsonify({"ok": False, "error": "Ce compte n'est pas le vôtre"})
            a["grab_phone"] = phone
            wj(ACCOUNTS_F, accounts)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Compte non trouvé"})

@app.route("/api/employe/validate", methods=["POST"])
@emp_auth
def api_employe_validate():
    """Valide un compte comme 'full' une fois le numéro entré et le compte créé."""
    import sys as _sys
    _sys.path.insert(0, str(_CODE_DIR))
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip()
    if not email:
        return jsonify({"ok": False, "error": "email requis"})
    employe_id = _get_employe_id()

    try:
        from identity_gen import generate_identity, get_bangkok_address
        ident = generate_identity(seed=email)
        addr = get_bangkok_address(seed=email)
    except Exception:
        ident = {"full_name": "?", "prenom": "?", "nom": "?"}
        addr = ""

    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a.get("email") == email:
            if a.get("claimed_by") != employe_id:
                return jsonify({"ok": False, "error": "Ce compte n'est pas le vôtre"})
            if not a.get("grab_phone"):
                return jsonify({"ok": False, "error": "Numéro de téléphone manquant"})
            a["status"] = "grab_ready"
            a["claimed_by"] = None
            a["claimed_at"] = None
            a["grab_created"] = datetime.datetime.now().isoformat()
            a["grab_password"] = "Grab2024lol!"
            a["grab_name"] = ident.get("full_name", "")
            a["grab_prenom"] = ident.get("prenom", "")
            a["grab_nom"] = ident.get("nom", "")
            a["grab_bangkok_addr"] = addr
            a["validated_by_employee"] = employe_id
            wj(ACCOUNTS_F, accounts)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Compte non trouvé"})

@app.route("/api/employe/mails/<path:email_address>")
@emp_auth
def api_employe_mails(email_address):
    """Lit les derniers mails iCloud pour l'adresse donnée."""
    employe_id = _get_employe_id()
    # Vérifier que cet employé a bien ce compte en charge
    accounts = rj(ACCOUNTS_F, [])
    acc = next((a for a in accounts if a.get("email") == email_address), None)
    if not acc:
        return jsonify({"ok": False, "error": "Compte non trouvé", "mails": []})
    if acc.get("claimed_by") != employe_id:
        return jsonify({"ok": False, "error": "Accès refusé", "mails": []})
    mails = _read_icloud_mails(email_address, max_count=10)
    # Si la liste contient un dict avec une clé "error", c'est une erreur
    if mails and "error" in mails[0]:
        return jsonify({"ok": False, "error": mails[0]["error"], "mails": []})
    return jsonify({"ok": True, "mails": mails})


# ── MAIN PAGE ─────────────────────────────────────────────
@app.route("/")
@auth
def index(): return render_template_string(DASH)

# ══════════════════════════════════════════════════════════
#  HTML
# ══════════════════════════════════════════════════════════
LOGIN = """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GrabDiscount</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
body{background:#080b12;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.box{background:#111827;border:1px solid #1f2937;border-radius:20px;padding:48px 40px;width:380px;text-align:center}
.logo{font-size:3.5rem;margin-bottom:20px}h1{color:#fff;font-size:1.5rem;font-weight:700;margin-bottom:6px}
.sub{color:#6b7280;font-size:.875rem;margin-bottom:36px}
input{width:100%;background:#0d1117;border:1px solid #1f2937;border-radius:12px;padding:15px 18px;color:#fff;font-size:1rem;outline:none;margin-bottom:14px;transition:.2s}
input:focus{border-color:#00b14f;box-shadow:0 0 0 3px #00b14f15}
button{width:100%;background:#00b14f;border:none;border-radius:12px;padding:15px;color:#fff;font-size:1rem;font-weight:700;cursor:pointer;transition:.2s}
button:hover{background:#009940;transform:translateY(-1px)}
.err{color:#f87171;font-size:.85rem;margin-bottom:14px;background:#7f1d1d22;border:1px solid #7f1d1d;border-radius:8px;padding:10px}
</style></head><body>
<div class="box"><div class="logo">🛵</div><h1>GrabDiscount</h1><div class="sub">Tableau de bord admin</div>
{% if err %}<div class="err">{{ err }}</div>{% endif %}
<form method="POST"><input type="password" name="pwd" placeholder="Mot de passe" autofocus><button>Accéder au QG →</button></form>
</div></body></html>"""

DASH = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GrabDiscount QG</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#080b12;--s1:#0d1117;--s2:#111827;--s3:#1f2937;--s4:#374151;
  --t1:#f9fafb;--t2:#9ca3af;--t3:#6b7280;--green:#00b14f;--blue:#3b82f6;
  --orange:#f59e0b;--red:#ef4444;--purple:#8b5cf6;--cyan:#06b6d4}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--t1);display:flex}

/* SIDEBAR */
.sidebar{width:220px;min-width:220px;background:var(--s1);border-right:1px solid var(--s3);
  display:flex;flex-direction:column;height:100vh;padding:20px 12px}
.brand{display:flex;align-items:center;gap:10px;padding:4px 12px 24px;border-bottom:1px solid var(--s3);margin-bottom:16px}
.brand-logo{font-size:1.6rem}
.brand-name{font-size:1rem;font-weight:800;color:var(--t1)}
.brand-sub{font-size:.65rem;color:var(--t3);margin-top:1px}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;
  cursor:pointer;font-size:.875rem;color:var(--t2);transition:.15s;margin-bottom:2px;border:none;background:none;width:100%;text-align:left}
.nav-item:hover{background:var(--s2);color:var(--t1)}
.nav-item.active{background:var(--green)15;color:var(--green);font-weight:600}
.nav-icon{font-size:1.1rem;width:24px;text-align:center}
.nav-badge{margin-left:auto;background:var(--red);color:#fff;border-radius:99px;
  font-size:.65rem;padding:2px 7px;font-weight:700}
.sidebar-spacer{flex:1}
.sidebar-bottom{border-top:1px solid var(--s3);padding-top:16px;margin-top:8px}
.dispo-toggle{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:10px;
  background:var(--s2);cursor:pointer;margin-bottom:8px;font-size:.8rem;color:var(--t2)}
.dispo-dot{width:8px;height:8px;border-radius:50%;background:var(--green);flex-shrink:0;transition:.3s}
.dispo-dot.pause{background:var(--orange)}
.btn-logout{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:10px;
  font-size:.8rem;color:var(--t3);cursor:pointer;text-decoration:none;transition:.15s}
.btn-logout:hover{color:var(--red);background:#ef444410}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;height:100vh;overflow:hidden;min-width:0}
.topbar{padding:16px 24px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:12px;flex-shrink:0}
.page-title{font-size:1.1rem;font-weight:700;color:var(--t1)}
.page-sub{font-size:.8rem;color:var(--t3);margin-left:auto}
.content{flex:1;overflow-y:auto;overflow-x:hidden;padding:24px}

/* CARDS */
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.card{background:var(--s2);border:1px solid var(--s3);border-radius:14px;padding:20px}
.card-sm{background:var(--s2);border:1px solid var(--s3);border-radius:14px;padding:16px}
.kpi-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--t3);margin-bottom:8px}
.kpi-val{font-size:2rem;font-weight:800;line-height:1}
.kpi-sub{font-size:.75rem;color:var(--t3);margin-top:6px}
.c-green{color:var(--green)} .c-blue{color:var(--blue)} .c-orange{color:var(--orange)}
.c-red{color:var(--red)} .c-purple{color:var(--purple)} .c-cyan{color:var(--cyan)}

/* TABLE */
.table-wrap{background:var(--s2);border:1px solid var(--s3);border-radius:14px;overflow:hidden}
.table-wrap table{display:block;max-height:520px;overflow-y:auto}
.table-header{padding:16px 20px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:12px}
.table-title{font-size:.9rem;font-weight:700}
table{width:100%;border-collapse:collapse}
th{font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);
   padding:11px 16px;text-align:left;border-bottom:1px solid var(--s3);background:var(--s1)}
td{padding:13px 16px;border-bottom:1px solid #0d111780;font-size:.85rem;color:var(--t2)}
tr:last-child td{border:none}
tr:hover td{background:var(--s3)30;cursor:pointer}
.mono{font-family:monospace;font-size:.8rem}

/* PILLS */
.pill{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:99px;font-size:.72rem;font-weight:600;white-space:nowrap}
.pill-green{background:#00b14f18;color:var(--green)}
.pill-blue{background:#3b82f618;color:var(--blue)}
.pill-orange{background:#f59e0b18;color:var(--orange)}
.pill-red{background:#ef444418;color:var(--red)}
.pill-purple{background:#8b5cf618;color:var(--purple)}
.pill-gray{background:var(--s3);color:var(--t3)}
.pill-cyan{background:#06b6d418;color:var(--cyan)}

/* BUTTONS */
.btn{padding:8px 16px;border-radius:8px;border:none;font-size:.82rem;font-weight:600;cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:6px}
.btn:hover{filter:brightness(1.1);transform:translateY(-1px)}
.btn-primary{background:var(--green);color:#fff}
.btn-secondary{background:var(--s3);color:var(--t1)}
.btn-blue{background:var(--blue);color:#fff}
.btn-danger{background:#ef444420;color:var(--red);border:1px solid #ef444430}
.btn-sm{padding:5px 12px;font-size:.75rem}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none}

/* INPUT */
.input{background:var(--s1);border:1px solid var(--s3);border-radius:8px;padding:9px 13px;
  color:var(--t1);font-size:.85rem;outline:none;transition:.2s}
.input:focus{border-color:var(--green);box-shadow:0 0 0 3px #00b14f12}
.input::placeholder{color:var(--t3)}
.select{background:var(--s1);border:1px solid var(--s3);border-radius:8px;padding:9px 13px;
  color:var(--t1);font-size:.85rem;outline:none;cursor:pointer}

/* FILTERS */
.filter-bar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
.filter-pill{padding:6px 14px;border-radius:99px;font-size:.8rem;cursor:pointer;border:1px solid var(--s3);background:var(--s2);color:var(--t2);transition:.15s}
.filter-pill:hover,.filter-pill.active{background:var(--green);color:#fff;border-color:var(--green)}

/* CHAT */
.chat-layout{display:grid;grid-template-columns:300px 1fr;height:100%;overflow:hidden}
.conv-list{border-right:1px solid var(--s3);overflow-y:auto;background:var(--s1)}
.conv-item{padding:14px 16px;cursor:pointer;border-bottom:1px solid var(--s3)50;
  display:flex;gap:10px;align-items:center;transition:.1s}
.conv-item:hover,.conv-item.active{background:var(--s2)}
.conv-item.active{border-left:3px solid var(--green)}
.avatar{width:38px;height:38px;border-radius:50%;background:var(--s3);display:flex;align-items:center;
  justify-content:center;font-weight:700;font-size:.9rem;flex-shrink:0}
.conv-name{font-size:.875rem;font-weight:600;color:var(--t1)}
.conv-prev{font-size:.75rem;color:var(--t3);margin-top:2px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:180px}
.unread-badge{margin-left:auto;background:var(--blue);color:#fff;border-radius:99px;font-size:.65rem;padding:2px 7px;font-weight:700;flex-shrink:0}
.chat-window{display:flex;flex-direction:column;height:100%}
.chat-header{padding:16px 20px;border-bottom:1px solid var(--s3);flex-shrink:0;display:flex;align-items:center;gap:12px}
.chat-msgs{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:10px}
.msg-bubble{max-width:72%;padding:10px 14px;border-radius:14px;font-size:.875rem;line-height:1.5}
.msg-client{background:var(--s2);align-self:flex-start;border-bottom-left-radius:4px}
.msg-admin{background:#00b14f20;border:1px solid #00b14f35;align-self:flex-end;border-bottom-right-radius:4px;color:#d1fae5}
.msg-time{font-size:.68rem;color:var(--t3);margin-top:4px}
.chat-input-row{padding:14px 16px;border-top:1px solid var(--s3);display:flex;gap:8px;flex-shrink:0}
.chat-textarea{flex:1;background:var(--s1);border:1px solid var(--s3);border-radius:12px;
  padding:11px 14px;color:var(--t1);font-size:.875rem;outline:none;resize:none;font-family:inherit}
.chat-textarea:focus{border-color:var(--blue)}
.send-btn{background:var(--blue);border:none;border-radius:12px;padding:11px 18px;color:#fff;cursor:pointer;font-size:1.1rem}
.send-btn:hover{background:#2563eb}

/* ACCOUNTS */
.quota-card{background:var(--s2);border:1px solid var(--s3);border-radius:14px;padding:24px;margin-bottom:16px}
.quota-bar-bg{background:var(--s3);border-radius:99px;height:8px;margin:12px 0}
.quota-bar-fill{background:var(--green);border-radius:99px;height:8px;transition:.5s}
.quota-bar-fill.warn{background:var(--orange)}
.quota-bar-fill.full{background:var(--red)}

/* SLIDE PANEL */
.slide-overlay{position:fixed;inset:0;background:#00000080;z-index:200;opacity:0;pointer-events:none;transition:.2s}
.slide-overlay.open{opacity:1;pointer-events:all}
.slide-panel{position:fixed;right:0;top:0;bottom:0;width:440px;background:var(--s1);
  border-left:1px solid var(--s3);z-index:201;transform:translateX(100%);transition:.25s;overflow-y:auto}
.slide-panel.open{transform:translateX(0)}
.slide-header{padding:20px 24px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:12px}
.slide-body{padding:24px}
.slide-section{background:var(--s2);border-radius:12px;padding:16px;margin-bottom:14px}
.slide-section h4{font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);margin-bottom:12px}
.detail-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--s3)60;font-size:.85rem}
.detail-row:last-child{border:none}
.detail-key{color:var(--t3)}
.detail-val{color:var(--t1);font-weight:500;text-align:right;max-width:240px}

/* TOAST */
.toast-wrap{position:fixed;bottom:24px;right:24px;z-index:999;display:flex;flex-direction:column;gap:8px}
.toast{background:var(--s2);border:1px solid var(--s3);border-radius:12px;padding:13px 20px;
  font-size:.85rem;min-width:220px;transform:translateX(120%);transition:.3s;box-shadow:0 8px 24px #00000060}
.toast.show{transform:translateX(0)}
.toast.ok{border-color:var(--green)60;color:var(--green)}
.toast.err{border-color:var(--red)60;color:var(--red)}

/* EMPTY */
.empty{text-align:center;padding:60px 24px;color:var(--t3)}
.empty-icon{font-size:2.5rem;margin-bottom:12px}

/* GEN MODAL */
.modal-overlay{position:fixed;inset:0;background:#00000090;z-index:300;display:none;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--s2);border:1px solid var(--s3);border-radius:18px;padding:28px;width:520px;max-width:95vw}
.modal h2{font-size:1.1rem;font-weight:700;margin-bottom:4px}
.modal .sub{font-size:.8rem;color:var(--t3);margin-bottom:20px}
.gen-log{background:var(--s1);border-radius:10px;padding:14px;font-family:monospace;font-size:.78rem;
  color:#86efac;min-height:120px;max-height:200px;overflow-y:auto;white-space:pre-wrap;margin-bottom:16px}
.modal-actions{display:flex;gap:8px;justify-content:flex-end}

/* SCROLLBAR */
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--s3);border-radius:4px}

/* ── MOBILE ─────────────────────────────────────────────── */
@media(max-width:768px){
  html,body{overflow:auto}
  .app{flex-direction:column}
  .sidebar{display:none}
  .main{height:auto;overflow:visible;padding-bottom:70px}
  .content{overflow:visible;padding:12px}
  .grid-4{grid-template-columns:1fr 1fr!important}
  .grid-2{grid-template-columns:1fr!important}
  .stat-grid{grid-template-columns:1fr 1fr!important}
  .table-wrap{overflow-x:auto;border-radius:10px}
  .table-wrap table{display:table;max-height:none;min-width:600px}
  .btn{padding:10px 14px;font-size:.9rem}
  .card{padding:14px}
  .card-sm{padding:12px}
  .page-header{flex-direction:column;gap:8px;align-items:flex-start}
  .kpi-val{font-size:1.6rem}
  /* Barre de navigation mobile en bas */
  .mobile-nav{
    display:flex;position:fixed;bottom:0;left:0;right:0;
    background:var(--s1);border-top:1px solid var(--s3);
    z-index:999;padding:8px 0 12px;
  }
  .mobile-nav-item{
    flex:1;display:flex;flex-direction:column;align-items:center;
    gap:3px;font-size:.65rem;color:var(--t3);cursor:pointer;
    padding:4px 0;transition:.2s;
  }
  .mobile-nav-item.active{color:var(--green)}
  .mobile-nav-item span:first-child{font-size:1.3rem}
  .chat-layout{grid-template-columns:1fr!important;height:auto}
  .conv-list{height:200px;border-right:none;border-bottom:1px solid var(--s3)}
  .topbar{padding:10px 12px}
}
@media(min-width:769px){
  .mobile-nav{display:none}
  html,body{height:100%;overflow:hidden}
  .main{height:100vh;overflow:hidden}
  .content{overflow-y:auto}
}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sidebar">
  <div class="brand">
    <span class="brand-logo">🛵</span>
    <div><div class="brand-name">GrabDiscount</div><div class="brand-sub">QG Admin</div></div>
  </div>

  <button class="nav-item active" onclick="nav('overview')" id="nav-overview">
    <span class="nav-icon">🏠</span>Vue d'ensemble
  </button>
  <button class="nav-item" onclick="nav('orders')" id="nav-orders">
    <span class="nav-icon">📦</span>Commandes<span class="nav-badge" id="nb-orders" style="display:none">0</span>
  </button>
  <button class="nav-item" onclick="nav('chat')" id="nav-chat">
    <span class="nav-icon">💬</span>Messages<span class="nav-badge" id="nb-chat" style="display:none">0</span>
  </button>
  <button class="nav-item" onclick="nav('accounts')" id="nav-accounts">
    <span class="nav-icon">🍎</span>Comptes Grab
  </button>

  <div class="sidebar-spacer"></div>
  <div class="sidebar-bottom">
    <div style="padding:8px 12px;margin-bottom:6px;font-size:.72rem;color:var(--t3);display:flex;gap:8px;align-items:center">
      <span style="font-size:.8rem">🤖</span>
      <span id="botStatusTxt">Bot —</span>
      <span class="dispo-dot" id="botDot" style="margin-left:auto;background:var(--s4)"></span>
    </div>
    <div class="dispo-toggle" onclick="toggleDispo()" id="dispoToggle">
      <span class="dispo-dot" id="dispoDot"></span>
      <span id="dispoTxt">Disponible</span>
    </div>
    <a class="btn-logout" href="/logout">🚪 Déconnexion</a>
  </div>
</div>

<!-- MAIN -->
<div class="main">

  <!-- OVERVIEW -->
  <div id="page-overview" class="content" style="padding-top:24px">
    <div class="grid-4">
      <div class="card"><div class="kpi-label">Revenus total</div><div class="kpi-val c-green" id="o-rev">—</div><div class="kpi-sub">฿ encaissés</div></div>
      <div class="card"><div class="kpi-label">Marge nette</div><div class="kpi-val c-blue" id="o-mar">—</div><div class="kpi-sub">~50% du revenu</div></div>
      <div class="card"><div class="kpi-label">Commandes</div><div class="kpi-val c-purple" id="o-tot">—</div><div class="kpi-sub" id="o-pend-sub">— en attente</div></div>
      <div class="card"><div class="kpi-label">Messages non lus</div><div class="kpi-val c-red" id="o-unread">—</div><div class="kpi-sub">à traiter</div></div>
    </div>
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card-sm" style="display:flex;align-items:center;gap:14px">
        <span style="font-size:2rem">🤖</span>
        <div><div class="kpi-label">Bot Telegram</div><div id="bot-status-card" style="font-size:.85rem;font-weight:600;color:var(--t3)">—</div></div>
      </div>
      <div class="card-sm" style="display:flex;align-items:center;gap:14px">
        <span style="font-size:2rem">🍽️</span>
        <div><div class="kpi-label">Restaurants DB</div><div id="resto-count-card" style="font-size:.85rem;font-weight:600;color:var(--t3)">—</div></div>
      </div>
      <div class="card-sm" style="display:flex;align-items:center;gap:14px">
        <span style="font-size:2rem">🍎</span>
        <div><div class="kpi-label">Comptes iCloud</div><div id="icloud-count-card" style="font-size:.85rem;font-weight:600;color:var(--t3)">—</div></div>
      </div>
      <div class="card-sm" style="display:flex;align-items:center;gap:14px">
        <span style="font-size:2rem">💳</span>
        <div><div class="kpi-label">Commandes payées</div><div id="paid-count-card" style="font-size:.85rem;font-weight:600;color:var(--t3)">—</div></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="kpi-label" style="margin-bottom:16px">📈 Revenus 7 jours</div>
        <canvas id="revenueChart" height="140"></canvas>
      </div>
      <div class="card">
        <div class="kpi-label" style="margin-bottom:12px">🕐 Activité récente</div>
        <div id="recentActivity"></div>
      </div>
    </div>
    <div class="table-wrap">
      <div class="table-header"><span class="table-title">📦 Dernières commandes</span></div>
      <table><thead><tr><th>Référence</th><th>Client</th><th>Cuisine</th><th>Prix</th><th>Statut</th><th>Heure</th></tr></thead>
      <tbody id="o-recent-orders"></tbody></table>
    </div>

    <!-- TARIFS CONFIGURABLES -->
    <div class="card" style="margin-top:20px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <span style="font-size:1.2rem">💰</span>
        <div style="font-size:.9rem;font-weight:700">Tarifs</div>
        <button class="btn btn-primary btn-sm" style="margin-left:auto" onclick="saveTarifs()">💾 Sauvegarder</button>
        <button class="btn btn-secondary btn-sm" onclick="doBackup()">💾 Backup Telegram</button>
      </div>
      <table style="width:100%;border-collapse:collapse" id="tarifsTable">
        <thead>
          <tr>
            <th style="text-align:left;padding:8px 12px;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);border-bottom:1px solid var(--s3)">Panier Grab (฿)</th>
            <th style="text-align:left;padding:8px 12px;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);border-bottom:1px solid var(--s3)">Prix client (฿)</th>
            <th style="text-align:left;padding:8px 12px;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);border-bottom:1px solid var(--s3)">Lien Wise</th>
          </tr>
        </thead>
        <tbody id="tarifsBody">
          <tr><td colspan="3" style="padding:16px;text-align:center;color:var(--t3)">Chargement…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- ORDERS -->
  <div id="page-orders" style="display:none;height:100%;flex-direction:column">
    <div class="topbar">
      <span class="page-title">📦 Commandes</span>
      <input class="input" style="width:240px;margin-left:auto" id="orderSearch" placeholder="🔍 Rechercher…" oninput="filterOrders()">
    </div>
    <div class="content" style="flex:1;overflow-y:auto">
      <div class="filter-bar" id="orderFilters">
        <span class="filter-pill active" onclick="setFilter(this,'all')">Toutes</span>
        <span class="filter-pill" onclick="setFilter(this,'en_attente_paiement')">⏳ Attente paiement</span>
        <span class="filter-pill" onclick="setFilter(this,'paiement_recu')">💰 Payées</span>
        <span class="filter-pill" onclick="setFilter(this,'en_cours')">🛵 En cours</span>
        <span class="filter-pill" onclick="setFilter(this,'livre')">✅ Livrées</span>
        <span class="filter-pill" onclick="setFilter(this,'annule')">❌ Annulées</span>
      </div>
      <div class="table-wrap">
        <table><thead><tr><th>Référence</th><th>Client</th><th>Cuisine</th><th>Adresse</th><th>Prix client</th><th>Statut</th><th>Heure</th></tr></thead>
        <tbody id="ordersTable"></tbody></table>
      </div>
    </div>
  </div>

  <!-- CHAT -->
  <div id="page-chat" style="display:none;height:100%">
    <div class="chat-layout" style="height:100%">
      <div class="conv-list" id="convList"></div>
      <div id="chatWindow" style="display:flex;flex-direction:column;height:100%">
        <div class="empty" style="margin:auto"><div class="empty-icon">💬</div>Sélectionnez une conversation</div>
      </div>
    </div>
  </div>

  <!-- ACCOUNTS -->
  <div id="page-accounts" style="display:none;flex-direction:column;height:100%;overflow:hidden">
    <div class="topbar">
      <span class="page-title">🏭 Usine Grab — Packs Identité</span>
      <div style="display:flex;gap:8px;margin-left:auto;align-items:center">
        <button class="btn btn-secondary" onclick="openGenModal()">⚡ + Emails</button>
        <span style="font-size:.75rem;color:var(--t3);background:var(--s2);padding:6px 10px;border-radius:8px" title="Nécessite un téléphone Android branché — non disponible sur VPS">📱 Usine Android : non dispo sur VPS</span>
      </div>
    </div>
    <div class="content" style="flex:1;overflow-y:auto">

      <!-- 3 compteurs top -->
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px">
        <div class="card" style="padding:16px 20px;text-align:center">
          <div style="font-size:2rem;font-weight:800;color:var(--orange)" id="packsDispo">—</div>
          <div style="font-size:.78rem;color:var(--t3);margin-top:2px">Sans numéro</div>
        </div>
        <div class="card" style="padding:16px 20px;text-align:center">
          <div style="font-size:2rem;font-weight:800;color:var(--green)" id="packsEnCours">—</div>
          <div style="font-size:.78rem;color:var(--t3);margin-top:2px">Comptes full</div>
        </div>
        <div class="card" style="padding:16px 20px;text-align:center">
          <div style="font-size:2rem;font-weight:800;color:var(--purple)" id="packsReady">—</div>
          <div style="font-size:.78rem;color:var(--t3);margin-top:2px">Utilisés</div>
        </div>
      </div>

      <!-- Auto-génération emails iCloud -->
      <div class="quota-card" style="border-color:#00b14f33;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div style="flex:1;min-width:200px">
            <div style="font-weight:700;margin-bottom:2px">🍎 Auto-génération emails iCloud</div>
            <div style="font-size:.78rem;color:var(--t3)" id="autoGenNext">—</div>
          </div>
          <div id="autoGenTotalWrap" style="font-size:.82rem;color:var(--t3)">Total : <span id="autoGenTotal" style="font-weight:700;color:var(--green)">0</span></div>
          <label id="autoGenToggleWrap" style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <span style="font-size:.82rem;color:var(--t3)" id="autoGenLabel">Désactivé</span>
            <div style="position:relative;width:42px;height:24px" onclick="toggleAutoGen()">
              <div id="autoGenTrack" style="width:42px;height:24px;border-radius:12px;background:var(--s3);transition:.2s"></div>
              <div id="autoGenThumb" style="position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.2s"></div>
            </div>
          </label>
          <button id="autoGenRunBtn" class="btn btn-secondary btn-sm" onclick="runNow()">▶ Now</button>
          <label id="autoGenCookieBtn" class="btn btn-secondary btn-sm" style="cursor:pointer;margin:0" title="Mettre à jour le cookie iCloud (expire tous les 2-3 jours)">
            🍪 Cookie
            <input type="file" accept=".txt" style="display:none" onchange="uploadCookie(this)">
          </label>
        </div>
        <div id="cookieStatus" style="font-size:.75rem;color:var(--t3);margin-top:6px;display:none"></div>
      </div>

      <!-- Recherche + filtres comptes -->
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center">
        <input class="input" id="packsSearch" style="flex:1;min-width:200px;max-width:320px" placeholder="🔍 Rechercher email, nom, adresse…" oninput="onPacksSearch()">
        <div class="filter-bar" style="margin:0;flex:1;min-width:260px">
          <span class="filter-pill active" onclick="setPackFilter(this,'all')">Tous</span>
          <span class="filter-pill" onclick="setPackFilter(this,'available')">📧 Sans numéro</span>
          <span class="filter-pill" onclick="setPackFilter(this,'full')">✅ Full</span>
          <span class="filter-pill" onclick="setPackFilter(this,'grab_ready')">✅ Grab ready</span>
          <span class="filter-pill" onclick="setPackFilter(this,'used')">✓ Utilisé</span>
          <span class="filter-pill" onclick="setPackFilter(this,'failed')">❌ Échoué</span>
        </div>
      </div>

      <!-- Tableau des packs -->
      <div class="table-wrap">
        <div class="table-header">
          <span class="table-title">📦 Packs prêts à inscrire — 1 email = 1 identité = 1 compte</span>
          <span class="pill pill-green" id="packCount" style="margin-left:8px">0</span>
          <button class="btn btn-secondary btn-sm" style="margin-left:auto;font-size:.75rem" onclick="resetFailed()" title="Remettre les comptes en échec en disponible">🔄 Reset failed</button>
        </div>
        <table>
          <thead>
            <tr>
              <th style="width:24px"></th>
              <th>Email iCloud</th>
              <th>Identité + MDP</th>
              <th>Adresse Bangkok</th>
              <th>Statut</th>
              <th style="width:120px">Actions</th>
            </tr>
          </thead>
          <tbody id="packsTable"><tr><td colspan="6" style="text-align:center;color:var(--t3);padding:24px">Chargement…</td></tr></tbody>
        </table>
        <!-- Pagination -->
        <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-top:1px solid var(--s3)">
          <span style="font-size:.8rem;color:var(--t3)" id="packsPageInfo">—</span>
          <div style="margin-left:auto;display:flex;gap:8px">
            <button class="btn btn-secondary btn-sm" id="packsPrev" onclick="packsChangePage(-1)">← Précédent</button>
            <button class="btn btn-secondary btn-sm" id="packsNext" onclick="packsChangePage(1)">Suivant →</button>
          </div>
        </div>
      </div>

      <!-- Note Orchestrateur (désactivé sur VPS) -->
      <div class="card" style="margin-top:20px;border:1px solid var(--s3)">
        <div style="padding:16px 20px;display:flex;align-items:center;gap:14px">
          <span style="font-size:1.8rem">📱</span>
          <div>
            <div style="font-weight:700;margin-bottom:4px">Usine Android — Création auto de comptes Grab</div>
            <div style="font-size:.82rem;color:var(--t3)">Nécessite un téléphone Android branché en USB avec ADB + Appium. Non disponible sur VPS. Pour activer, branchez un téléphone et relancez en local.</div>
          </div>
        </div>
      </div>

    </div>
  </div>


</div><!-- .main -->

<!-- SLIDE PANEL (order detail) -->
<div class="slide-overlay" id="slideOverlay" onclick="closeSlide()"></div>
<div class="slide-panel" id="slidePanel">
  <div class="slide-header">
    <div style="flex:1">
      <div style="font-family:monospace;color:var(--green);font-weight:700;font-size:1rem" id="sp-ref">—</div>
      <div style="font-size:.75rem;color:var(--t3);margin-top:2px" id="sp-time">—</div>
    </div>
    <span id="sp-status-pill"></span>
    <button class="btn btn-secondary btn-sm" onclick="closeSlide()" style="margin-left:8px">✕</button>
  </div>
  <div class="slide-body" id="slideBody"></div>
</div>

<!-- GENERATE MODAL -->
<div class="modal-overlay" id="genModal">
  <div class="modal">
    <h2>⚡ Générer des emails iCloud HME</h2>
    <div class="sub">Chrome doit être ouvert et connecté à iCloud. Limite Apple : ~5 par session / 24h.</div>
    <div style="margin:12px 0;display:flex;align-items:center;gap:12px;">
      <label style="font-weight:600;white-space:nowrap;">Nombre d'emails :</label>
      <input type="number" id="genCount" value="5" min="1" max="25" style="width:70px;padding:6px 10px;border:1px solid #ddd;border-radius:8px;font-size:15px;text-align:center;">
      <span style="color:#888;font-size:13px;">(max 25)</span>
    </div>
    <div class="gen-log" id="genLog">En attente de lancement…</div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeGenModal()">Fermer</button>
      <button class="btn btn-primary" id="genStartBtn" onclick="startGen()">🚀 Lancer la génération</button>
    </div>
  </div>
</div>

<!-- GRAB GEN MODAL -->
<div class="modal-overlay" id="grabGenModal">
  <div class="modal" style="max-width:500px">
    <h2>🤖 Créer un compte Grab</h2>
    <div class="sub">Pipeline automatique : OnOff → OTP → Compte Grab lié à l'email iCloud</div>

    <div style="display:grid;gap:10px;margin:14px 0">
      <div>
        <label style="font-size:.8rem;color:var(--t3);display:block;margin-bottom:4px">📧 Email iCloud (laisser vide = prochain disponible)</label>
        <input id="ggIcloud" type="text" placeholder="ex: abc@icloud.com ou laisser vide" style="width:100%;padding:8px 12px;border:1px solid var(--s3);border-radius:8px;background:var(--s1);color:var(--t1);font-size:.85rem;box-sizing:border-box">
      </div>
      <div>
        <label style="font-size:.8rem;color:var(--t3);display:block;margin-bottom:4px">🔑 Email compte OnOff</label>
        <input id="ggOnoffEmail" type="email" placeholder="votre@email.com" style="width:100%;padding:8px 12px;border:1px solid var(--s3);border-radius:8px;background:var(--s1);color:var(--t1);font-size:.85rem;box-sizing:border-box">
      </div>
      <div>
        <label style="font-size:.8rem;color:var(--t3);display:block;margin-bottom:4px">🔐 Mot de passe OnOff</label>
        <input id="ggOnoffPass" type="password" placeholder="••••••••" style="width:100%;padding:8px 12px;border:1px solid var(--s3);border-radius:8px;background:var(--s1);color:var(--t1);font-size:.85rem;box-sizing:border-box">
      </div>
      <div>
        <label style="font-size:.8rem;color:var(--t3);display:block;margin-bottom:4px">📱 Numéro OnOff (avec indicatif)</label>
        <input id="ggPhone" type="text" placeholder="+33612345678" style="width:100%;padding:8px 12px;border:1px solid var(--s3);border-radius:8px;background:var(--s1);color:var(--t1);font-size:.85rem;box-sizing:border-box">
      </div>
      <div>
        <label style="font-size:.8rem;color:var(--t3);display:block;margin-bottom:4px">📡 Canal OTP</label>
        <select id="ggChannel" style="width:100%;padding:8px 12px;border:1px solid var(--s3);border-radius:8px;background:var(--s1);color:var(--t1);font-size:.85rem">
          <option value="sms">SMS</option>
          <option value="whatsapp">WhatsApp</option>
        </select>
      </div>
    </div>

    <pre id="ggLog" style="background:var(--s2);border-radius:8px;padding:12px;font-size:.78rem;color:var(--t2);min-height:60px;white-space:pre-wrap;max-height:140px;overflow-y:auto">En attente…</pre>

    <div class="modal-actions" style="margin-top:14px">
      <button class="btn btn-secondary" onclick="closeGrabGenModal()">Fermer</button>
      <button class="btn btn-primary" id="ggRunBtn" onclick="runGrabGen()" style="background:#00b14f">🚀 Créer le compte</button>
    </div>
  </div>
</div>

<!-- TOAST -->
<div class="toast-wrap" id="toastWrap"></div>

<!-- MOBILE NAV BAR -->
<nav class="mobile-nav" id="mobileNav">
  <div class="mobile-nav-item active" id="mnav-overview" onclick="nav('overview')">
    <span>🏠</span><span>Accueil</span>
  </div>
  <div class="mobile-nav-item" id="mnav-orders" onclick="nav('orders')">
    <span>📦</span><span>Commandes</span>
  </div>
  <div class="mobile-nav-item" id="mnav-chat" onclick="nav('chat')">
    <span>💬</span><span>Messages</span>
  </div>
  <div class="mobile-nav-item" id="mnav-accounts" onclick="nav('accounts')">
    <span>🍎</span><span>Comptes</span>
  </div>
</nav>

<script>
// ── STATE ─────────────────────────────────────────────────
let _orders={}, _msgs={}, _accounts=[], _filter='all', _activeChat=null, _revenueChart=null;
let _packs=[], _packsFilter='all', _packsSearch='', _accountsPage=0, _accountsPerPage=20;
const STATUT = {
  'en_attente_confirmation': {label:'En attente',    cls:'pill-gray'},
  'en_attente_paiement':     {label:'💳 Paiement',  cls:'pill-orange'},
  'paiement_recu':           {label:'💰 Payé',       cls:'pill-blue'},
  'en_cours':                {label:'🛵 En cours',   cls:'pill-cyan'},
  'livre':                   {label:'✅ Livré',       cls:'pill-green'},
  'annule':                  {label:'❌ Annulé',      cls:'pill-red'},
};
function sf(s){const m=STATUT[s]||{label:s||'?',cls:'pill-gray'};return `<span class="pill ${m.cls}">${m.label}</span>`}

// ── TOAST ─────────────────────────────────────────────────
let _tid=0;
function toast(msg,ok=true){
  const id='t'+(++_tid);
  const d=document.getElementById('toastWrap');
  d.insertAdjacentHTML('beforeend',`<div class="toast ${ok?'ok':'err'}" id="${id}">${msg}</div>`);
  setTimeout(()=>document.getElementById(id)?.classList.add('show'),10);
  setTimeout(()=>{const el=document.getElementById(id);if(el){el.classList.remove('show');setTimeout(()=>el.remove(),300);}},3500);
}

// ── NAVIGATION ────────────────────────────────────────────
let _page='overview';
function nav(p){
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('nav-'+p)?.classList.add('active');
  // Mobile nav sync
  document.querySelectorAll('.mobile-nav-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('mnav-'+p)?.classList.add('active');
  ['overview','orders','chat','accounts'].forEach(id=>{
    const el=document.getElementById('page-'+id);
    if(el) el.style.display=id===p?(id==='overview'?'block':'flex'):'none';
  });
  if(p==='orders'){document.getElementById('page-orders').style.display='flex';}
  if(p==='chat'){document.getElementById('page-chat').style.display='block'; renderConvList(); _startChatPoll();}
  else { _stopChatPoll(); }
  if(p==='accounts'){document.getElementById('page-accounts').style.display='flex'; loadPacks(); loadAutoGen(); orchStartPolling();}
  // Scroll top on mobile
  window.scrollTo(0,0);
  _page=p;
}

// ── DISPO TOGGLE ──────────────────────────────────────────
let _dispo=true;
async function loadDispo(){
  try{
    const r=await fetch('/api/dispo'); const d=await r.json();
    _dispo=d.dispo!==false;
    document.getElementById('dispoDot').className='dispo-dot'+(_dispo?'':' pause');
    document.getElementById('dispoTxt').textContent=_dispo?'Disponible':'En pause';
  }catch(e){}
}
async function toggleDispo(){
  _dispo=!_dispo;
  document.getElementById('dispoDot').className='dispo-dot'+(_dispo?'':' pause');
  document.getElementById('dispoTxt').textContent=_dispo?'Disponible':'En pause';
  toast(_dispo?'✅ Statut : Disponible':'⏸️ Statut : En pause', _dispo);
  await fetch('/api/dispo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dispo:_dispo})});
}
async function loadBotStatus(){
  try{
    const r=await fetch('/api/bot/health'); const d=await r.json();
    const botEl=document.getElementById('botStatusTxt');
    const dotEl=document.getElementById('botDot');
    const cardEl=document.getElementById('bot-status-card');
    if(d.alive){
      if(botEl) botEl.textContent='Bot ✅ actif';
      if(dotEl) dotEl.style.background='var(--green)';
      if(cardEl){cardEl.textContent='✅ En ligne';cardEl.style.color='var(--green)';}
    } else {
      if(botEl) botEl.textContent='Bot ⚠ hors ligne';
      if(dotEl) dotEl.style.background='var(--orange)';
      if(cardEl){cardEl.textContent='⚠ Hors ligne';cardEl.style.color='var(--orange)';}
    }
  }catch(e){
    const el=document.getElementById('bot-status-card');
    if(el){el.textContent='? Inconnu';el.style.color='var(--t3)';}
  }
}
async function loadRestoCount(){
  try{
    const r=await fetch('/api/restaurants/count'); const d=await r.json();
    const el=document.getElementById('resto-count-card');
    if(el&&d.total){
      const zones=d.zones_done?` · zone ${d.zones_done}/${d.zones_total}`:'';
      el.textContent=d.total.toLocaleString('fr-FR')+' restos'+zones;
      el.style.color='var(--cyan)';
    }
  }catch(e){}
}

// ── STATS + OVERVIEW ──────────────────────────────────────
async function loadStats(){
  const r=await fetch('/api/stats'); const s=await r.json();
  $('o-rev').textContent=(s.revenue||0).toLocaleString('fr-FR')+'฿';
  $('o-mar').textContent=(s.margin||0).toLocaleString('fr-FR')+'฿';
  $('o-tot').textContent=s.total||0;
  $('o-pend-sub').textContent=(s.pending||0)+' en attente';
  $('o-unread').textContent=s.unread||0;
  // Mini cards
  const pc=$('paid-count-card');
  if(pc){pc.textContent=(s.paid||0)+' commande'+(s.paid>1?'s':'');pc.style.color='var(--blue)';}

  // Badges sidebar
  const nb=s.pending||0;
  const nbc=s.unread||0;
  setbadge('nb-orders',nb); setbadge('nb-chat',nbc);

  // Revenue chart
  if(!_revenueChart){
    const ctx=document.getElementById('revenueChart').getContext('2d');
    _revenueChart=new Chart(ctx,{
      type:'bar',
      data:{labels:s.days||[],datasets:[{data:s.revs||[],backgroundColor:'#00b14f40',
        borderColor:'#00b14f',borderWidth:2,borderRadius:6}]},
      options:{responsive:true,plugins:{legend:{display:false}},
        scales:{x:{grid:{color:'#1f293740'},ticks:{color:'#6b7280',font:{size:10}}},
                y:{grid:{color:'#1f293740'},ticks:{color:'#6b7280',font:{size:10},
                   callback:v=>v+'฿'}}}}
    });
  } else {
    _revenueChart.data.labels=s.days||[];
    _revenueChart.data.datasets[0].data=s.revs||[];
    _revenueChart.update();
  }
}
function setbadge(id,n){const el=document.getElementById(id);if(!el)return;el.textContent=n;el.style.display=n>0?'':'none';}
function $(id){return document.getElementById(id)}

// ── ORDERS ────────────────────────────────────────────────
async function loadOrders(){
  const r=await fetch('/api/orders'); _orders=await r.json();
  renderOrders(); renderRecentOrders();
}
function filteredOrders(){
  let entries=Object.entries(_orders).reverse();
  const q=document.getElementById('orderSearch')?.value?.toLowerCase()||'';
  if(q) entries=entries.filter(([ref,o])=>ref.toLowerCase().includes(q)||(o.nom||'').toLowerCase().includes(q)||(o.adresse||'').toLowerCase().includes(q));
  if(_filter!=='all') entries=entries.filter(([,o])=>o.statut===_filter);
  return entries;
}
function setFilter(el,f){
  document.querySelectorAll('.filter-pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active'); _filter=f; renderOrders();
}
function filterOrders(){renderOrders();}

function renderOrders(){
  const tbody=document.getElementById('ordersTable');
  if(!tbody)return;
  const entries=filteredOrders();
  if(!entries.length){tbody.innerHTML=`<tr><td colspan="7"><div class="empty"><div class="empty-icon">📭</div>Aucune commande</div></td></tr>`;return;}
  tbody.innerHTML=entries.map(([ref,o])=>`
    <tr onclick="openSlide('${escHtml(ref)}')">
      <td class="mono" style="color:var(--green)">${escHtml(ref)}</td>
      <td>${escHtml(o.nom||'—')}</td>
      <td>${escHtml(o.cuisine||'—')}</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(o.adresse||'—')}</td>
      <td style="font-weight:700;color:var(--green)">${o.prix||0}฿</td>
      <td>${sf(o.statut)}</td>
      <td style="color:var(--t3);font-size:.78rem">${escHtml(o.heure||'—')}</td>
    </tr>`).join('');
}

function renderRecentOrders(){
  const tbody=document.getElementById('o-recent-orders');
  if(!tbody)return;
  const entries=Object.entries(_orders).reverse().slice(0,5);
  if(!entries.length){tbody.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--t3);padding:24px">Aucune commande</td></tr>`;return;}
  tbody.innerHTML=entries.map(([ref,o])=>`
    <tr onclick="nav('orders');setTimeout(()=>openSlide('${escHtml(ref)}'),100)" style="cursor:pointer">
      <td class="mono" style="color:var(--green)">${escHtml(ref)}</td>
      <td>${escHtml(o.nom||'—')}</td>
      <td>${escHtml(o.cuisine||'—')}</td>
      <td style="font-weight:700;color:var(--green)">${o.prix||0}฿</td>
      <td>${sf(o.statut)}</td>
      <td style="color:var(--t3);font-size:.78rem">${escHtml(o.heure||'—')}</td>
    </tr>`).join('');
}

// ── SLIDE PANEL ───────────────────────────────────────────
function openSlide(ref){
  const o=_orders[ref]; if(!o)return;
  document.getElementById('sp-ref').textContent=ref;
  document.getElementById('sp-time').textContent=o.heure||'';
  document.getElementById('sp-status-pill').innerHTML=sf(o.statut);
  const statusOpts=Object.entries(STATUT).map(([k,v])=>`<option value="${k}"${o.statut===k?' selected':''}>${v.label}</option>`).join('');
  const safeRef = escHtml(ref);
  const safeLien = o.lien_commande ? escHtml(o.lien_commande) : '';
  document.getElementById('slideBody').innerHTML=`
    <div class="slide-section"><h4>👤 Client</h4>
      <div class="detail-row"><span class="detail-key">Nom</span><span class="detail-val">${escHtml(o.nom||'—')}</span></div>
      <div class="detail-row"><span class="detail-key">Telegram ID</span><span class="detail-val mono">${escHtml(String(o.chat_id||'—'))}</span></div>
    </div>
    <div class="slide-section"><h4>📦 Commande</h4>
      <div class="detail-row"><span class="detail-key">Cuisine</span><span class="detail-val">${escHtml(o.cuisine||'—')}</span></div>
      <div class="detail-row"><span class="detail-key">Adresse</span><span class="detail-val">${escHtml(o.adresse||'—')}</span></div>
      ${safeLien?`<div class="detail-row"><span class="detail-key">Lien</span><a href="${safeLien}" target="_blank" rel="noopener noreferrer" style="color:var(--blue);font-size:.82rem">Ouvrir ↗</a></div>`:''}
      <div class="detail-row"><span class="detail-key">Panier Grab</span><span class="detail-val">${o.budget||0}฿</span></div>
      <div class="detail-row"><span class="detail-key">Payé</span><span class="detail-val c-green">${o.prix||0}฿</span></div>
      <div class="detail-row"><span class="detail-key">Marge</span><span class="detail-val c-blue">${Math.round((o.prix||0)/2)}฿</span></div>
    </div>
    <div class="slide-section"><h4>⚡ Statut</h4>
      <select class="select" id="sp-sel" style="width:100%;margin-bottom:10px">${statusOpts}</select>
      <button class="btn btn-secondary btn-sm" style="width:100%" onclick="updateStatus('${safeRef}')">Mettre à jour</button>
    </div>
    <div class="slide-section"><h4>📍 Envoyer le suivi</h4>
      <input class="input" id="sp-track" style="width:100%;margin-bottom:10px" placeholder="https://order.grab.com/tracking/…">
      <button class="btn btn-primary btn-sm" style="width:100%" onclick="sendTracking('${safeRef}')">🛵 Envoyer au client</button>
    </div>
    <div class="slide-section"><h4>💬 Contacter</h4>
      <textarea class="input" id="sp-msg" style="width:100%;height:80px;resize:none;margin-bottom:10px" placeholder="Votre message…"></textarea>
      <button class="btn btn-blue btn-sm" style="width:100%" onclick="quickReply(${parseInt(o.chat_id)||0})">Envoyer le message</button>
    </div>`;
  document.getElementById('slideOverlay').classList.add('open');
  document.getElementById('slidePanel').classList.add('open');
}
function closeSlide(){
  document.getElementById('slideOverlay').classList.remove('open');
  document.getElementById('slidePanel').classList.remove('open');
}
async function updateStatus(ref){
  const s=document.getElementById('sp-sel')?.value;
  const r=await fetch('/api/order/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:ref,statut:s})});
  const d=await r.json();
  if(d.ok){toast('✅ Statut mis à jour');document.getElementById('sp-status-pill').innerHTML=sf(s);await loadOrders();}
  else toast('❌ Erreur',false);
}
async function sendTracking(ref){
  const lien=document.getElementById('sp-track')?.value?.trim();
  if(!lien){toast('⚠️ Entrez un lien',false);return;}
  const r=await fetch('/api/order/tracking',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:ref,lien})});
  const d=await r.json();
  toast(d.ok?'✅ Suivi envoyé !':'❌ Erreur envoi',d.ok);
  if(d.ok){await loadOrders();}
}
async function quickReply(chatId){
  const text=document.getElementById('sp-msg')?.value?.trim();
  if(!text){toast('⚠️ Message vide',false);return;}
  const r=await fetch('/api/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:chatId,text})});
  const d=await r.json();
  toast(d.ok?'✅ Message envoyé !':'❌ Erreur envoi',d.ok);
  if(d.ok && document.getElementById('sp-msg')) document.getElementById('sp-msg').value='';
}

// ── CHAT ──────────────────────────────────────────────────
// ── CHAT — état interne ──────────────────────────────────
let _chatPollTimer = null;
let _chatSoundEnabled = true;
let _prevUnreadTotal = 0;
const _QUICK_REPLIES = [
  "🛵 En cours, on s'en occupe !",
  "✅ Commande livrée ! Bon appétit 🍽️",
  "📸 Envoie ton reçu de paiement Wise",
  "⏳ Prêt dans 5 min, on passe la commande",
  "❌ Problème avec ta commande, on te recontacte",
];

function _chatBeep(){
  if(!_chatSoundEnabled) return;
  try{
    const ctx=new(window.AudioContext||window.webkitAudioContext)();
    const o=ctx.createOscillator(); const g=ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value=880; o.type='sine';
    g.gain.setValueAtTime(0.3,ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.3);
    o.start(); o.stop(ctx.currentTime+0.3);
  }catch(e){}
}

async function loadMsgs(silent=false){
  try{
    const r=await fetch('/api/messages'); const fresh=await r.json();
    // Détecter nouveaux messages non lus
    const newUnread=Object.values(fresh).reduce((s,c)=>s+(c.unread||0),0);
    if(!silent && newUnread > _prevUnreadTotal) _chatBeep();
    _prevUnreadTotal=newUnread;
    _msgs=fresh;
    renderConvList();
    if(_activeChat) _renderChatSmart(_activeChat);
  }catch(e){}
}

function _renderChatSmart(uid){
  const c=_msgs[uid]; if(!c)return;
  const msgs=document.getElementById('chatMsgs');
  // Garde le scroll si l'utilisateur a scrollé vers le haut
  const atBottom = msgs ? msgs.scrollHeight-msgs.scrollTop-msgs.clientHeight < 60 : true;
  renderChat(uid);
  if(atBottom) setTimeout(()=>{const el=document.getElementById('chatMsgs');if(el)el.scrollTop=el.scrollHeight;},20);
}

function renderConvList(){
  const container=document.getElementById('convList'); if(!container)return;
  const entries=Object.entries(_msgs).sort((a,b)=>{
    const la=a[1].messages?.slice(-1)[0]?.ts||'';
    const lb=b[1].messages?.slice(-1)[0]?.ts||'';
    return lb.localeCompare(la);
  });
  if(!entries.length){container.innerHTML='<div class="empty"><div class="empty-icon">💬</div>Aucun message</div>';return;}
  container.innerHTML=entries.map(([uid,c])=>{
    const last=c.messages?.slice(-1)[0];
    const init=(c.name||'?').split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase();
    const colors=['#3b82f6','#8b5cf6','#06b6d4','#f59e0b','#ef4444'];
    const col=colors[uid.charCodeAt(0)%colors.length];
    const unread=c.unread||0;
    return `<div class="conv-item${_activeChat===uid?' active':''}" onclick="selectChat('${uid}')">
      <div class="avatar" style="background:${col}20;color:${col}">${init}</div>
      <div style="flex:1;min-width:0">
        <div class="conv-name">${escHtml(c.name||uid)}</div>
        <div class="conv-prev">${last?.from==='admin'?'Vous : ':''}${escHtml(last?.text||'…')}</div>
      </div>
      ${unread>0?`<span class="unread-badge">${unread}</span>`:''}
    </div>`;
  }).join('');
}

function selectChat(uid){
  _activeChat=uid;
  renderConvList();
  renderChat(uid);
  markRead(uid);
}

function renderChat(uid){
  const c=_msgs[uid]; if(!c)return;
  const win=document.getElementById('chatWindow'); if(!win)return;
  const init=escHtml((c.name||'?').split(' ').map(w=>w[0]).slice(0,2).join('').toUpperCase());
  const safeUid=escHtml(uid);
  const msgs=(c.messages||[]).map(m=>`
    <div style="display:flex;flex-direction:column;align-items:${m.from==='admin'?'flex-end':'flex-start'}">
      <div class="msg-bubble msg-${m.from==='admin'?'admin':'client'}">${escHtml(m.text||'')}</div>
      <div class="msg-time">${escHtml(m.heure||'')}</div>
    </div>`).join('');
  const quickBtns=_QUICK_REPLIES.map(t=>
    `<button onclick="useQuickReply('${safeUid}','${t.replace(/'/g,"\\'")}')"
      style="background:var(--s3);border:none;border-radius:20px;padding:5px 12px;color:var(--t2);
             font-size:.75rem;cursor:pointer;white-space:nowrap;flex-shrink:0"
      onmouseover="this.style.background='var(--s4)'" onmouseout="this.style.background='var(--s3)'"
    >${escHtml(t)}</button>`
  ).join('');
  win.innerHTML=`
    <div class="chat-header">
      <div class="avatar" style="background:#3b82f620;color:#3b82f6;width:36px;height:36px;font-size:.85rem">${init}</div>
      <div style="flex:1"><div style="font-weight:700">${escHtml(c.name||uid)}</div>
        <div style="font-size:.75rem;color:var(--t3)">${escHtml(c.username||'')} · ID : ${safeUid}</div></div>
      <label style="display:flex;align-items:center;gap:6px;font-size:.75rem;color:var(--t3);cursor:pointer">
        <input type="checkbox" ${_chatSoundEnabled?'checked':''} onchange="_chatSoundEnabled=this.checked"> 🔔
      </label>
    </div>
    <div class="chat-msgs" id="chatMsgs">${msgs||'<div style="color:var(--t3);margin:auto;padding-top:40px">Aucun message</div>'}</div>
    <div style="padding:8px 16px;border-top:1px solid var(--s3);display:flex;gap:6px;overflow-x:auto;scrollbar-width:none">${quickBtns}</div>
    <div class="chat-input-row">
      <textarea class="chat-textarea" id="chatInput" rows="2" placeholder="Répondre… (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendReply('${safeUid}')}"></textarea>
      <button class="send-btn" onclick="sendReply('${safeUid}')">➤</button>
    </div>`;
  setTimeout(()=>{const el=document.getElementById('chatMsgs');if(el)el.scrollTop=el.scrollHeight;},30);
}

function useQuickReply(uid, text){
  const inp=document.getElementById('chatInput');
  if(inp){ inp.value=text; inp.focus(); }
}

async function sendReply(uid){
  const inp=document.getElementById('chatInput');
  const text=(inp?.value||'').trim(); if(!text)return;
  // Optimistic : affiche le message immédiatement
  const k=String(uid);
  if(_msgs[k]){
    const now=new Date();
    const hh=String(now.getHours()).padStart(2,'0'), mm=String(now.getMinutes()).padStart(2,'0');
    const dd=String(now.getDate()).padStart(2,'0'), mo=String(now.getMonth()+1).padStart(2,'0');
    _msgs[k].messages=_msgs[k].messages||[];
    _msgs[k].messages.push({text,ts:now.toISOString(),heure:`${dd}/${mo} à ${hh}:${mm}`,from:'admin',read:true});
    renderChat(uid);
    setTimeout(()=>{const el=document.getElementById('chatMsgs');if(el)el.scrollTop=el.scrollHeight;},20);
  }
  inp.value='';
  const r=await fetch('/api/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(uid),text})});
  const d=await r.json();
  if(!d.ok) toast('❌ Erreur envoi',false);
  await loadMsgs(true);
}

async function markRead(uid){
  await fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid})});
  if(_msgs[uid]){ _msgs[uid].unread=0; _prevUnreadTotal=Math.max(0,_prevUnreadTotal-(_msgs[uid].unread||0)); }
}

// Auto-refresh chat toutes les 3s quand tab chat visible
function _startChatPoll(){ if(_chatPollTimer)return; _chatPollTimer=setInterval(()=>{if(!document.hidden)loadMsgs(true);},3000); }
function _stopChatPoll(){ clearInterval(_chatPollTimer); _chatPollTimer=null; }

// ── AUTO-GEN ──────────────────────────────────────────────
let _autoGenEnabled=false;
async function loadAutoGen(){
  try{
    const r=await fetch('/api/autogen/status'); const d=await r.json();
    _autoGenEnabled=d.enabled;
    // Mode VPS : pas de cookie iCloud → génération impossible ici, gérée par Mac.
    // On masque les contrôles interactifs et on affiche un message d'info statique.
    if(d.can_generate===false){
      $('autoGenNext').innerHTML='🖥️ Génération gérée par le Mac (LaunchAgent) — rien à faire ici.';
      $('autoGenNext').style.color='var(--t2)';
      ['autoGenToggleWrap','autoGenRunBtn','autoGenCookieBtn','autoGenTotalWrap'].forEach(id=>{
        const el=$(id); if(el) el.style.display='none';
      });
      return;
    }
    // Toggle visuel
    const track=$('autoGenTrack'); const thumb=$('autoGenThumb');
    if(track){track.style.background=d.enabled?'var(--green)':'var(--s3)';}
    if(thumb){thumb.style.left=d.enabled?'21px':'3px';}
    $('autoGenLabel').textContent=d.enabled?'Activé':'Désactivé';
    $('autoGenLabel').style.color=d.enabled?'var(--green)':'var(--t3)';
    // Prochain run
    if(d.next_run){
      const dt=new Date(d.next_run);
      const diff=Math.round((dt-Date.now())/60000);
      $('autoGenNext').textContent=d.enabled?`Prochain run dans ${diff} min (${dt.toLocaleTimeString('fr',{hour:'2-digit',minute:'2-digit'})})`:'Désactivé — 5 emails/heure automatiquement';
    } else {
      $('autoGenNext').textContent=d.enabled?'En cours de planification…':'Activez pour générer 5 emails toutes les 65 min';
    }
    $('autoGenTotal').textContent=d.total||0;
    // Historique runs
    if(d.log&&d.log.length){
      $('autoGenLog').style.display='block';
      $('autoGenLog').innerHTML='<b>Historique :</b> '+d.log.slice(0,5).map(l=>`<span style="margin-right:10px">${l.ts} → ${l.ok?'<span style="color:var(--green)">+'+l.count+'</span>':'<span style="color:var(--red)">0</span>'}</span>`).join('');
    }
  }catch(e){}
}
async function toggleAutoGen(){
  const r=await fetch('/api/autogen/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!_autoGenEnabled,interval:65,count:5})});
  const d=await r.json();
  if(d.ok){toast(d.enabled?'🤖 Auto-génération activée !':'Auto-génération désactivée',d.enabled);}
  await loadAutoGen();
}
async function runNow(){
  const r=await fetch('/api/autogen/runnow',{method:'POST'}); const d=await r.json();
  if(d.ok){toast('🔄 Génération lancée…');setTimeout(()=>{loadAccounts();loadAutoGen();},8000);}
  else toast('⚠ '+d.msg,false);
}
async function uploadCookie(input){
  const file=input.files[0]; if(!file)return;
  const status=document.getElementById('cookieStatus');
  status.style.display='block'; status.textContent='⏳ Upload en cours…'; status.style.color='var(--t3)';
  const fd=new FormData(); fd.append('cookie',file);
  try{
    const r=await fetch('/api/cookie/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.ok){status.textContent='✅ Cookie mis à jour !';status.style.color='var(--green)';toast('🍪 Cookie iCloud mis à jour !');}
    else{status.textContent='❌ Erreur : '+d.error;status.style.color='var(--red)';toast('❌ '+d.error,false);}
  }catch(e){status.textContent='❌ Erreur réseau';status.style.color='var(--red)';}
  setTimeout(()=>{status.style.display='none';},5000);
  input.value='';
}

// ── ACCOUNTS ──────────────────────────────────────────────
async function loadAccounts(){
  await loadPacks();
}

async function loadPacks(){
  try{
    const r=await fetch('/api/packs'); const d=await r.json();
    _packs=d.packs||[];
    // Compteurs globaux (sur tous les packs, pas filtrés)
    const sansTel=_packs.filter(p=>p.status==='available').length;
    const full=_packs.filter(p=>p.status==='full'||p.status==='grab_ready').length;
    const used=_packs.filter(p=>p.status==='used').length;
    if($('packsDispo'))  $('packsDispo').textContent=sansTel;
    if($('packsEnCours'))$('packsEnCours').textContent=full;
    if($('packsReady'))  $('packsReady').textContent=used;
    if($('packCount'))   $('packCount').textContent=_packs.length;
    renderPacks();
  }catch(ex){
    const tbody=document.getElementById('packsTable');
    if(tbody)tbody.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--red);padding:16px">Erreur: ${ex.message}</td></tr>`;
  }
}
function filteredPacks(){
  let packs=_packs;
  if(_packsFilter!=='all') packs=packs.filter(p=>p.status===_packsFilter);
  const q=_packsSearch.toLowerCase();
  if(q) packs=packs.filter(p=>
    (p.email||'').toLowerCase().includes(q)||
    (p.full_name||'').toLowerCase().includes(q)||
    (p.prenom||'').toLowerCase().includes(q)||
    (p.nom||'').toLowerCase().includes(q)||
    (p.bangkok_addr||'').toLowerCase().includes(q)
  );
  return packs;
}
function setPackFilter(el,f){
  document.querySelectorAll('#page-accounts .filter-pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active'); _packsFilter=f; _accountsPage=0; renderPacks();
}
function onPacksSearch(){
  _packsSearch=document.getElementById('packsSearch')?.value||'';
  _accountsPage=0; renderPacks();
}
function packsChangePage(dir){
  const packs=filteredPacks();
  const totalPages=Math.ceil(packs.length/_accountsPerPage)||1;
  _accountsPage=Math.max(0,Math.min(_accountsPage+dir,totalPages-1));
  renderPacks();
}
function renderPacks(){
  const tbody=document.getElementById('packsTable'); if(!tbody)return;
  const packs=filteredPacks();
  const totalPages=Math.ceil(packs.length/_accountsPerPage)||1;
  if(_accountsPage>=totalPages) _accountsPage=Math.max(0,totalPages-1);
  const start=_accountsPage*_accountsPerPage;
  const pagePacks=packs.slice(start,start+_accountsPerPage);
  // Pagination info
  const infoEl=$('packsPageInfo');
  if(infoEl) infoEl.textContent=packs.length?`Affichage ${start+1}–${Math.min(start+_accountsPerPage,packs.length)} sur ${packs.length} comptes`:'0 comptes';
  const prevBtn=$('packsPrev'); const nextBtn=$('packsNext');
  if(prevBtn) prevBtn.disabled=_accountsPage===0;
  if(nextBtn) nextBtn.disabled=_accountsPage>=totalPages-1;
  if(!packs.length){tbody.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--t3);padding:24px">📭 Aucun email — cliquez sur "+ Emails"</td></tr>`;return;}
  const STATUS_PACK={
    'full':      '<span class="pill" style="background:#05966922;color:#34d399;border:1px solid #05966944">✅ Compte full</span>',
    'used':      '<span class="pill" style="background:#1e293b;color:#64748b">✓ Utilisé</span>',
    'available': '<span class="pill pill-orange">📧 Sans numéro</span>',
    'failed':    '<span class="pill pill-red">❌ Échoué</span>',
    'grab_ready':'<span class="pill" style="background:#05966922;color:#34d399;border:1px solid #05966944">✅ Compte full</span>',
  };
  tbody.innerHTML=pagePacks.map(p=>{
    const e=escHtml(p.email||'');
    const emailRaw=p.email||'';
    const name=escHtml(p.full_name||`${p.prenom} ${p.nom}`);
    const nameRaw=p.full_name||`${p.prenom} ${p.nom}`;
    const addrFull=p.bangkok_addr||'';
    const addr=escHtml(addrFull.slice(0,50));
    const phone=p.phone||'';
    const pass='Grab2024lol!';
    const status=p.status||'available';
    const badge=STATUS_PACK[status]||`<span class="pill">${status}</span>`;
    const errTip=p._last_error?`title="${escHtml(p._last_error)}"`:''
    const failBadge=p._fail_count>0?`<span style="color:var(--orange);font-size:.7rem;margin-left:4px" ${errTip}>⚠ ${p._fail_count}x</span>`:'';
    // Input phone inline (quand pas de numéro)
    const phoneInput = status !== 'used' && status !== 'full' && status !== 'grab_ready'
      ? `<div style="display:flex;gap:4px;margin-top:4px">
           <input id="ph_${emailRaw.replace(/[@.]/g,'_')}" type="text" placeholder="+66XXXXXXXXX"
             style="width:130px;padding:4px 8px;border:1px solid var(--s3);border-radius:6px;background:var(--s1);color:var(--t1);font-size:.75rem"
             onkeydown="if(event.key==='Enter')savePhone('${emailRaw.replace(/'/g,"\\'")}')">
           <button class="btn btn-primary btn-sm" style="font-size:.7rem;padding:3px 8px;background:#3b82f6"
             onclick="savePhone('${emailRaw.replace(/'/g,"\\'")}')">💾</button>
         </div>`
      : '';
    // Affichage numéro si full
    const phoneDisplay = phone && (status === 'full' || status === 'grab_ready')
      ? `<div style="font-family:monospace;font-size:.72rem;color:var(--green);margin-top:2px">📱 ${escHtml(phone)}</div>`
      : '';
    // Bouton marquer utilisé
    const usedBtn = (status === 'full' || status === 'grab_ready')
      ? `<button class="btn btn-secondary btn-sm" style="font-size:.7rem;padding:3px 7px;margin-left:4px" onclick="markUsed('${emailRaw.replace(/'/g,"\\'")}')">✓ Utilisé</button>`
      : '';
    // Bouton copier
    const copyBtn=`<button class="btn btn-secondary btn-sm" style="font-size:.7rem;padding:3px 7px" onclick='copyPackData(${JSON.stringify({email:emailRaw,name:nameRaw,addr:addrFull,pass,phone})})' title="Copier toutes les données">📋</button>`;
    return `<tr>
      <td style="padding:0 6px;color:var(--t3)">•</td>
      <td style="font-size:.77rem">
        <div class="mono" style="color:var(--purple)">${e}</div>
        ${phoneDisplay}
        ${phoneInput}
      </td>
      <td style="font-size:.82rem">
        <div style="font-weight:600;color:var(--t1)">${name}</div>
        <div style="color:var(--t3);font-size:.72rem">🇫🇷 · 🔑 <span class="mono">${pass}</span></div>
      </td>
      <td style="font-size:.74rem;color:var(--t3);max-width:220px" title="${escHtml(addrFull)}">
        📍 ${addr}${addrFull.length>50?'…':''}
      </td>
      <td>${badge}${failBadge}</td>
      <td>${copyBtn}${usedBtn}</td>
    </tr>`;
  }).join('');
}
function copyPackData(p){
  const lines=['📧 Email    : '+p.email,'👤 Nom      : '+p.name,'📍 Adresse  : '+p.addr,'🔑 MDP      : '+p.pass];
  if(p.phone) lines.push('📱 Tél      : '+p.phone);
  const txt=lines.join('\\n');
  navigator.clipboard.writeText(txt).then(()=>toast('📋 Données copiées !')).catch(()=>{
    const el=document.createElement('textarea');
    el.value=txt; document.body.appendChild(el); el.select();
    document.execCommand('copy'); document.body.removeChild(el);
    toast('📋 Données copiées !');
  });
}
async function savePhone(email){
  const key='ph_'+email.replace(/[@.]/g,'_');
  const phone=document.getElementById(key)?.value.trim()||'';
  if(!phone){toast('⚠ Entre un numéro',false);return;}
  const r=await fetch('/api/packs/set_phone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,phone})});
  const d=await r.json();
  if(d.ok){toast('✅ Numéro enregistré — compte full !');await loadPacks();}
  else toast('❌ '+d.msg,false);
}
async function markUsed(email){
  const r=await fetch('/api/accounts/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,status:'used'})});
  const d=await r.json();
  if(d.ok){toast('✓ Compte marqué utilisé');await loadPacks();}
}
async function resetFailed(){
  const r=await fetch('/api/packs/reset_failed',{method:'POST'});
  const d=await r.json();
  toast(`🔄 ${d.reset} comptes remis en disponible`);
  await loadPacks();
}
function copyEmail(e){navigator.clipboard.writeText(e);toast('📋 Email copié !');}
function copyGrabPass(btn){navigator.clipboard.writeText(btn.dataset.pass||'');toast('🔑 Mot de passe copié !');}
async function toggleAccountStatus(email,status){
  await fetch('/api/accounts/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,status,grab_phone:''})});
  toast(status==='used'?'🔗 Marqué comme utilisé':'✅ Libéré');
  await loadAccounts();
}

// ── TARIFS ────────────────────────────────────────────────
let _tarifs=[];
async function loadTarifs(){
  try{
    const r=await fetch('/api/config'); const d=await r.json();
    _tarifs=d.budgets||[];
    renderTarifs();
  }catch(e){}
}
function renderTarifs(){
  const tbody=$('tarifsBody'); if(!tbody)return;
  if(!_tarifs.length){tbody.innerHTML='<tr><td colspan="3" style="color:var(--t3);padding:12px">Aucun tarif</td></tr>';return;}
  tbody.innerHTML=_tarifs.map((b,i)=>`
    <tr>
      <td style="padding:8px 12px"><input class="input" type="number" id="t_panier_${i}" value="${b.panier||0}" style="width:100px"></td>
      <td style="padding:8px 12px"><input class="input" type="number" id="t_prix_${i}" value="${b.prix||0}" style="width:100px"></td>
      <td style="padding:8px 12px"><input class="input" type="text" id="t_wise_${i}" value="${escHtml(b.wise||'')}" style="width:100%;max-width:380px"></td>
    </tr>`).join('');
}
async function saveTarifs(){
  const budgets=_tarifs.map((_,i)=>({
    panier:parseInt($('t_panier_'+i)?.value)||0,
    prix:  parseInt($('t_prix_'+i)?.value)||0,
    wise:  $('t_wise_'+i)?.value?.trim()||'',
  }));
  const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({budgets})});
  const d=await r.json();
  if(d.ok){toast('✅ Tarifs sauvegardés !');_tarifs=d.config.budgets;renderTarifs();}
  else toast('❌ Erreur : '+(d.msg||'?'),false);
}
async function doBackup(){
  toast('⏳ Backup en cours…');
  const r=await fetch('/api/backup',{method:'POST'});
  const d=await r.json();
  toast(d.ok?'✅ Backup envoyé sur Telegram !':'❌ Erreur backup',d.ok);
}

// ── GENERATE MODAL ────────────────────────────────────────
let _genPoll=null;
function openGenModal(){document.getElementById('genModal').classList.add('open'); $('genLog').textContent='Prêt à générer…';}

// ── GRAB GEN MODAL ────────────────────────────────────────
let _ggPoll=null;
function openGrabGenModal(){
  document.getElementById('grabGenModal').classList.add('open');
  $('ggLog').textContent='Remplis les champs puis clique sur Créer le compte.';
  $('ggRunBtn').disabled=false;
  // Pré-remplit depuis .env si dispo
  fetch('/api/grabgen/config').then(r=>r.json()).then(d=>{
    if(d.onoff_email) $('ggOnoffEmail').value=d.onoff_email;
  });
}
function closeGrabGenModal(){
  document.getElementById('grabGenModal').classList.remove('open');
  if(_ggPoll){clearInterval(_ggPoll);_ggPoll=null;}
}
async function runGrabGen(){
  const payload={
    icloud_email: $('ggIcloud').value.trim(),
    onoff_email:  $('ggOnoffEmail').value.trim(),
    onoff_pass:   $('ggOnoffPass').value.trim(),
    phone:        $('ggPhone').value.trim(),
    channel:      $('ggChannel').value,
  };
  if(!payload.onoff_email||!payload.onoff_pass||!payload.phone){
    toast('⚠ Email OnOff, mot de passe et numéro requis',false); return;
  }
  $('ggRunBtn').disabled=true;
  $('ggLog').textContent='🚀 Pipeline lancé… ⏳ Ouverture Grab + connexion OnOff…';
  const r=await fetch('/api/grabgen/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json();
  if(!d.ok){toast('❌ '+d.msg,false);$('ggRunBtn').disabled=false;return;}
  // Poll statut
  _ggPoll=setInterval(async()=>{
    const sr=await fetch('/api/grabgen/status'); const sd=await sr.json();
    $('ggLog').textContent=sd.log||'';
    const el=$('ggLog'); el.scrollTop=el.scrollHeight;
    if(!sd.running){
      clearInterval(_ggPoll);_ggPoll=null;
      $('ggRunBtn').disabled=false;
      if(sd.last_result){
        toast('🎉 Compte Grab créé !');
        loadAccounts();
      } else {
        toast('⚠ Pipeline terminé — vérifier les logs',false);
      }
    }
  },3000);
}
function closeGenModal(){document.getElementById('genModal').classList.remove('open');if(_genPoll){clearInterval(_genPoll);_genPoll=null;}}
async function startGen(){
  const n=parseInt($('genCount').value)||5;
  $('genStartBtn').disabled=true;
  $('genLog').textContent='Lancement…';
  const r=await fetch('/api/generate/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:n})});
  const d=await r.json();
  if(!d.ok){toast(d.msg||'Erreur',false);$('genStartBtn').disabled=false;return;}
  _genPoll=setInterval(async()=>{
    const sr=await fetch('/api/generate/status'); const sd=await sr.json();
    $('genLog').textContent=sd.log||'';
    const el=$('genLog'); el.scrollTop=el.scrollHeight;
    if(!sd.running){clearInterval(_genPoll);_genPoll=null;$('genStartBtn').disabled=false;toast('✅ Génération terminée !');loadAccounts();}
  },1000);
}

// ── ORCHESTRATEUR ─────────────────────────────────────────
let _orchPoll = null;

async function orchStart(){
  const r=await fetch('/api/orch/start',{method:'POST'}); const d=await r.json();
  if(d.ok){toast('🏭 Usine démarrée !');orchStartPolling();}
  else toast('⚠ '+d.msg,false);
}
async function orchStop(){
  await fetch('/api/orch/stop',{method:'POST'});
  toast('⏹ Usine arrêtée');
}
function orchStartPolling(){
  if(_orchPoll)clearInterval(_orchPoll);
  _orchPoll=setInterval(orchRefresh,3000);
  orchRefresh();
}
async function orchRefresh(){
  try{
    const r=await fetch('/api/orch/status'); const s=await r.json();
    // Boutons
    const startBtn=$('orchStartBtn'); const stopBtn=$('orchStopBtn');
    if(startBtn) startBtn.style.display=s.running?'none':'inline-flex';
    if(stopBtn) stopBtn.style.display=s.running?'inline-flex':'none';
    // Stats
    if($('orchTotal')) $('orchTotal').textContent=s.total_created||0;
    if($('orchFailed')) $('orchFailed').textContent=s.total_failed||0;
    if($('orchSpeed')) $('orchSpeed').textContent=(s.speed||0)+' comptes/h';
    const workers=Object.values(s.workers||{});
    if($('orchWorkers')) $('orchWorkers').textContent=workers.filter(w=>w.status!=='stopped').length;
    // Workers table
    const tbody=$('orchWorkersTable');
    if(tbody&&workers.length){
      const statusEmoji={waiting_email:'⏳',buying_phone:'💳',registering:'🤖',idle:'✅',error:'❌',stopped:'⏹',starting:'🔄'};
      tbody.innerHTML=workers.map((w,i)=>`<tr>
        <td class="mono" style="color:var(--purple)">device-${i+1}</td>
        <td>${statusEmoji[w.status]||'❓'} ${w.status}</td>
        <td style="color:var(--t3);font-size:.75rem">${escHtml(w.current_email||'—')}</td>
        <td style="color:var(--green);font-family:monospace;font-size:.78rem">${escHtml(w.current_phone||'—')}</td>
        <td style="color:var(--green)">${w.created}</td>
        <td style="color:var(--orange)">${w.failed}</td>
      </tr>`).join('');
    }
    // Refresh packs table pendant que l'usine tourne
    if(s.running) loadPacks();
    // Devices count
    try{
      const dr=await fetch('/api/orch/devices'); const dd=await dr.json();
      if($('orchDevices')) $('orchDevices').textContent=(dd.devices||[]).length;
    }catch(e){}
    // Log
    const logEl=$('orchLog');
    if(logEl){logEl.textContent=(s.log||[]).join('\\n');logEl.scrollTop=logEl.scrollHeight;}
  }catch(e){}
}

// ── RECENT ACTIVITY ───────────────────────────────────────
function renderRecentActivity(){
  const el=document.getElementById('recentActivity'); if(!el)return;
  const events=[];
  Object.entries(_orders).forEach(([ref,o])=>{
    events.push({ts:o.ts||'',icon:'📦',text:`Commande ${ref} — ${o.nom||'?'} · ${o.prix||0}฿`});
  });
  Object.entries(_msgs).forEach(([uid,c])=>{
    const last=c.messages?.slice(-1)[0];
    if(last&&last.from==='client') events.push({ts:last.ts||'',icon:'💬',text:`${c.name||uid} : ${(last.text||'').slice(0,40)}`});
  });
  events.sort((a,b)=>b.ts.localeCompare(a.ts));
  if(!events.length){el.innerHTML='<div style="color:var(--t3);font-size:.85rem;text-align:center;padding:20px">Aucune activité récente</div>';return;}
  el.innerHTML=events.slice(0,6).map(e=>`
    <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--s3)40">
      <span style="font-size:1rem">${escHtml(e.icon)}</span>
      <div style="font-size:.8rem;color:var(--t2);flex:1">${escHtml(e.text)}</div>
    </div>`).join('');
}

// ── UTILS ─────────────────────────────────────────────────
function escHtml(t){return (t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ── POLLING ───────────────────────────────────────────────
async function refresh(){
  await Promise.all([loadStats(), loadOrders(), loadMsgs()]);
  renderRecentActivity();
}
async function refreshAll(){
  await refresh();
  await Promise.all([loadDispo(), loadBotStatus(), loadRestoCount(), loadTarifs()]);
  // iCloud count mini-card (quick update without full accounts reload)
  try{
    const r=await fetch('/api/accounts'); const d=await r.json();
    const avail=(d.accounts||[]).filter(a=>a.status==='available').length;
    const total=(d.accounts||[]).length;
    const el=$('icloud-count-card');
    if(el){el.textContent=avail+'/'+total+' disponibles';el.style.color=avail>0?'var(--green)':'var(--orange)';}
  }catch(e){}
}
// ── HASH NAVIGATION ──────────────────────────────────────
(function(){
  const pages = ['overview','orders','chat','accounts'];
  function hashNav(){
    const h = window.location.hash.replace('#','');
    if(pages.includes(h)) nav(h);
  }
  window.addEventListener('hashchange', hashNav);
  // Apply on load
  hashNav();
  // Update hash when nav is clicked
  const _origNav = nav;
  window.nav = function(p){ _origNav(p); history.replaceState(null,'','#'+p); };
})();
refreshAll();
setInterval(refresh, 15000);
setInterval(()=>{
  Promise.all([loadDispo(),loadBotStatus(),loadRestoCount()]);
  // Auto-refresh comptes si sur la page accounts
  if(_page==='accounts') loadPacks();
  // Mettre à jour le compteur iCloud
  try{fetch('/api/accounts').then(r=>r.json()).then(d=>{
    const avail=(d.accounts||[]).filter(a=>a.status==='available').length;
    const total=(d.accounts||[]).length;
    const el=$('icloud-count-card');
    if(el){el.textContent=avail+'/'+total+' disponibles';el.style.color=avail>0?'var(--green)':'var(--orange)';}
  });}catch(e){}
}, 30000);
</script>
</body>
</html>"""

EMPLOYE_LOGIN = """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GrabDiscount — Espace Employé</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080b12;--s2:#111827;--s3:#1f2937;--green:#00b14f;--red:#ef4444;--t1:#f9fafb;--t3:#6b7280}
body{background:var(--bg);display:flex;align-items:center;justify-content:center;min-height:100vh;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.box{background:var(--s2);border:1px solid var(--s3);border-radius:20px;padding:48px 40px;width:380px;text-align:center}
.logo{font-size:3.5rem;margin-bottom:16px}
h1{color:var(--t1);font-size:1.4rem;font-weight:700;margin-bottom:4px}
.sub{color:var(--t3);font-size:.875rem;margin-bottom:32px}
input{width:100%;background:#0d1117;border:1px solid var(--s3);border-radius:12px;padding:14px 16px;
color:var(--t1);font-size:1rem;outline:none;margin-bottom:12px;transition:.2s}
input:focus{border-color:var(--green);box-shadow:0 0 0 3px #00b14f15}
button{width:100%;background:var(--green);border:none;border-radius:12px;padding:14px;color:#fff;
font-size:1rem;font-weight:700;cursor:pointer;transition:.2s}
button:hover{background:#009940}
button:disabled{opacity:.5;cursor:not-allowed}
.err{color:var(--red);font-size:.85rem;margin-bottom:12px;background:#7f1d1d22;border:1px solid #7f1d1d44;
border-radius:8px;padding:10px;display:none}
</style></head><body>
<div class="box">
  <div class="logo">🛵</div>
  <h1>GrabDiscount</h1>
  <div class="sub">Espace Employé — Création de comptes</div>
  <div class="err" id="errMsg"></div>
  <form id="loginForm">
    <input type="password" id="pwdInput" name="pwd" placeholder="Mot de passe employé" autofocus>
    <button type="submit" id="loginBtn">Accéder →</button>
  </form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const btn = document.getElementById('loginBtn');
  const err = document.getElementById('errMsg');
  const pwd = document.getElementById('pwdInput').value;
  btn.disabled = true; btn.textContent = '⏳'; err.style.display = 'none';
  try{
    const r = await fetch('/employe/login', {
      method:'POST',
      headers:{'Content-Type':'application/x-www-form-urlencoded'},
      credentials:'include',
      body:'pwd='+encodeURIComponent(pwd)
    });
    const d = await r.json();
    if(d.ok){ window.location.href = '/employe'; }
    else{
      err.textContent = d.error || 'Mot de passe incorrect';
      err.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Accéder →';
    }
  } catch(ex){
    err.textContent = 'Erreur réseau : '+ex.message;
    err.style.display = 'block';
    btn.disabled = false; btn.textContent = 'Accéder →';
  }
});
</script>
</body></html>"""

EMPLOYE_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GrabDiscount — Espace Employé</title>
<style>
:root{--bg:#080b12;--s1:#0d1117;--s2:#111827;--s3:#1f2937;--s4:#374151;
  --t1:#f9fafb;--t2:#9ca3af;--t3:#6b7280;--green:#00b14f;--blue:#3b82f6;
  --orange:#f59e0b;--red:#ef4444;--purple:#8b5cf6;--cyan:#06b6d4}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--t1);min-height:100vh}
.header{background:var(--s1);border-bottom:1px solid var(--s3);padding:14px 24px;
  display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:100}
.header-brand{display:flex;align-items:center;gap:10px;flex:1}
.header-logo{font-size:1.5rem}
.header-title{font-size:1rem;font-weight:800}
.header-sub{font-size:.7rem;color:var(--t3)}
.btn-logout{padding:7px 14px;border-radius:8px;border:1px solid var(--s3);background:none;
  color:var(--t3);cursor:pointer;font-size:.8rem;transition:.15s;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.btn-logout:hover{color:var(--red);border-color:var(--red)}
.content{padding:24px;max-width:1200px;margin:0 auto}
.filter-bar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
.filter-pill{padding:6px 14px;border-radius:99px;font-size:.8rem;cursor:pointer;
  border:1px solid var(--s3);background:var(--s2);color:var(--t2);transition:.15s}
.filter-pill:hover,.filter-pill.active{background:var(--green);color:#fff;border-color:var(--green)}
.table-wrap{background:var(--s2);border:1px solid var(--s3);border-radius:14px;overflow:hidden}
.table-header{padding:14px 20px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:12px}
.table-title{font-size:.9rem;font-weight:700}
table{width:100%;border-collapse:collapse}
th{font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);
   padding:10px 14px;text-align:left;border-bottom:1px solid var(--s3);background:var(--s1)}
td{padding:12px 14px;border-bottom:1px solid #0d111780;font-size:.84rem;color:var(--t2);vertical-align:top}
tr:last-child td{border:none}
.mono{font-family:monospace;font-size:.78rem}
.pill{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:99px;
  font-size:.7rem;font-weight:600;white-space:nowrap}
.pill-green{background:#00b14f18;color:var(--green)}
.pill-orange{background:#f59e0b18;color:var(--orange)}
.pill-blue{background:#3b82f618;color:var(--blue)}
.pill-gray{background:var(--s3);color:var(--t3)}
.btn{padding:6px 13px;border-radius:7px;border:none;font-size:.78rem;font-weight:600;
  cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:5px}
.btn:hover{filter:brightness(1.1);transform:translateY(-1px)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn-primary{background:var(--green);color:#fff}
.btn-secondary{background:var(--s3);color:var(--t1)}
.btn-blue{background:var(--blue);color:#fff}
.btn-danger{background:#ef444420;color:var(--red);border:1px solid #ef444430}
.btn-sm{padding:4px 10px;font-size:.72rem}
.input{background:var(--s1);border:1px solid var(--s3);border-radius:7px;padding:7px 11px;
  color:var(--t1);font-size:.82rem;outline:none;transition:.2s}
.input:focus{border-color:var(--green)}
.input::placeholder{color:var(--t3)}
/* SLIDE PANEL */
.slide-overlay{position:fixed;inset:0;background:#00000080;z-index:200;opacity:0;pointer-events:none;transition:.2s}
.slide-overlay.open{opacity:1;pointer-events:all}
.slide-panel{position:fixed;right:0;top:0;bottom:0;width:520px;background:var(--s1);
  border-left:1px solid var(--s3);z-index:201;transform:translateX(100%);transition:.25s;overflow-y:auto;
  display:flex;flex-direction:column}
.slide-panel.open{transform:translateX(0)}
.slide-header{padding:18px 22px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:10px;flex-shrink:0}
.slide-body{padding:20px;flex:1;overflow-y:auto}
.slide-section{background:var(--s2);border-radius:12px;padding:14px;margin-bottom:12px}
.slide-section h4{font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--t3);margin-bottom:10px}
/* TOAST */
.toast-wrap{position:fixed;bottom:20px;right:20px;z-index:999;display:flex;flex-direction:column;gap:8px}
.toast{background:var(--s2);border:1px solid var(--s3);border-radius:10px;padding:12px 18px;
  font-size:.84rem;min-width:200px;transform:translateX(120%);transition:.3s;box-shadow:0 6px 20px #00000060}
.toast.show{transform:translateX(0)}
.toast.ok{border-color:#00b14f60;color:var(--green)}
.toast.err{border-color:#ef444460;color:var(--red)}
/* MAIL PANEL */
.mail-item{background:var(--s1);border:1px solid var(--s3);border-radius:10px;padding:12px;margin-bottom:8px}
.mail-item.grab{border-color:#00b14f40;background:#00b14f08}
.mail-from{font-size:.78rem;color:var(--t3);margin-bottom:2px}
.mail-subject{font-size:.86rem;font-weight:600;color:var(--t1);margin-bottom:4px}
.mail-preview{font-size:.76rem;color:var(--t2);line-height:1.4}
.mail-date{font-size:.7rem;color:var(--t3);margin-top:4px}
.empty{text-align:center;padding:40px 20px;color:var(--t3)}
.loading{text-align:center;padding:20px;color:var(--t3);font-size:.85rem}
@media(max-width:768px){
  .content{padding:12px}
  .slide-panel{width:100%}
  table{display:block;overflow-x:auto}
  th,td{white-space:nowrap}
}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="header-brand">
    <span class="header-logo">🛵</span>
    <div>
      <div class="header-title">GrabDiscount</div>
      <div class="header-sub">Espace Employé</div>
    </div>
  </div>
  <a href="#" onclick="logout()" class="btn-logout">🚪 Déconnexion</a>
</div>

<!-- MAIN CONTENT -->
<div class="content">
  <div style="margin-bottom:16px">
    <div style="font-size:1.1rem;font-weight:700;margin-bottom:4px">Comptes à créer</div>
    <div style="font-size:.82rem;color:var(--t3)">Prenez un compte en charge, entrez le numéro SMSPool, créez le compte Grab, validez.</div>
  </div>

  <!-- Filtres -->
  <div class="filter-bar">
    <span class="filter-pill active" onclick="setFilter(this,'all')">Tous mes comptes</span>
    <span class="filter-pill" onclick="setFilter(this,'available')">📧 Disponibles</span>
    <span class="filter-pill" onclick="setFilter(this,'claimed')">🔒 Mes comptes en cours</span>
  </div>

  <!-- Tableau -->
  <div class="table-wrap">
    <div class="table-header">
      <span class="table-title">📦 Comptes disponibles</span>
      <span class="pill pill-blue" id="countBadge" style="margin-left:8px">{{ accounts|length }}</span>
      <button class="btn btn-secondary btn-sm" style="margin-left:auto" onclick="loadAccounts()">🔄 Actualiser</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>Email iCloud</th>
          <th>Identité + MDP</th>
          <th>Adresse Bangkok</th>
          <th>Statut</th>
          <th style="width:180px">Actions</th>
        </tr>
      </thead>
      <tbody id="accountsTable">
        {% for a in accounts %}
        <tr>
          <td><div class="mono" style="color:var(--purple)">{{ a.email }}</div></td>
          <td>
            <div style="font-weight:600;color:var(--t1)">{{ a.full_name }}</div>
            <div style="font-size:.72rem;color:var(--t3)">🔑 <span class="mono">Grab2024lol!</span></div>
            {% if a.phone %}<div style="font-size:.72rem;color:var(--green);margin-top:2px">📱 {{ a.phone }}</div>{% endif %}
          </td>
          <td style="font-size:.74rem;color:var(--t3)">📍 {{ a.bangkok_addr[:55] }}{% if a.bangkok_addr|length > 55 %}…{% endif %}</td>
          <td>
            {% if a.status == 'available' %}<span class="pill pill-orange">📧 Disponible</span>
            {% elif a.status == 'claimed' %}<span class="pill pill-blue">🔒 En cours</span>
            {% elif a.status in ('full','grab_ready') %}<span class="pill pill-green">✅ Prêt</span>
            {% else %}<span class="pill pill-gray">{{ a.status }}</span>{% endif %}
          </td>
          <td>
            {% if a.status == 'available' %}
              <button class="btn btn-primary btn-sm" onclick="claimAccount('{{ a.email }}')">🤚 Prendre en charge</button>
            {% elif a.claimed_by %}
              <button class="btn btn-blue btn-sm" onclick="openPanel('{{ a.email }}')">⚙️ Gérer</button>
            {% endif %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="5"><div class="empty">📭 Aucun compte disponible</div></td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <div style="margin-top:14px;font-size:.76rem;color:var(--t3);text-align:right">
    Mot de passe Grab par défaut : <span class="mono" style="color:var(--t2)">Grab2024lol!</span>
  </div>
</div>

<!-- SLIDE PANEL — Gestion compte -->
<div class="slide-overlay" id="slideOverlay" onclick="closePanel()"></div>
<div class="slide-panel" id="slidePanel">
  <div class="slide-header">
    <div style="flex:1">
      <div class="mono" style="color:var(--purple);font-weight:700;font-size:.9rem" id="spEmail">—</div>
      <div style="font-size:.73rem;color:var(--t3);margin-top:2px" id="spName">—</div>
    </div>
    <span id="spStatusPill"></span>
    <button class="btn btn-secondary btn-sm" onclick="closePanel()">✕</button>
  </div>
  <div class="slide-body" id="slideBody">
    <!-- rempli dynamiquement -->
  </div>
</div>

<!-- MAIL PANEL (modal) -->
<div class="slide-overlay" id="mailOverlay" onclick="closeMails()"></div>
<div class="slide-panel" id="mailPanel" style="width:480px">
  <div class="slide-header">
    <div style="flex:1">
      <div style="font-weight:700">📧 Mails iCloud</div>
      <div class="mono" style="font-size:.75rem;color:var(--t3)" id="mailForEmail">—</div>
    </div>
    <button class="btn btn-secondary btn-sm" onclick="refreshMails()">🔄</button>
    <button class="btn btn-secondary btn-sm" style="margin-left:6px" onclick="closeMails()">✕</button>
  </div>
  <div class="slide-body" id="mailBody">
    <div class="loading">Chargement des mails…</div>
  </div>
</div>

<!-- TOAST -->
<div class="toast-wrap" id="toastWrap"></div>

<script>
// Données injectées côté serveur — pas de fetch nécessaire au chargement
const _ACCOUNTS_INIT = {{ accounts_json | safe }};

// Helper fetch — le cookie emp_tok est envoyé automatiquement par le navigateur
function authFetch(url, opts={}){
  opts.credentials = 'include';
  return fetch(url, opts);
}

// ── STATE ────────────────────────────────────────────────
let _accounts = [];
let _filter = 'all';
let _currentEmail = null;
let _mailEmail = null;

// ── UTILS ────────────────────────────────────────────────
function $(id){ return document.getElementById(id); }
function escHtml(t){ return (t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function jsq(t){ return escHtml(t||''); }

let _tid = 0;
function toast(msg, ok=true){
  const id = 't'+(++_tid);
  const d = $('toastWrap');
  d.insertAdjacentHTML('beforeend', `<div class="toast ${ok?'ok':'err'}" id="${id}">${msg}</div>`);
  setTimeout(()=>document.getElementById(id)?.classList.add('show'), 10);
  setTimeout(()=>{ const el=document.getElementById(id); if(el){el.classList.remove('show');setTimeout(()=>el.remove(),300);} }, 3500);
}

function statusPill(status){
  const m = {
    'available': '<span class="pill pill-orange">📧 Disponible</span>',
    'claimed':   '<span class="pill pill-blue">🔒 En cours</span>',
    'full':      '<span class="pill pill-green">✅ Full</span>',
    'grab_ready':'<span class="pill pill-green">✅ Prêt</span>',
    'used':      '<span class="pill pill-gray">✓ Utilisé</span>',
  };
  return m[status] || `<span class="pill pill-gray">${status}</span>`;
}

// ── FILTER ───────────────────────────────────────────────
function setFilter(el, f){
  document.querySelectorAll('.filter-pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  _filter = f;
  renderAccounts();
}

function filteredAccounts(){
  if(_filter === 'all') return _accounts;
  return _accounts.filter(a => a.status === _filter);
}

// ── LOAD ─────────────────────────────────────────────────
async function loadAccounts(){
  // Rechargement dynamique (bouton Actualiser)
  const tbody = $('accountsTable');
  try{
    const r = await authFetch('/api/employe/accounts');
    if(r.status === 401){ window.location.href = '/employe/login'; return; }
    const d = await r.json();
    if(!d.ok){
      if(tbody) tbody.innerHTML=`<tr><td colspan="5"><div class="empty">❌ Erreur : ${d.error||'inconnue'}</div></td></tr>`;
      return;
    }
    _accounts = d.accounts || [];
    renderAccounts();
  } catch(e){
    if(tbody) tbody.innerHTML=`<tr><td colspan="5"><div class="empty">❌ Erreur réseau : ${e.message}</div></td></tr>`;
  }
}

// ── RENDER ───────────────────────────────────────────────
function renderAccounts(){
  const tbody = $('accountsTable');
  if(!tbody) return;
  const list = filteredAccounts();
  $('countBadge').textContent = list.length;
  if(!list.length){
    tbody.innerHTML = '<tr><td colspan="5"><div class="empty">📭 Aucun compte disponible pour le moment</div></td></tr>';
    return;
  }
  tbody.innerHTML = list.map(a => {
    const e = escHtml(a.email || '');
    const name = escHtml(a.full_name || `${a.prenom} ${a.nom}`);
    const addr = escHtml((a.bangkok_addr || '').slice(0, 55));
    const addrFull = a.bangkok_addr || '';
    const isMine = a.claimed_by && a.claimed_by !== null;
    const hasPhone = !!a.phone;

    let actionBtn = '';
    if(a.status === 'available'){
      actionBtn = `<button class="btn btn-primary btn-sm" onclick="claimAccount('${e}')">🤚 Prendre en charge</button>`;
    } else if(a.status === 'claimed'){
      actionBtn = `<button class="btn btn-blue btn-sm" onclick="openPanel('${e}')">⚙️ Gérer</button>`;
    }

    return `<tr>
      <td>
        <div class="mono" style="color:var(--purple)">${e}</div>
        ${a.claimed_at ? `<div style="font-size:.7rem;color:var(--t3);margin-top:2px">Pris le ${escHtml(a.claimed_at.slice(0,10))}</div>` : ''}
      </td>
      <td>
        <div style="font-weight:600;color:var(--t1)">${name}</div>
        <div style="font-size:.72rem;color:var(--t3)">🔑 <span class="mono">Grab2024lol!</span></div>
        ${hasPhone ? `<div style="font-size:.72rem;color:var(--green);margin-top:2px">📱 ${escHtml(a.phone)}</div>` : ''}
      </td>
      <td style="font-size:.74rem;color:var(--t3)" title="${escHtml(addrFull)}">📍 ${addr}${addrFull.length > 55 ? '…' : ''}</td>
      <td>${statusPill(a.status)}</td>
      <td>${actionBtn}</td>
    </tr>`;
  }).join('');
}

// ── CLAIM ────────────────────────────────────────────────
async function claimAccount(email){
  const r = await authFetch('/api/employe/claim', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email})});
  const d = await r.json();
  if(d.ok){ toast('✅ Compte pris en charge !'); await loadAccounts(); openPanel(email); }
  else toast('❌ ' + (d.error || 'Erreur'), false);
}

// ── PANEL ────────────────────────────────────────────────
function openPanel(email){
  const acc = _accounts.find(a => a.email === email);
  if(!acc) return;
  _currentEmail = email;
  $('spEmail').textContent = email;
  $('spName').textContent = acc.full_name || `${acc.prenom} ${acc.nom}`;
  $('spStatusPill').innerHTML = statusPill(acc.status);
  renderPanel(acc);
  $('slideOverlay').classList.add('open');
  $('slidePanel').classList.add('open');
}

function renderPanel(acc){
  const email = acc.email || '';
  const name = acc.full_name || (acc.prenom && acc.nom ? acc.prenom+' '+acc.nom : '');
  const addr = acc.bangkok_addr || '';
  const phone = acc.phone || '';
  const hasPhone = !!acc.phone;
  const isReady = acc.status === 'grab_ready' || acc.status === 'full';

  // Store values for copy buttons — no escaping needed in onclick
  window._pd = { email: email, name: name, addr: addr };

  function stepIcon(done){ return done ? '✅' : '⬜'; }

  $('slideBody').innerHTML = `
    <!-- Progress -->
    <div class="slide-section" style="background:var(--s3)">
      <h4>📋 Étapes de création</h4>
      <div style="display:flex;flex-direction:column;gap:5px;font-size:.82rem;margin-top:4px">
        <div>✅ <span style="color:var(--green)">1. Compte pris en charge</span></div>
        <div>⬜ <span style="color:var(--t2)">2. Créer le compte sur Grab (app)</span></div>
        <div>${stepIcon(hasPhone)} <span style="color:${hasPhone?'var(--green)':'var(--t2)'}">3. Entrer le numéro de téléphone</span></div>
        <div>${stepIcon(isReady)} <span style="color:${isReady?'var(--green)':'var(--t2)'}">4. Valider le compte</span></div>
      </div>
    </div>

    <!-- Identité -->
    <div class="slide-section">
      <h4>👤 Identité — à copier dans Grab</h4>
      <div style="display:flex;flex-direction:column;gap:8px">

        <div style="background:var(--s1);border-radius:8px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px">
          <div>
            <div style="font-size:.68rem;color:var(--t3);margin-bottom:2px">EMAIL</div>
            <div class="mono" style="color:var(--purple);font-size:.85rem">${escHtml(email)}</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="copyText(window._pd.email)">📋 Copier</button>
        </div>

        <div style="background:var(--s1);border-radius:8px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px">
          <div>
            <div style="font-size:.68rem;color:var(--t3);margin-bottom:2px">MOT DE PASSE</div>
            <div class="mono" style="color:var(--cyan);font-size:.9rem;font-weight:700">Grab2024lol!</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="copyText('Grab2024lol!')">📋 Copier</button>
        </div>

        <div style="background:var(--s1);border-radius:8px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px">
          <div>
            <div style="font-size:.68rem;color:var(--t3);margin-bottom:2px">NOM COMPLET</div>
            <div style="color:var(--t1);font-weight:600;font-size:.88rem">${escHtml(name)}</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="copyText(window._pd.name)">📋 Copier</button>
        </div>

        <div style="background:var(--s1);border-radius:8px;padding:10px 12px">
          <div style="font-size:.68rem;color:var(--t3);margin-bottom:4px">ADRESSE BANGKOK</div>
          <div style="color:var(--t2);font-size:.78rem;line-height:1.5;margin-bottom:8px">${escHtml(addr)}</div>
          <button class="btn btn-secondary btn-sm" onclick="copyText(window._pd.addr)">📋 Copier l'adresse</button>
        </div>

      </div>
    </div>

    <!-- Numéro de téléphone -->
    <div class="slide-section">
      <h4>📱 Étape 3 — Numéro de téléphone</h4>
      <div style="font-size:.78rem;color:var(--t3);margin-bottom:8px">
        Numéro thaï utilisé lors de la création du compte Grab (+66XXXXXXXXX).
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <input class="input" id="phoneInput" type="tel" placeholder="+66XXXXXXXXX"
          value="${escHtml(phone)}" style="flex:1"
          onkeydown="if(event.key==='Enter')savePhone()">
        <button class="btn btn-primary btn-sm" onclick="savePhone()">💾 Sauvegarder</button>
      </div>
      ${hasPhone ? '<div style="font-size:.72rem;color:var(--green);margin-top:6px">✅ Numéro enregistré : '+escHtml(phone)+'</div>' : ''}
    </div>

    <!-- Mails iCloud inline -->
    <div class="slide-section">
      <h4>📧 Mails iCloud <button class="btn btn-secondary btn-sm" style="margin-left:8px" onclick="loadInlineMails()">🔄 Charger</button></h4>
      <div id="inlineMails" style="margin-top:8px">
        <div style="font-size:.78rem;color:var(--t3)">Cliquez sur 🔄 Charger pour voir les codes OTP Grab.</div>
      </div>
    </div>

    <!-- Validation -->
    <div class="slide-section" style="border:1px solid ${hasPhone?'#00b14f40':'var(--s4)'}">
      <h4>✅ Étape 4 — Valider le compte Grab</h4>
      <div style="font-size:.78rem;color:var(--t3);margin-bottom:10px">
        Compte Grab créé et vérifié ? Cliquez pour le marquer comme prêt à l'emploi.
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" id="validateBtn" onclick="validateAccount()"
          ${hasPhone ? '' : 'disabled'} style="flex:1;padding:10px">
          🎉 Compte Grab créé — Valider
        </button>
        <button class="btn btn-danger btn-sm" onclick="unclaimAccount()" title="Libérer sans valider">↩ Libérer</button>
      </div>
      ${hasPhone ? '' : '<div style="font-size:.72rem;color:var(--orange);margin-top:8px">⚠ Enregistrez dabord le numero (etape 3)</div>'}
    </div>
  `;
}

async function loadInlineMails(){
  if(!_currentEmail) return;
  const box = $('inlineMails');
  box.innerHTML = '<div style="font-size:.78rem;color:var(--t3)">⏳ Chargement…</div>';
  try{
    const r = await authFetch('/api/employe/mails/' + encodeURIComponent(_currentEmail));
    const d = await r.json();
    if(!d.ok){
      box.innerHTML = `<div style="font-size:.78rem;color:var(--red)">❌ ${escHtml(d.error||'Erreur')}</div>`;
      return;
    }
    const mails = d.mails || [];
    if(!mails.length){ box.innerHTML = '<div style="font-size:.78rem;color:var(--t3)">📭 Aucun mail</div>'; return; }
    box.innerHTML = mails.slice(0,6).map(m => `
      <div class="mail-item ${m.is_grab?'grab':''}" style="margin-bottom:6px">
        ${m.is_grab ? '<div style="font-size:.68rem;color:var(--green);font-weight:700;margin-bottom:2px">🟢 Grab / Vérification</div>' : ''}
        <div style="font-size:.72rem;color:var(--t3)">De : ${escHtml(m.from||'')}</div>
        <div style="font-size:.84rem;font-weight:600;color:var(--t1)">${escHtml(m.subject||'(sans sujet)')}</div>
        ${m.preview ? `<div style="font-size:.76rem;color:var(--t2);margin-top:3px;line-height:1.4">${escHtml(m.preview)}</div>` : ''}
        <div style="font-size:.68rem;color:var(--t3);margin-top:3px">${escHtml(m.date||'')}</div>
      </div>`).join('');
  } catch(e){
    box.innerHTML = `<div style="font-size:.78rem;color:var(--red)">❌ ${escHtml(e.message)}</div>`;
  }
}

function closePanel(){
  $('slideOverlay').classList.remove('open');
  $('slidePanel').classList.remove('open');
  _currentEmail = null;
}

// ── PHONE ────────────────────────────────────────────────
async function savePhone(){
  const phone = ($('phoneInput')?.value || '').trim();
  if(!phone){ toast('⚠ Entrez un numéro', false); return; }
  const r = await authFetch('/api/employe/set_phone', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email: _currentEmail, phone})});
  const d = await r.json();
  if(d.ok){
    toast('✅ Numéro enregistré !');
    await loadAccounts();
    // Rafraîchir le panel
    const acc = _accounts.find(a => a.email === _currentEmail);
    if(acc){ acc.phone = phone; renderPanel(acc); }
    // Activer le bouton valider
    const vb = $('validateBtn');
    if(vb) vb.disabled = false;
  } else toast('❌ ' + (d.error || 'Erreur'), false);
}

// ── UNCLAIM ──────────────────────────────────────────────
async function unclaimAccount(){
  if(!_currentEmail) return;
  if(!confirm('Libérer ce compte ?')) return;
  const r = await authFetch('/api/employe/unclaim', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email: _currentEmail})});
  const d = await r.json();
  if(d.ok){ toast('✅ Compte libéré'); closePanel(); await loadAccounts(); }
  else toast('❌ ' + (d.error || 'Erreur'), false);
}

// ── VALIDATE ─────────────────────────────────────────────
async function validateAccount(){
  if(!_currentEmail) return;
  const r = await authFetch('/api/employe/validate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email: _currentEmail})});
  const d = await r.json();
  if(d.ok){
    toast('🎉 Compte validé comme Grab Ready !');
    closePanel();
    await loadAccounts();
  } else toast('❌ ' + (d.error || 'Erreur'), false);
}

// ── MAILS ────────────────────────────────────────────────
function openMails(email){
  _mailEmail = email;
  $('mailForEmail').textContent = email;
  $('mailOverlay').classList.add('open');
  $('mailPanel').classList.add('open');
  refreshMails();
}

async function refreshMails(){
  if(!_mailEmail) return;
  $('mailBody').innerHTML = '<div class="loading">⏳ Chargement des mails…</div>';
  try{
    const r = await authFetch('/api/employe/mails/' + encodeURIComponent(_mailEmail));
    const d = await r.json();
    if(!d.ok){
      $('mailBody').innerHTML = `<div class="empty">❌ ${escHtml(d.error || 'Erreur')}<br><span style="font-size:.75rem;margin-top:8px;display:block">Le cookie iCloud est peut-être expiré.</span></div>`;
      return;
    }
    const mails = d.mails || [];
    if(!mails.length){
      $('mailBody').innerHTML = '<div class="empty">📭 Aucun mail reçu</div>';
      return;
    }
    $('mailBody').innerHTML = mails.map(m => `
      <div class="mail-item ${m.is_grab?'grab':''}">
        ${m.is_grab ? '<div style="font-size:.7rem;color:var(--green);font-weight:700;margin-bottom:4px">🟢 Mail Grab / Vérification</div>' : ''}
        <div class="mail-from">De : ${escHtml(m.from||'')}</div>
        <div class="mail-subject">${escHtml(m.subject||'(sans sujet)')}</div>
        ${m.preview ? `<div class="mail-preview">${escHtml(m.preview)}</div>` : ''}
        <div class="mail-date">${escHtml(m.date||'')}</div>
      </div>`).join('');
  } catch(e){
    $('mailBody').innerHTML = `<div class="empty">❌ Erreur réseau : ${escHtml(e.message)}</div>`;
  }
}

function closeMails(){
  $('mailOverlay').classList.remove('open');
  $('mailPanel').classList.remove('open');
  _mailEmail = null;
}

// ── COPY ─────────────────────────────────────────────────
function copyText(t){
  navigator.clipboard.writeText(t).then(()=>toast('📋 Copié !')).catch(()=>{
    const el = document.createElement('textarea');
    el.value = t; document.body.appendChild(el); el.select();
    document.execCommand('copy'); document.body.removeChild(el);
    toast('📋 Copié !');
  });
}

// ── LOGOUT ───────────────────────────────────────────────
function logout(){ window.location.href = '/employe/logout'; }

// ── INIT — données déjà dans la page, rendu immédiat ─────
_accounts = _ACCOUNTS_INIT;
renderAccounts();
setInterval(loadAccounts, 30000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", 5001)))
    a = p.parse_args()
    # Initialise config.json avec les valeurs par défaut si absent
    get_config()
    # Importe au démarrage les emails déjà générés mais pas encore dans accounts.json
    _reload_accounts()
    # Active l'auto-génération dès le démarrage (5 emails toutes les 65 min)
    _auto_gen["enabled"] = True
    _schedule_next()
    monitoring.schedule_daily_summary()
    print(f"🤖 Auto-génération iCloud HME activée — 5 emails toutes les 65 min")
    print(f"📊 Résumé quotidien Telegram activé — 8h Bangkok")
    print(f"🛵 GrabDiscount QG → http://localhost:{a.port}   |   pwd: {DASHBOARD_PWD}")
    from waitress import serve
    serve(app, host="0.0.0.0", port=a.port, threads=8)
