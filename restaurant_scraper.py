#!/usr/bin/env python3
"""
Grab Food Restaurant Scraper - Thailand (toutes villes)
Fetches all restaurants via food.grab.com proxy API
Saves to restaurants.json, runs every 24h
"""

import json, os, re, time, requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.environ.get("DATA_DIR", BASE_DIR)
OUTPUT    = os.path.join(DATA_DIR, "restaurants.json")

PAGE_SIZE = 32
API_URL   = "https://food.grab.com/proxy/foodweb/search"

# Grille de points GPS couvrant toute la Thaïlande
# Chaque point = centre d'une zone de livraison (~5km de rayon)
THAILAND_ZONES = [
    # ── BANGKOK (grille dense — ville énorme) ──────────────────────────
    ("Bangkok - Sukhumvit",       13.7367, 100.5598),
    ("Bangkok - Silom/Sathon",    13.7244, 100.5272),
    ("Bangkok - Chatuchak",       13.8122, 100.5600),
    ("Bangkok - Lat Phrao",       13.8190, 100.5757),
    ("Bangkok - Rama 9",          13.7559, 100.5680),
    ("Bangkok - On Nut",          13.7010, 100.5990),
    ("Bangkok - Asoke",           13.7445, 100.5604),
    ("Bangkok - Thonburi",        13.7270, 100.4860),
    ("Bangkok - Bang Na",         13.6721, 100.6060),
    ("Bangkok - Min Buri",        13.8130, 100.7480),
    ("Bangkok - Pratunam",        13.7530, 100.5390),
    ("Bangkok - Ekkamai",         13.7160, 100.5850),
    ("Bangkok - Don Mueang",      13.9130, 100.6050),
    ("Bangkok - Nonthaburi",      13.8590, 100.5140),
    ("Bangkok - Samut Prakan",    13.5990, 100.5970),
    ("Bangkok - Bangkapi",        13.7610, 100.6390),
    ("Bangkok - Bearing",         13.6650, 100.6350),
    # ── NORD ──────────────────────────────────────────────────────────
    ("Chiang Mai - Nimmanhaemin", 18.7980, 98.9680),
    ("Chiang Mai - Old City",     18.7883, 98.9853),
    ("Chiang Mai - Nimman",       18.8030, 98.9590),
    ("Chiang Mai - Airport",      18.7670, 98.9620),
    ("Chiang Rai",                19.9071, 99.8308),
    ("Pai",                       19.3573, 98.4418),
    ("Lampang",                   18.2887, 99.4908),
    ("Lamphun",                   18.5744, 99.0090),
    ("Phrae",                     18.1450, 100.1410),
    ("Nan",                       18.7798, 100.7730),
    ("Mae Sot",                   16.7130, 98.5700),
    ("Chiang Saen",               20.2730, 100.0840),
    # ── NORD-EST (ISAAN) ──────────────────────────────────────────────
    ("Khon Kaen",                 16.4419, 102.8360),
    ("Udon Thani",                17.4138, 102.7870),
    ("Ubon Ratchathani",          15.2448, 104.8473),
    ("Nakhon Ratchasima (Korat)", 14.9799, 102.0978),
    ("Roi Et",                    16.0540, 103.6520),
    ("Sakon Nakhon",              17.1550, 104.1480),
    ("Surin",                     14.8820, 103.4930),
    ("Buriram",                   14.9940, 103.1030),
    ("Loei",                      17.4860, 101.7230),
    ("Nong Khai",                 17.8760, 102.7400),
    ("Mukdahan",                  16.5430, 104.7240),
    ("Amnat Charoen",             15.8660, 104.6270),
    # ── CENTRE ────────────────────────────────────────────────────────
    ("Ayutthaya",                 14.3532, 100.5670),
    ("Nakhon Sawan",              15.6980, 100.1290),
    ("Lopburi",                   14.7995, 100.6530),
    ("Kanchanaburi",              14.0040, 99.5480),
    ("Phitsanulok",               16.8211, 100.2659),
    ("Tak",                       16.8797, 99.1253),
    ("Sukhothai",                 17.0067, 99.8232),
    ("Nakhon Pathom",             13.8199, 100.0600),
    ("Samut Sakhon",              13.5474, 100.2740),
    ("Suphan Buri",               14.4720, 100.1280),
    ("Sing Buri",                 14.8900, 100.3970),
    ("Ang Thong",                 14.5870, 100.4550),
    # ── EST ───────────────────────────────────────────────────────────
    ("Pattaya",                   12.9236, 100.8825),
    ("Jomtien",                   12.8910, 100.8730),
    ("Rayong",                    12.6815, 101.2816),
    ("Chonburi",                  13.3611, 100.9847),
    ("Chanthaburi",               12.6113, 102.1033),
    ("Trat",                      12.2428, 102.5148),
    ("Koh Chang",                 12.0564, 102.3182),
    ("Si Racha",                  13.1744, 100.9218),
    # ── OUEST ─────────────────────────────────────────────────────────
    ("Hua Hin",                   12.5684, 99.9577),
    ("Pranburi",                  12.3990, 99.9070),
    ("Phetchaburi",               13.1119, 99.9404),
    ("Prachuap Khiri Khan",       11.8133, 99.7975),
    # ── SUD (GOLFE) ───────────────────────────────────────────────────
    ("Koh Samui - Chaweng",        9.5312, 100.0614),
    ("Koh Samui - Lamai",          9.4750, 100.0600),
    ("Koh Samui - Bophut",         9.5530, 99.9990),
    ("Koh Samui - Nathon",         9.5350, 99.9520),
    ("Koh Phangan",                9.7380, 100.0530),
    ("Koh Tao",                   10.0960, 99.8400),
    ("Surat Thani",               9.1382, 99.3211),
    ("Nakhon Si Thammarat",        8.4328, 100.0015),
    ("Songkhla",                   7.1990, 100.5950),
    ("Hat Yai",                    7.0086, 100.4747),
    ("Pattani",                    6.8650, 101.2500),
    ("Narathiwat",                 6.4260, 101.8230),
    ("Yala",                       6.5400, 101.2800),
    ("Chumphon",                  10.4930, 99.1800),
    # ── SUD (ANDAMAN) ─────────────────────────────────────────────────
    ("Phuket - Patong",            7.8964, 98.2979),
    ("Phuket - Phuket Town",       7.8820, 98.3923),
    ("Phuket - Kata/Karon",        7.8210, 98.2980),
    ("Phuket - Rawai",             7.7840, 98.3260),
    ("Phuket - Kamala",            7.9520, 98.2780),
    ("Krabi - Ao Nang",            8.0322, 98.8301),
    ("Krabi Town",                 8.0830, 98.9164),
    ("Koh Lanta",                  7.6300, 99.0540),
    ("Phang Nga",                  8.4510, 98.5250),
    ("Ranong",                    9.9780, 98.6340),
    ("Trang",                      7.5590, 99.6110),
    ("Satun",                      6.6230, 100.0670),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://food.grab.com",
    "Referer": "https://food.grab.com/th/en",
}


