"""
Point d'entrée Render — lance le bot + scraper + mini HTTP server (requis par Render free tier)
"""
import threading
import os
import scraper
import bot
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GrabDiscount Bot is running")
    def log_message(self, *args):
        pass  # silence logs

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def run_scraper():
    scraper.run_scheduler()

# Health check server (requis Render)
threading.Thread(target=run_health_server, daemon=True).start()

# Scraper 48h dans un thread séparé
threading.Thread(target=run_scraper, daemon=True).start()

# Bot principal (bloquant)
bot.main()
