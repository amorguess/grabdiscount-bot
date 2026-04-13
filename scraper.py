#!/usr/bin/env python3
"""
Grab Food Cuisine Scraper
Détecte automatiquement les nouvelles cuisines sur Grab Food Bangkok
S'exécute toutes les 48h et met à jour cuisines.json + notifie via Telegram
"""

import json
import os
import time
import requests
import schedule
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────
BOT_TOKEN   = "8796586342:AAG4HxelgPzuDVLCfZMzcYHRDGRH_C4tig4"
ADMIN_ID    = "8711205448"
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.environ.get("DATA_DIR", BASE_DIR)
CUISINES_FILE = os.path.join(DATA_DIR, "cuisines.json")

# Coordonnées Bangkok centre (Sukhumvit)
LAT  = 13.7367
LNG  = 100.5598

# Headers pour simuler l'app mobile Grab
HEADERS = {
    "User-Agent": "GrabApp/5.270.0 (iPhone; iOS 17.0; Scale/3.00)",
    "Accept": "application/json",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Origin": "https://food.grab.com",
    "Referer": "https://food.grab.com/",
}

# ── TELEGRAM ─────────────────────────────────────────
def notify_admin(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[Telegram] Erreur: {e}")

# ── CHARGER / SAUVEGARDER ─────────────────────────────
def load_cuisines() -> dict:
    with open(CUISINES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cuisines(data: dict):
    with open(CUISINES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── SCRAPER GRAB FOOD ─────────────────────────────────
def fetch_grab_categories() -> list[dict]:
    """
    Récupère les catégories via l'API Grab Food.
    Essaie plusieurs endpoints et combine les résultats.
    """
    found = {}

    # --- Endpoint 1: Search categories ---
    try:
        r = requests.get(
            "https://portal.grab.com/foodweb/v2/categories",
            params={"latlng": f"{LAT},{LNG}", "countryCode": "TH"},
            headers=HEADERS,
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("categories", data.get("data", []))
            for item in items:
                name = item.get("name", item.get("displayName", ""))
                gid  = item.get("id", name.lower().replace(" ", "_"))
                if name:
                    found[gid] = name
            print(f"[Endpoint 1] {len(found)} catégories trouvées")
    except Exception as e:
        print(f"[Endpoint 1] {e}")

    # --- Endpoint 2: Grab Food web search ---
    try:
        r = requests.post(
            "https://food.grab.com/v1/search",
            headers={**HEADERS, "Content-Type": "application/json"},
            json={
                "latlng": {"latitude": LAT, "longitude": LNG},
                "filters": [],
                "keyword": "",
                "sortBy": "DISTANCE",
                "pagination": {"offset": 0, "limit": 1},
            },
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            for cuisine in data.get("cuisines", data.get("categories", [])):
                name = cuisine.get("name", cuisine.get("cuisine", ""))
                gid  = cuisine.get("id", name.lower().replace(" ", "_"))
                if name and gid not in found:
                    found[gid] = name
            print(f"[Endpoint 2] total: {len(found)} catégories")
    except Exception as e:
        print(f"[Endpoint 2] {e}")

    # --- Endpoint 3: Grab public API (Bangkok) ---
    try:
        r = requests.get(
            "https://food.grab.com/api/v1/feed",
            params={"latitude": LAT, "longitude": LNG, "countryCode": "TH"},
            headers=HEADERS,
            timeout=12,
        )
        if r.status_code == 200:
            data = r.json()
            for section in data.get("sections", []):
                for item in section.get("cuisineCards", []):
                    name = item.get("displayName", item.get("name", ""))
                    gid  = item.get("id", name.lower().replace(" ", "_"))
                    if name and gid not in found:
                        found[gid] = name
            print(f"[Endpoint 3] total: {len(found)} catégories")
    except Exception as e:
        print(f"[Endpoint 3] {e}")

    # Convertir en liste
    return [{"grab_id": k, "name": v} for k, v in found.items()]

# ── ICÔNES AUTO ───────────────────────────────────────
ICON_MAP = {
    "thai": "🍜", "japan": "🍣", "korea": "🫕", "chin": "🥟",
    "burger": "🍔", "pizza": "🍕", "italian": "🍝", "pasta": "🍝",
    "indian": "🍛", "health": "🥗", "fast": "🍟", "sea": "🦐",
    "bbq": "🥩", "grill": "🥩", "fried chick": "🍤", "ramen": "🍜",
    "hotpot": "🍲", "shabu": "🍲", "mookata": "🥘", "rice": "🍚",
    "noodle": "🍜", "porridge": "🥣", "veg": "🥗", "halal": "☪️",
    "muslim": "☪️", "bak": "🥐", "dessert": "🍰", "ice cream": "🍦",
    "bubble": "🧋", "coffee": "☕", "drink": "🥤", "breakfast": "🍳",
    "sandwich": "🥙", "mexic": "🌮", "dim sum": "🍢", "soup": "🍲",
    "western": "🥑", "viet": "🐟", "steak": "🥩", "bento": "🍱",
    "seafood": "🦐", "sushi": "🍱",
}

def get_icon(name: str) -> str:
    nl = name.lower()
    for key, icon in ICON_MAP.items():
        if key in nl:
            return icon
    return "🍽️"

# ── CHECK NOUVELLES CUISINES ───────────────────────────
def check_new_cuisines():
    print(f"\n{'='*50}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scan Grab Food...")

    current_data = load_cuisines()
    existing_ids = {c["grab_id"] for c in current_data["cuisines"]}
    existing_names_lower = {c["en"].lower() for c in current_data["cuisines"]}

    grab_categories = fetch_grab_categories()

    new_ones = []
    for cat in grab_categories:
        gid  = cat["grab_id"]
        name = cat["name"]
        if gid not in existing_ids and name.lower() not in existing_names_lower:
            new_ones.append({
                "icon": get_icon(name),
                "fr":   name,
                "en":   name,
                "grab_id": gid,
                "new": True,
            })

    if new_ones:
        print(f"✅ {len(new_ones)} nouvelle(s) cuisine(s) détectée(s) !")
        for n in new_ones:
            print(f"   → {n['icon']} {n['en']}")

        # Ajouter en tête de liste (section "Nouveautés")
        current_data["cuisines"] = new_ones + current_data["cuisines"]
        current_data["total"]    = len(current_data["cuisines"])
        current_data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        save_cuisines(current_data)

        # Notifier l'admin
        lines = "\n".join(f"  {n['icon']} *{n['en']}*" for n in new_ones)
        notify_admin(
            f"🆕 *{len(new_ones)} nouvelle(s) cuisine(s) Grab détectée(s) !*\n\n"
            f"{lines}\n\n"
            f"✅ cuisines.json mis à jour automatiquement.\n"
            f"📅 Prochain scan dans 48h."
        )
    else:
        print("ℹ️ Aucune nouvelle cuisine détectée.")
        # Log silencieux côté admin toutes les semaines seulement
        day = datetime.now().weekday()
        if day == 0:  # Lundi
            notify_admin(
                f"📊 *Rapport hebdo Grab Scraper*\n\n"
                f"Aucune nouvelle cuisine cette semaine.\n"
                f"Total cuisines référencées : *{current_data['total']}*\n"
                f"Dernière MAJ : {current_data['last_updated']}"
            )

    print(f"{'='*50}\n")

# ── SCHEDULER ─────────────────────────────────────────
def run_scheduler():
    print("🤖 Grab Cuisine Scraper démarré")
    print(f"⏰ Scan toutes les 48h (prochain: dans 48h)")
    print(f"📍 Zone: Bangkok ({LAT}, {LNG})")
    print("Ctrl+C pour arrêter\n")

    # Premier scan immédiat
    check_new_cuisines()

    # Puis toutes les 48h
    schedule.every(48).hours.do(check_new_cuisines)

    while True:
        schedule.run_pending()
        time.sleep(60)

# ── MAIN ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Mode test : scan unique
        check_new_cuisines()
    else:
        run_scheduler()