def extract_english_name(full_name: str) -> str:
    """Extract English portion from a name like 'McDonald's (แมคโดนัลด์) - โรบินสัน'.
    Falls back to full_name if the result would be too short or mostly punctuation."""
    # Remove Thai text in parentheses: (แมคโดนัลด์)
    cleaned = re.sub(r'\([^\)]*[\u0E00-\u0E7F][^\)]*\)', '', full_name)
    # Remove Thai portions after dash preceded by whitespace
    cleaned = re.split(r'\s[-–]\s*[\u0E00-\u0E7F]', cleaned)[0]
    # Remove any remaining Thai characters
    cleaned = re.sub(r'[\u0E00-\u0E7F]+', '', cleaned)
    # Clean trailing punctuation, dashes, spaces, open parentheses
    cleaned = re.sub(r'[\s\-–(|/\\]+$', '', cleaned).strip()
    # Also clean leading junk
    cleaned = re.sub(r'^[\s\-–(|/\\]+', '', cleaned).strip()
    # Fallback: if result is meaninglessly short, use full name (Thai preserved for context)
    # A meaningful English name needs at least 3 letters or 4+ total characters
    alpha_only = re.sub(r'[^a-zA-Z]', '', cleaned)
    if len(alpha_only) < 3 and len(cleaned) < 4:
        return full_name
    return cleaned or full_name


