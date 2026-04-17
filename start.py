"""
start.py — Point d'entrée unique Render / Raspberry Pi
=======================================================
Lance en parallèle :
  • Bot Telegram     (thread principal — asyncio + signaux)
  • Dashboard Flask  (daemon thread   — port exposé par Render)
  • Scraper restos   (daemon thread   — toutes les 24h)

Toutes les données lues/écrites dans DATA_DIR (= /data sur Render).
"""
from __future__ import annotations
import threading, os, sys, time
from pathlib import Path

# ── Variables d'environnement ────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
PORT     = int(os.environ.get("PORT", 5001))   # Render injecte PORT automatiquement

print(f"[start] DATA_DIR = {DATA_DIR or '(répertoire courant)'}", flush=True)
print(f"[start] PORT     = {PORT}", flush=True)

# ── Dashboard Flask (daemon thread) ──────────────────────
def run_dashboard():
    try:
        import dashboard
        dashboard._reload_accounts()
        dashboard._auto_gen["enabled"] = True
        dashboard._schedule_next()
        print(f"[DASH] 🛵 Dashboard → http://0.0.0.0:{PORT}", flush=True)
        dashboard.app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[DASH] ❌ Erreur dashboard : {e}", flush=True)

# ── Scraper restaurants (daemon thread — toutes les 24h) ─
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

# ── Démarrer les threads daemon ───────────────────────────
threading.Thread(target=run_dashboard,          daemon=True).start()
threading.Thread(target=run_restaurant_scraper, daemon=True).start()

# Petit délai pour que le dashboard soit prêt avant que Render check /health
time.sleep(2)

# ── Bot Telegram dans le thread principal ─────────────────
# (python-telegram-bot v21 a besoin du thread principal pour asyncio + signaux)
while True:
    try:
        import bot
        print("[BOT] ✅ Démarré", flush=True)
        bot.main()
    except Exception as e:
        print(f"[BOT] ❌ Crash : {e} — relance dans 10s", flush=True)
        time.sleep(10)
