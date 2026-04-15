"""
Render / Raspberry Pi entry point
HTTP health check en thread principal, bot + scraper en daemon threads
"""
from __future__ import annotations
import threading, os, sys, time
from pathlib import Path

# Charge .env si présent
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
PORT     = int(os.environ.get("PORT", 10000))

from http.server import HTTPServer, BaseHTTPRequestHandler

# ── État de santé du bot ──────────────────────────────────
_bot_alive  = False
_bot_error  = ""

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            code = 200 if _bot_alive else 503
            body = b"OK" if _bot_alive else f"Bot KO: {_bot_error}".encode()
        else:
            code, body = 200, b"GrabDiscount Bot OK"
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

# ── Bot avec surveillance ────────────────────────────────
def run_bot():
    global _bot_alive, _bot_error
    while True:   # relance auto si crash
        try:
            import bot
            _bot_alive = True
            _bot_error = ""
            print("[BOT] ✅ Démarré", flush=True)
            bot.main()
        except Exception as e:
            _bot_alive = False
            _bot_error = str(e)
            print(f"[BOT] ❌ Crash : {e} — relance dans 10s", flush=True)
            time.sleep(10)

# ── Restaurant scraper (toutes les 24h) ─────────────────
def run_restaurant_scraper():
    try:
        import restaurant_scraper, schedule, time as t
        print("[RESTAURANTS] Premier scan au démarrage…", flush=True)
        restaurant_scraper.run_once()
        schedule.every(24).hours.do(restaurant_scraper.run_once)
        while True:
            schedule.run_pending()
            t.sleep(60)
    except Exception as e:
        print(f"[RESTAURANTS] Erreur : {e}", flush=True)

# ── Lancement ────────────────────────────────────────────
print(f"[start] HTTP health check sur port {PORT}", flush=True)

threading.Thread(target=run_bot,                daemon=True).start()
threading.Thread(target=run_restaurant_scraper, daemon=True).start()

server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
print("[start] Serveur HTTP démarré", flush=True)
server.serve_forever()
