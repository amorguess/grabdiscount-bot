"""
start.py — Point d'entrée unique Render / Raspberry Pi
=======================================================
Ordre de démarrage optimisé pour Render :
  1. Health check HTTP minimal → port ouvert en <1s (Render valide)
  2. Dashboard Flask           → remplace le health check
  3. Bot Telegram              → thread daemon
  4. Scraper restaurants       → thread daemon (délai 60s)
"""
from __future__ import annotations
import threading, os, sys, time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Variables d'environnement ─────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import monitoring

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
PORT     = int(os.environ.get("PORT", 5001))

print(f"[start] DATA_DIR = {DATA_DIR or '(répertoire courant)'}", flush=True)
print(f"[start] PORT     = {PORT}", flush=True)

# ── 1. Health check minimal (ouvre le port instantanément) ──
# Render exige que le port réponde rapidement — ce mini serveur
# répond "OK" pendant que Flask charge en arrière-plan.
_flask_ready = False

class QuickHealth(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

_health_server = HTTPServer(("0.0.0.0", PORT), QuickHealth)
_health_thread = threading.Thread(target=_health_server.serve_forever, daemon=True)
_health_thread.start()
print(f"[start] ✅ Port {PORT} ouvert (health check)", flush=True)

# ── 2. Bot Telegram (daemon thread) ──────────────────────
def run_bot():
    import asyncio
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            import bot
            print("[BOT] ✅ Démarré", flush=True)
            loop.run_until_complete(_run_bot_async())
        except Exception as e:
            print(f"[BOT] ❌ Crash : {e} — relance dans 10s", flush=True)
            time.sleep(10)

async def _run_bot_async():
    import bot
    await bot.main_async() if hasattr(bot, 'main_async') else None

def run_bot_simple():
    """Lance le bot comme un sous-processus indépendant — évite les conflits asyncio/thread."""
    import subprocess, sys
    bot_script = Path(__file__).parent / "bot.py"
    attempt = 0
    first_start = True
    while True:
        try:
            if first_start:
                print("[BOT] ✅ Démarré (subprocess)", flush=True)
                first_start = False
            else:
                print(f"[BOT] 🔄 Relance #{attempt} (subprocess)", flush=True)
            proc = subprocess.Popen(
                [sys.executable, str(bot_script)],
                cwd=str(Path(__file__).parent)
            )
            proc.wait()
            code = proc.returncode
            if code != 0:
                attempt += 1
                # Backoff exponentiel : 10s → 20s → 40s → max 120s
                delay = min(10 * (2 ** (attempt - 1)), 120)
                print(f"[BOT] ❌ Crash (code {code}) — relance dans {delay}s (tentative {attempt})", flush=True)
                monitoring.alert_bot_crash(f"exit code {code}", attempt)
                time.sleep(delay)
                monitoring.alert_bot_restarted(attempt)
            else:
                first_start = True
                attempt = 0
                time.sleep(5)
        except Exception as e:
            attempt += 1
            delay = min(10 * (2 ** (attempt - 1)), 120)
            print(f"[BOT] ❌ Erreur : {e} — relance dans {delay}s", flush=True)
            monitoring.alert_bot_crash(str(e), attempt)
            time.sleep(delay)

# ── 3. Scraper (daemon thread — démarre après 60s) ────────
def run_restaurant_scraper():
    time.sleep(60)   # laisse le temps à Flask + Bot de démarrer
    try:
        import restaurant_scraper, schedule, time as t
        print("[RESTAURANTS] Scan au démarrage…", flush=True)
        restaurant_scraper.run_once()
        schedule.every(24).hours.do(restaurant_scraper.run_once)
        while True:
            schedule.run_pending()
            t.sleep(60)
    except Exception as e:
        print(f"[RESTAURANTS] Erreur : {e}", flush=True)

# ── 4. Dashboard Flask (thread principal) ─────────────────
def run_dashboard():
    global _flask_ready
    try:
        import dashboard
        dashboard._reload_accounts()
        dashboard._auto_gen["enabled"] = True
        # Lance une génération dans 5 min (au démarrage), puis toutes les 65 min
        dashboard._schedule_immediate(delay_min=5)
        # Résumé quotidien Telegram à 8h Bangkok
        monitoring.schedule_daily_summary()
        # Arrêt du health check minimal → Flask prend le relais
        _health_server.shutdown()
        _health_server.server_close()  # libère le socket immédiatement
        time.sleep(0.5)               # laisse le temps au port de se libérer
        print(f"[DASH] 🛵 Dashboard démarré sur port {PORT}", flush=True)
        _flask_ready = True
        from waitress import serve
        serve(dashboard.app, host="0.0.0.0", port=PORT, threads=8)
    except Exception as e:
        print(f"[DASH] ❌ Erreur : {e}", flush=True)

# ── Lancement des threads ─────────────────────────────────
threading.Thread(target=run_bot_simple,           daemon=True).start()
threading.Thread(target=run_restaurant_scraper,   daemon=True).start()

# Dashboard dans le thread principal (Flask bloque ici)
run_dashboard()
