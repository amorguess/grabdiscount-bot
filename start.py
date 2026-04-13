"""
Point d'entrée Render — lance le bot ET le scraper en parallèle
"""
import threading
import scraper
import bot

def run_scraper():
    scraper.run_scheduler()

# Scraper dans un thread séparé (toutes les 48h)
t = threading.Thread(target=run_scraper, daemon=True)
t.start()

# Bot principal (bloquant)
bot.main()
