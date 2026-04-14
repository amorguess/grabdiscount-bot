#!/usr/bin/env python3
"""
Grab Food Restaurant Scraper - Bangkok
Fetches all restaurants via food.grab.com proxy API
Saves to restaurants.json, runs every 24h
"""

import json, os, re, time, requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.environ.get("DATA_DIR", BASE_DIR)
OUTPUT    = os.path.join(DATA_DIR, "restaurants.json")

LAT, LNG  = 13.7367, 100.5598   # Bangkok Sukhumvit
PAGE_SIZE = 32
API_URL   = "https://food.grab.com/proxy/foodweb/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://food.grab.com",
    "Referer": "https://food.grab.com/th/en",
}


def extract_english_name(full_name: str) -> str:
    """Extract English portion from a name like 'McDonald's (แมคโดนัลด์) - โรบินสัน'"""
    # Remove Thai text in parentheses: (แมคโดนัลด์)
    cleaned = re.sub(r'\([^\)]*[\u0E00-\u0E7F][^\)]*\)', '', full_name)
    # Remove Thai portions after dash
    cleaned = re.split(r'\s[-–]\s*[\u0E00-\u0E7F]', cleaned)[0]
    # Remove any remaining Thai characters
    cleaned = re.sub(r'[\u0E00-\u0E7F]+', '', cleaned)
    # Clean trailing punctuation
    cleaned = re.sub(r'[\s\-–(]+$', '', cleaned).strip()
    return cleaned or full_name


def fetch_all_restaurants() -> list:
    restaurants = []
    offset = 0
    total = None

    print(f"[{datetime.now():%H:%M:%S}] Fetching Grab Food restaurants (Bangkok)...")

    while True:
        try:
            r = requests.post(API_URL, headers=HEADERS, json={
                "latlng": f"{LAT},{LNG}",
                "keyword": "",
                "offset": offset,
                "pageSize": PAGE_SIZE,
            }, timeout=15)

            if r.status_code != 200:
                print(f"  ⚠ HTTP {r.status_code} at offset {offset}, stopping.")
                break

            data = r.json().get('searchResult', {})
            items = data.get('searchMerchants', [])
            if total is None:
                total = data.get('totalCount', 0)

            if not items:
                break

            for item in items:
                brief = item.get('merchantBrief', {})
                name_en = extract_english_name(item['address']['name'])

                restaurants.append({
                    "id":       item['id'],
                    "name":     name_en,
                    "name_th":  item['address']['name'],
                    "cuisine":  brief.get('cuisine', []),
                    "photo":    brief.get('smallPhotoHref') or brief.get('photoHref', ''),
                    "icon":     brief.get('iconHref', ''),
                    "halal":    brief.get('halal', False),
                    "city":     item['address'].get('city', 'Bangkok'),
                })

            offset += PAGE_SIZE
            pct = int(len(restaurants) / max(total, 1) * 100)
            print(f"  → {len(restaurants)}/{total} ({pct}%)")

            if len(restaurants) >= total:
                break

            time.sleep(0.4)  # polite delay

        except Exception as e:
            print(f"  ✗ Error at offset {offset}: {e}")
            break

    return restaurants


def save(restaurants: list):
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(restaurants),
        "restaurants": restaurants,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(restaurants)} restaurants saved to {OUTPUT}")


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