def fetch_zone(zone_name: str, lat: float, lng: float, seen_ids: set) -> list:
    """Scrape tous les restos d'une zone GPS. Ignore les doublons via seen_ids."""
    results = []
    offset  = 0
    total   = None
    consecutive_errors = 0

    while True:
        try:
            r = requests.post(API_URL, headers=HEADERS, json={
                "latlng": f"{lat},{lng}",
                "keyword": "",
                "offset": offset,
                "pageSize": PAGE_SIZE,
            }, timeout=15)

            if r.status_code != 200:
                break

            data  = r.json().get('searchResult', {})
            items = data.get('searchMerchants', [])
            if total is None:
                total = data.get('totalCount', 0)

            if not items:
                break

            for item in items:
                rid = item['id']
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                brief   = item.get('merchantBrief', {})
                name_en = extract_english_name(item['address']['name'])
                results.append({
                    "id":       rid,
                    "name":     name_en,
                    "name_th":  item['address']['name'],
                    "cuisine":  brief.get('cuisine', []),
                    "photo":    brief.get('smallPhotoHref') or brief.get('photoHref', ''),
                    "icon":     brief.get('iconHref', ''),
                    "halal":    brief.get('halal', False),
                    "city":     item['address'].get('city', zone_name),
                    "zone":     zone_name,
                })

            offset += PAGE_SIZE
            consecutive_errors = 0

            if total and offset >= total:
                break

            time.sleep(0.3)

        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            time.sleep(2)

    return results


def fetch_all_restaurants() -> list:
    all_restaurants = []
    seen_ids        = set()
    total_zones     = len(THAILAND_ZONES)

    # Reprend depuis la sauvegarde existante si elle est plus récente de moins de 6h
    try:
        with open(OUTPUT, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_ts = datetime.strptime(existing.get("last_updated",""), "%Y-%m-%d %H:%M")
        age_h = (datetime.now() - existing_ts).total_seconds() / 3600
        if age_h < 6 and existing.get("restaurants"):
            for r in existing["restaurants"]:
                seen_ids.add(r["id"])
            all_restaurants = existing["restaurants"]
            print(f"[{datetime.now():%H:%M:%S}] Reprise depuis la sauvegarde : {len(all_restaurants)} restaurants existants\n")
    except Exception:
        pass

    print(f"[{datetime.now():%H:%M:%S}] Scraping {total_zones} zones en Thaïlande…\n")

    for i, (zone_name, lat, lng) in enumerate(THAILAND_ZONES, 1):
        before = len(all_restaurants)
        zone_results = fetch_zone(zone_name, lat, lng, seen_ids)
        all_restaurants.extend(zone_results)
        new_count = len(all_restaurants) - before

        print(f"  [{i:>3}/{total_zones}] {zone_name:<40} +{new_count:>4} nouveaux  (total: {len(all_restaurants)})")

        # Sauvegarde incrémentale toutes les 10 zones
        if i % 10 == 0:
            save(all_restaurants, partial=True, zone=i, total_zones=total_zones)

        time.sleep(0.5)  # pause entre zones

    print(f"\n✅ Total : {len(all_restaurants)} restaurants uniques en Thaïlande")
    return all_restaurants


def save(restaurants: list, partial: bool = False, zone: int = 0, total_zones: int = 0):
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(restaurants),
        "restaurants": restaurants,
    }
    if partial:
        data["zones_done"] = zone
        data["zones_total"] = total_zones
    # Écriture atomique via fichier temporaire pour éviter la corruption
    tmp = OUTPUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT)
    label = f"[zone {zone}/{total_zones}]" if partial else "[final]"
    print(f"💾 {label} {len(restaurants)} restaurants → {OUTPUT}")


def git_push():
    """Push restaurants.json to GitHub so GitHub Pages stays up to date.
    Requires GIT_TOKEN env var on Render (Personal Access Token with repo scope).
    """
    import subprocess
    token = os.environ.get("GIT_TOKEN", "")
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    if not token:
        print("[GIT] ⚠ GIT_TOKEN non défini — push ignoré (local ou Render sans token).")
        return

    try:
        # Configure remote URL with token for auth
        remote_url = f"https://{token}@github.com/amorguess/grabdiscount-bot.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url],
                       cwd=repo_dir, check=True, capture_output=True)

        subprocess.run(["git", "add", "restaurants.json"], cwd=repo_dir, check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir)
        if result.returncode == 0:
            print("[GIT] Aucun changement dans restaurants.json, push ignoré.")
            return
        subprocess.run(
            ["git", "-c", "user.email=bot@grabdiscount.app",
             "-c", "user.name=GrabDiscount Bot",
             "commit", "-m", f"chore: update restaurants.json ({datetime.now():%Y-%m-%d %H:%M})"],
            cwd=repo_dir, check=True
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, check=True)
        print("[GIT] ✅ restaurants.json poussé vers GitHub Pages")
    except Exception as e:
        print(f"[GIT] ⚠ Push échoué: {e}")


def run_once():
    restaurants = fetch_all_restaurants()
    if restaurants:
        save(restaurants)
        git_push()
    return len(restaurants)




if __name__ == "__main__":
    import sys
    run_once()
