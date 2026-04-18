"""
1000+ adresses résidentielles Bangkok pour comptes Grab
Format : "Apt X, Building Name, Soi Y, Road, Sub-district, District, Bangkok POSTCODE"
Toutes sont de vraies rues/quartiers résidentiels de Bangkok.
"""
import random, hashlib

# ─────────────────────────────────────────────────────────────────
#  DONNÉES DE BASE
# ─────────────────────────────────────────────────────────────────

# (nom_route, sois_disponibles, sous_quartier, quartier, cp)
ZONES = [
    # ── Sukhumvit / Watthana ──────────────────────────────────
    ("Sukhumvit Road", list(range(1, 63, 2)),  "Khlong Toei Nuea", "Watthana",    "10110"),
    ("Sukhumvit Road", list(range(2, 64, 2)),  "Khlong Toei Nuea", "Watthana",    "10110"),
    ("Sukhumvit Road", list(range(55, 101, 2)),"Phra Khanong Nuea","Watthana",    "10110"),
    ("Sukhumvit Road", list(range(56, 100, 2)),"Phra Khanong",     "Khlong Toei", "10110"),
    # ── Silom / Bang Rak ─────────────────────────────────────
    ("Silom Road",     list(range(1, 25)),      "Si Lom",           "Bang Rak",    "10500"),
    ("Sathorn Road",   list(range(1, 15)),      "Thung Maha Mek",   "Sathon",      "10120"),
    ("Sathorn Road",   list(range(1, 12)),      "Yan Nawa",         "Sathon",      "10120"),
    # ── Ratchada / Huai Khwang ───────────────────────────────
    ("Ratchadaphisek Road", list(range(1, 30)), "Huai Khwang",      "Huai Khwang", "10310"),
    ("Lat Phrao Road",      list(range(1, 50)), "Chom Phon",        "Chatuchak",   "10900"),
    ("Lat Phrao Road",      list(range(50, 95)),"Lat Phrao",        "Lat Phrao",   "10230"),
    # ── Ari / Phahon / Chatuchak ─────────────────────────────
    ("Phahonyothin Road",   list(range(1, 30)), "Sam Sen Nai",      "Phaya Thai",  "10400"),
    ("Phahonyothin Road",   list(range(30, 60)),"Lat Yao",          "Chatuchak",   "10900"),
    ("Phahonyothin Road",   list(range(60, 95)),"Anusawari",        "Bang Khen",   "10220"),
    # ── Phra Ram / Rama ──────────────────────────────────────
    ("Rama IV Road",        list(range(1, 20)), "Khlong Toei",      "Khlong Toei", "10110"),
    ("Rama IX Road",        list(range(1, 25)), "Bang Kapi",        "Huai Khwang", "10310"),
    ("Rama III Road",       list(range(1, 20)), "Bang Phong Phaeng","Bang Kho Laem","10120"),
    ("Rama VI Road",        list(range(1, 15)), "Samsen Nai",       "Phaya Thai",  "10400"),
    # ── Thong Lo / Ekkamai ───────────────────────────────────
    ("Thong Lo Road",       list(range(1, 25)), "Khlong Toei Nuea", "Watthana",    "10110"),
    ("Ekkamai Road",        list(range(1, 20)), "Khlong Toei Nuea", "Watthana",    "10110"),
    # ── On Nut / Bang Na ─────────────────────────────────────
    ("On Nut Road",         list(range(1, 30)), "Suan Luang",       "Suan Luang",  "10250"),
    ("Bang Na-Trat Road",   list(range(1, 40)), "Bang Na Nuea",     "Bang Na",     "10260"),
    # ── Pattanakarn / Prawet ─────────────────────────────────
    ("Pattanakarn Road",    list(range(1, 35)), "Suan Luang",       "Suan Luang",  "10250"),
    ("Prawet Road",         list(range(1, 25)), "Prawet",           "Prawet",      "10250"),
    # ── Bangkapi / Ramkhamhaeng ──────────────────────────────
    ("Ramkhamhaeng Road",   list(range(1, 50)), "Hua Mak",          "Bang Kapi",   "10240"),
    ("Ramkhamhaeng Road",   list(range(50, 95)),"Saphan Sung",      "Saphan Sung", "10240"),
    # ── Nonthaburi adjacent / Bang Sue ───────────────────────
    ("Ngam Wong Wan Road",  list(range(1, 30)), "Lat Yao",          "Chatuchak",   "10900"),
    ("Si Rat Road",         list(range(1, 20)), "Bang Sue",         "Bang Sue",    "10800"),
    # ── Tha Phra / Thon Buri ─────────────────────────────────
    ("Ratchaphruek Road",   list(range(1, 30)), "Talat Phlu",       "Thon Buri",   "10600"),
    ("Charoen Nakhon Road", list(range(1, 20)), "Khlong San",       "Khlong San",  "10600"),
    # ── Wang Thonglang / Saphan Sung ─────────────────────────
    ("Srinakarin Road",     list(range(1, 40)), "Nuan Chan",        "Bueng Kum",   "10230"),
    ("Lat Krabang Road",    list(range(1, 30)), "Lat Krabang",      "Lat Krabang", "10520"),
    # ── Nong Khaem / Bang Khae ───────────────────────────────
    ("Phetkasem Road",      list(range(1, 45)), "Nong Khaem",       "Nong Khaem",  "10160"),
    ("Bang Khae Road",      list(range(1, 25)), "Bang Khae",        "Bang Khae",   "10160"),
    # ── Don Mueang / Lak Si ──────────────────────────────────
    ("Vibhavadi Rangsit Road", list(range(1, 30)),"Don Mueang",     "Don Mueang",  "10210"),
    ("Lak Si Road",            list(range(1, 20)),"Thung Song Hong", "Lak Si",     "10210"),
    # ── Min Buri / Khlong Sam Wa ─────────────────────────────
    ("Si Burapha Road",     list(range(1, 20)), "Min Buri",         "Min Buri",    "10510"),
    ("Khlong Sam Wa Road",  list(range(1, 20)), "Khlong Sam Wa",    "Khlong Sam Wa","10510"),
]

