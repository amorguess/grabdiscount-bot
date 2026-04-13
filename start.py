"""
Render entry point — HTTP health server en premier, bot + scraper en threads
"""
import threading
import os
import sys

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("PORT", 10000))

# ── HTTP HEALTH SERVER (démarre en premier, dans le thread principal) ──
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GrabDiscount Bot OK")
    def log_message(self, *args):
        pass

# Lancer le bot dans un thread daemon
def run_bot():
    try:
        import bot
        bot.main()
    except Exception as e:
        print(f"[BOT] Erreur: {e}", flush=True)
        sys.exit(1)

def run_scraper():
    try:
        import scraper
        scraper.run_scheduler()
    except Exception as e:
        print(f"[SCRAPER] Erreur: {e}", flush=True)

def run_restaurant_scraper():
    try:
        import restaurant_scraper
        import schedule, time
        print("[RESTAURANTS] Premier scan au démarrage...", flush=True)
        restaurant_scraper.run_once()
        schedule.every(24).hours.do(restaurant_scraper.run_once)
        while True:
            schedule.run_pending()
            time.sleep(60)
    except Exception as e:
        print(f"[RESTAURANTS] Erreur: {e}", flush=True)

print(f"[start] HTTP health check sur port {PORT}", flush=True)

threading.Thread(target=run_scraper, daemon=True).start()
threading.Thread(target=run_restaurant_scraper, daemon=True).start()
threading.Thread(target=run_bot, daemon=True).start()

# HTTP server bloquant en dernier (satisfait Render)
server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
print(f"[start] Serveur HTTP démarré, bot en arrière-plan", flush=True)
server.serve_forever()
