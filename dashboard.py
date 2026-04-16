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

from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for

app = Flask(__name__)
# Secret Flask : obligatoire depuis .env, jamais hardcodé
_secret = os.environ.get("DASHBOARD_SECRET")
if not _secret:
    import secrets as _s
    _secret = _s.token_urlsafe(32)   # généré aléatoirement si absent → sessions sécurisées
app.secret_key = _secret

BASE        = Path(__file__).parent
ORDERS_F    = BASE / "orders.json"
MESSAGES_F  = BASE / "messages.json"
ACCOUNTS_F  = BASE / "accounts.json"
EXPORT_F    = BASE / "icloud_gen" / "emails_export.txt"
STATUS_F    = BASE / "status.json"

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_ID      = int(os.environ.get("ADMIN_CHAT_ID", 0))
DASHBOARD_PWD = os.environ.get("DASHBOARD_PASSWORD")
if not DASHBOARD_PWD:
    raise RuntimeError("DASHBOARD_PASSWORD non défini dans .env — démarrage refusé.")

# ── Verrou I/O pour éviter les race conditions ─────────────
_io_lock = threading.Lock()

_gen_status = {"running": False, "log": "", "last_run": None}

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
    """Proxy la vérification de santé du bot (port 10000)."""
    bot_port = int(os.environ.get("PORT", 10000))
    try:
        r = requests.get(f"http://localhost:{bot_port}/health", timeout=3)
        return jsonify({"alive": r.status_code == 200, "msg": r.text})
    except Exception as e:
        return jsonify({"alive": False, "msg": str(e)})

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

    def _run():
        _gen_status["running"] = True
        _gen_status["log"] = "Lancement du générateur iCloud…\n"
        try:
            proc = subprocess.Popen(
                ["python3", str(BASE / "icloud_gen" / "run.py"), "generate"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(BASE)
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

def _reload_accounts():
    """Met à jour accounts.json depuis emails_export.txt après génération."""
    existing = {a["email"]: a for a in rj(ACCOUNTS_F, [])}
    try:
        for line in EXPORT_F.read_text().splitlines():
            line = line.strip()
            if "@icloud.com" not in line: continue
            parts = line.split("  ")
            email = parts[0].strip()
            if email not in existing:
                m = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", line)
                ts = datetime.datetime.strptime(m.group(1), "%d/%m/%Y %H:%M").strftime("%Y-%m-%dT%H:%M:%S") if m else datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                existing[email] = {"email": email, "created": ts, "status": "available", "grab_phone": "", "grab_notes": "", "used_at": None}
        wj(ACCOUNTS_F, list(existing.values()))
    except Exception as e:
        _gen_status["log"] += f"\n⚠ reload: {e}"

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
.main{flex:1;display:flex;flex-direction:column;height:100vh;overflow:hidden}
.topbar{padding:16px 24px;border-bottom:1px solid var(--s3);display:flex;align-items:center;gap:12px;flex-shrink:0}
.page-title{font-size:1.1rem;font-weight:700;color:var(--t1)}
.page-sub{font-size:.8rem;color:var(--t3);margin-left:auto}
.content{flex:1;overflow-y:auto;padding:24px}

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
  <div id="page-accounts" style="display:none">
    <div class="topbar">
      <span class="page-title">🍎 Comptes Grab — iCloud HME</span>
      <button class="btn btn-primary" style="margin-left:auto" onclick="openGenModal()">⚡ Générer un email</button>
    </div>
    <div class="content">
      <!-- Quota Apple -->
      <div class="quota-card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
          <div style="font-weight:700">Quota Apple HME</div>
          <div class="pill" id="quotaPill">—</div>
        </div>
        <div style="font-size:.8rem;color:var(--t3)" id="quotaSub">Chargement…</div>
        <div class="quota-bar-bg"><div class="quota-bar-fill" id="quotaBar" style="width:0%"></div></div>
        <div style="display:flex;justify-content:space-between;font-size:.75rem;color:var(--t3)">
          <span id="quotaUsed">0/5 aujourd'hui</span>
          <span id="quotaReset">Reset : —</span>
        </div>
      </div>

      <!-- Emails table -->
      <div class="table-wrap">
        <div class="table-header">
          <span class="table-title">Emails iCloud actifs</span>
          <span class="pill pill-green" id="emailCount" style="margin-left:8px">0</span>
        </div>
        <table>
          <thead><tr><th>Email iCloud</th><th>Créé le</th><th>Statut</th><th>Compte Grab</th><th>Actions</th></tr></thead>
          <tbody id="accountsTable"></tbody>
        </table>
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
    <h2>⚡ Générer un email iCloud HME</h2>
    <div class="sub">Chrome doit être ouvert et connecté à iCloud. Limite Apple : ~5 par session / 24h.</div>
    <div class="gen-log" id="genLog">En attente de lancement…</div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeGenModal()">Fermer</button>
      <button class="btn btn-primary" id="genStartBtn" onclick="startGen()">🚀 Lancer la génération</button>
    </div>
  </div>
</div>

<!-- TOAST -->
<div class="toast-wrap" id="toastWrap"></div>

<script>
// ── STATE ─────────────────────────────────────────────────
let _orders={}, _msgs={}, _accounts=[], _filter='all', _activeChat=null, _revenueChart=null;
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
  ['overview','orders','chat','accounts'].forEach(id=>{
    const el=document.getElementById('page-'+id);
    if(el) el.style.display=id===p?(id==='overview'?'block':'flex'):'none';
  });
  if(p==='orders'){document.getElementById('page-orders').style.display='flex';}
  if(p==='chat'){document.getElementById('page-chat').style.display='block'; renderConvList();}
  if(p==='accounts'){document.getElementById('page-accounts').style.display='block'; loadAccounts();}
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
async function loadMsgs(){
  const r=await fetch('/api/messages'); _msgs=await r.json();
  renderConvList();
  if(_activeChat) renderChat(_activeChat);
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
    return `<div class="conv-item${_activeChat===uid?' active':''}" onclick="selectChat('${uid}')">
      <div class="avatar" style="background:${col}20;color:${col}">${init}</div>
      <div style="flex:1;min-width:0">
        <div class="conv-name">${c.name||uid}</div>
        <div class="conv-prev">${last?.from==='admin'?'Vous : ':''}${last?.text||'…'}</div>
      </div>
      ${(c.unread||0)>0?`<span class="unread-badge">${c.unread}</span>`:''}
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
  win.innerHTML=`
    <div class="chat-header">
      <div class="avatar" style="background:#3b82f620;color:#3b82f6;width:36px;height:36px;font-size:.85rem">${init}</div>
      <div><div style="font-weight:700">${escHtml(c.name||uid)}</div><div style="font-size:.75rem;color:var(--t3)">${escHtml(c.username||'')} · ID : ${safeUid}</div></div>
    </div>
    <div class="chat-msgs" id="chatMsgs">${msgs||'<div style="color:var(--t3);margin:auto">Aucun message</div>'}</div>
    <div class="chat-input-row">
      <textarea class="chat-textarea" id="chatInput" rows="2" placeholder="Votre réponse… (Ctrl+Enter pour envoyer)"
        onkeydown="if(event.ctrlKey&&event.key==='Enter')sendReply('${safeUid}')"></textarea>
      <button class="send-btn" onclick="sendReply('${safeUid}')">➤</button>
    </div>`;
  setTimeout(()=>{const el=document.getElementById('chatMsgs');if(el)el.scrollTop=el.scrollHeight;},50);
}
async function sendReply(uid){
  const inp=document.getElementById('chatInput');
  const text=(inp?.value||'').trim(); if(!text)return;
  inp.value='';
  const r=await fetch('/api/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(uid),text})});
  const d=await r.json();
  toast(d.ok?'✅ Envoyé':'❌ Erreur',d.ok);
  await loadMsgs();
}
async function markRead(uid){
  await fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid})});
  if(_msgs[uid]) _msgs[uid].unread=0;
}

// ── ACCOUNTS ──────────────────────────────────────────────
async function loadAccounts(){
  const r=await fetch('/api/accounts'); const d=await r.json();
  _accounts=d.accounts||[];
  const q=d.quota||{};
  // Quota bar
  const pct=Math.round((q.used||0)/(q.limit||5)*100);
  const barEl=document.getElementById('quotaBar');
  if(barEl){barEl.style.width=pct+'%';barEl.className='quota-bar-fill'+(pct>=100?' full':pct>=80?' warn':'');}
  const pill=document.getElementById('quotaPill');
  if(pill){pill.className='pill '+(pct>=100?'pill-red':pct>=80?'pill-orange':'pill-green');pill.textContent=pct>=100?'Quota atteint':pct>=80?'Presque plein':'Disponible';}
  if(document.getElementById('quotaUsed')) $('quotaUsed').textContent=`${q.used||0}/${q.limit||5} aujourd'hui`;
  if(document.getElementById('quotaReset')) $('quotaReset').textContent=`Reset : ${q.reset||'—'}`;
  if(document.getElementById('quotaSub')) $('quotaSub').textContent=`${q.remaining||0} génération${(q.remaining||0)>1?'s':''} restante${(q.remaining||0)>1?'s':''} · Limite Apple ~5/session/24h`;
  // Table
  const tbody=document.getElementById('accountsTable'); if(!tbody)return;
  $('emailCount').textContent=_accounts.length;
  if(!_accounts.length){tbody.innerHTML=`<tr><td colspan="5"><div class="empty"><div class="empty-icon">📭</div>Aucun email — cliquez sur "Générer"</div></td></tr>`;return;}
  tbody.innerHTML=_accounts.map(a=>{
    const used=a.status==='used';
    const safeEmail=escHtml(a.email||'');
    const safePhone=escHtml(a.grab_phone||'—');
    const safeDate=escHtml((a.created||'').slice(0,10));
    return `<tr>
      <td class="mono" style="color:var(--purple)">${safeEmail}</td>
      <td style="color:var(--t3);font-size:.78rem">${safeDate}</td>
      <td>${used?'<span class="pill pill-orange">🔗 Utilisé</span>':'<span class="pill pill-green">✅ Disponible</span>'}</td>
      <td><span style="font-size:.8rem;color:var(--t2)">${safePhone}</span></td>
      <td style="display:flex;gap:6px">
        <button class="btn btn-secondary btn-sm" onclick="copyEmail('${safeEmail}')">Copier</button>
        <button class="btn ${used?'btn-secondary':'btn-blue'} btn-sm" onclick="toggleAccountStatus('${safeEmail}','${used?'available':'used'}')">${used?'Libérer':'Marquer utilisé'}</button>
      </td>
    </tr>`;
  }).join('');
}
function copyEmail(e){navigator.clipboard.writeText(e);toast('📋 Email copié !');}
async function toggleAccountStatus(email,status){
  let phone='';
  if(status==='used'){phone=prompt('Numéro de téléphone du compte Grab (optionnel):','')||'';}
  await fetch('/api/accounts/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,status,grab_phone:phone})});
  toast(status==='used'?'🔗 Marqué comme utilisé':'✅ Libéré');
  await loadAccounts();
}

// ── GENERATE MODAL ────────────────────────────────────────
let _genPoll=null;
function openGenModal(){document.getElementById('genModal').classList.add('open'); $('genLog').textContent='Prêt à générer…';}
function closeGenModal(){document.getElementById('genModal').classList.remove('open');if(_genPoll){clearInterval(_genPoll);_genPoll=null;}}
async function startGen(){
  $('genStartBtn').disabled=true;
  $('genLog').textContent='Lancement…';
  const r=await fetch('/api/generate/start',{method:'POST'});
  const d=await r.json();
  if(!d.ok){toast(d.msg||'Erreur',false);$('genStartBtn').disabled=false;return;}
  _genPoll=setInterval(async()=>{
    const sr=await fetch('/api/generate/status'); const sd=await sr.json();
    $('genLog').textContent=sd.log||'';
    const el=$('genLog'); el.scrollTop=el.scrollHeight;
    if(!sd.running){clearInterval(_genPoll);_genPoll=null;$('genStartBtn').disabled=false;toast('✅ Génération terminée !');loadAccounts();}
  },1000);
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
  await Promise.all([loadDispo(), loadBotStatus(), loadRestoCount()]);
  // iCloud count mini-card (quick update without full accounts reload)
  try{
    const r=await fetch('/api/accounts'); const d=await r.json();
    const avail=(d.accounts||[]).filter(a=>a.status==='available').length;
    const total=(d.accounts||[]).length;
    const el=$('icloud-count-card');
    if(el){el.textContent=avail+'/'+total+' disponibles';el.style.color=avail>0?'var(--green)':'var(--orange)';}
  }catch(e){}
}
refreshAll();
setInterval(refresh, 15000);
setInterval(()=>Promise.all([loadDispo(),loadBotStatus(),loadRestoCount()]), 30000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", 5001)))
    a = p.parse_args()
    print(f"🛵 GrabDiscount QG → http://localhost:{a.port}   |   pwd: {DASHBOARD_PWD}")
    app.run(host="0.0.0.0", port=a.port, debug=False)