# ── Noms de bâtiments résidentiels ────────────────────────────
BUILDING_PREFIXES = [
    "Baan", "The", "Casa", "Noble", "IDEO", "Lumpini", "Centric", "Aspire",
    "Metro", "Rhythm", "Life", "Base", "Knightsbridge", "Chapter", "Park",
    "Supalai", "Origin", "Plum", "Niche", "Ideo", "Quad", "Veri",
    "Astra", "Belle", "Cube", "Deo", "Eden", "Flora", "Grand", "Haven",
    "Icon", "Jade", "Klass", "Lava", "Mela", "Nue", "Optima", "Pearl",
    "Quest", "Revo", "Siamese", "Teal", "Una", "Vista", "Wave", "Xen",
    "Yield", "Zone", "Amber", "Blue", "Coral", "Dusk", "Elara", "Fern",
]

BUILDING_SUFFIXES = [
    "Condo", "Residence", "Place", "Court", "Tower", "Mansion", "Park",
    "Villa", "Home", "Living", "Space", "Suite", "Loft", "Hub", "One",
    "House", "View", "Heights", "Point", "Corner", "Edge", "Lane",
    "Garden", "Green", "Prime", "Plus", "Neo", "Urban", "City",
]

BUILDING_THEMES = [
    "Sukhumvit", "Silom", "Sathorn", "Ratchada", "Ari", "Ekkamai",
    "Thong Lo", "On Nut", "Phra Khanong", "Bang Na", "Lat Phrao",
    "Phahon", "Vibha", "Rama", "Central", "Metro", "Sky", "River",
    "Green", "Park", "Garden", "City", "Urban", "Prime",
]

CONDO_NAMES = [
    # Condos réels bien connus (mix avec générés)
    "Supalai Premier", "Lumpini Suite", "The Line", "The Base", "Life One",
    "Rhythm Sukhumvit", "Park 24", "Noble Reflex", "IDEO Q", "Aspire",
    "Centric Sea", "Chapter One", "Knightsbridge Prime", "The Diplomat",
    "Quattro", "Wind Sukhumvit", "Hyde Sukhumvit", "Sky Walk", "Siri Sathorn",
    "Le Luk", "The Address", "Ivy Thong Lo", "H Sukhumvit", "Tree Condo",
    "Niche Mono", "Metro Luxe", "Ceil", "Mori", "Dori", "Amber",
    "Ideo Mobi", "Whizdom", "Elio", "The Nest", "Casa Condo", "M Silom",
    "The Cube", "Mayfair Place", "Circle Condominium", "Lake Green",
    "The Peak", "Rich Park", "U Delight", "One Plus", "Baan Klang Muang",
]


def _make_building_name(rng: random.Random) -> str:
    """Génère un nom de bâtiment résidentiel réaliste."""
    style = rng.randint(0, 3)
    if style == 0:
        return rng.choice(CONDO_NAMES)
    elif style == 1:
        return f"{rng.choice(BUILDING_PREFIXES)} {rng.choice(BUILDING_THEMES)}"
    elif style == 2:
        return f"{rng.choice(BUILDING_PREFIXES)} {rng.choice(BUILDING_SUFFIXES)}"
    else:
        return f"{rng.choice(BUILDING_THEMES)} {rng.choice(BUILDING_SUFFIXES)}"


def _generate_one(rng: random.Random) -> str:
    """Génère une adresse Bangkok complète."""
    road, sois, sub_district, district, postcode = rng.choice(ZONES)
    soi = rng.choice(sois)
    bldg = _make_building_name(rng)
    floor = rng.randint(2, 35)
    unit  = rng.randint(1, 20)
    unit_str = f"{floor:02d}{unit:02d}"

    return (
        f"Room {unit_str}, {bldg}, "
        f"Soi {road.split()[0]} {soi}, {road}, "
        f"{sub_district}, {district}, Bangkok {postcode}"
    )


# ─────────────────────────────────────────────────────────────────
#  PRÉ-GÉNÉRATION DE 1200 ADRESSES UNIQUES
# ─────────────────────────────────────────────────────────────────
def _build_pool(n: int = 1200) -> list:
    rng  = random.Random(42)   # seed fixe → déterministe
    seen = set()
    pool = []
    attempts = 0
    while len(pool) < n and attempts < n * 30:
        attempts += 1
        addr = _generate_one(rng)
        # Clé d'unicité : bâtiment + numéro chambre (évite doublon exact)
        key  = addr[:50]
        if key not in seen:
            seen.add(key)
            pool.append(addr)
    return pool


BANGKOK_ADDRESSES: list = _build_pool(1200)


# ─────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────
_used_indices: set = set()


def get_bangkok_address(seed: str = "") -> str:
    """
    Retourne une adresse Bangkok unique basée sur un seed (email).
    Sans seed : retourne une adresse aléatoire.
    """
    if seed:
        idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(BANGKOK_ADDRESSES)
        return BANGKOK_ADDRESSES[idx]
    # Sans seed : ordre séquentiel pour éviter les doublons
    for i in range(len(BANGKOK_ADDRESSES)):
        if i not in _used_indices:
            _used_indices.add(i)
            return BANGKOK_ADDRESSES[i]
    # Pool épuisé → regénérer aléatoirement
    return _generate_one(random.Random())


def get_all_addresses() -> list:
    """Retourne la liste complète des adresses pré-générées."""
    return list(BANGKOK_ADDRESSES)


def reset_used():
    """Réinitialise le pool d'adresses utilisées."""
    _used_indices.clear()


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"Pool total : {len(BANGKOK_ADDRESSES)} adresses\n")
    for i in range(n):
        print(f"#{i+1:04d}  {BANGKOK_ADDRESSES[i]}")
