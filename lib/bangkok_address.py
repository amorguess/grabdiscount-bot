"""
bangkok_address.py — Générateur d'adresses résidentielles Bangkok
==================================================================
Fichier autonome, zéro dépendance externe (stdlib uniquement).
Réutilisable dans n'importe quel projet Python 3.7+.
Génère des adresses résidentielles réalistes pour Bangkok.

Usage en bibliothèque :
    from bangkok_address import get_address, get_batch

Usage CLI :
    python3 bangkok_address.py          # 5 adresses aléatoires
    python3 bangkok_address.py 20       # 20 adresses
    python3 bangkok_address.py --seed=user@icloud.com   # reproductible
"""
import random
import hashlib

# ─────────────────────────────────────────────────────────────────
#  ZONES RÉSIDENTIELLES DE BANGKOK
#  (route, sois disponibles, sous-quartier, district, code postal)
# ─────────────────────────────────────────────────────────────────
ZONES = [
    # ── Sukhumvit / Watthana ──────────────────────────────────
    ("Sukhumvit Road", list(range(1, 63, 2)),   "Khlong Toei Nuea",  "Watthana",     "10110"),
    ("Sukhumvit Road", list(range(2, 64, 2)),   "Khlong Toei Nuea",  "Watthana",     "10110"),
    ("Sukhumvit Road", list(range(55, 101, 2)), "Phra Khanong Nuea", "Watthana",     "10110"),
    ("Sukhumvit Road", list(range(56, 100, 2)),"Phra Khanong",      "Khlong Toei",  "10110"),
    # ── Silom / Bang Rak ─────────────────────────────────────
    ("Silom Road",     list(range(1, 25)),      "Si Lom",            "Bang Rak",     "10500"),
    ("Sathorn Road",   list(range(1, 15)),      "Thung Maha Mek",    "Sathon",       "10120"),
    ("Sathorn Road",   list(range(1, 12)),      "Yan Nawa",          "Sathon",       "10120"),
    # ── Ratchada / Huai Khwang ───────────────────────────────
    ("Ratchadaphisek Road", list(range(1, 30)), "Huai Khwang",       "Huai Khwang",  "10310"),
    ("Lat Phrao Road",      list(range(1, 50)), "Chom Phon",         "Chatuchak",    "10900"),
    ("Lat Phrao Road",      list(range(50, 95)),"Lat Phrao",         "Lat Phrao",    "10230"),
    # ── Ari / Phahon / Chatuchak ─────────────────────────────
    ("Phahonyothin Road",   list(range(1, 30)), "Sam Sen Nai",       "Phaya Thai",   "10400"),
    ("Phahonyothin Road",   list(range(30, 60)),"Lat Yao",           "Chatuchak",    "10900"),
    ("Phahonyothin Road",   list(range(60, 95)),"Anusawari",         "Bang Khen",    "10220"),
    # ── Phra Ram / Rama ──────────────────────────────────────
    ("Rama IV Road",        list(range(1, 20)), "Khlong Toei",       "Khlong Toei",  "10110"),
    ("Rama IX Road",        list(range(1, 25)), "Bang Kapi",         "Huai Khwang",  "10310"),
    ("Rama III Road",       list(range(1, 20)), "Bang Phong Phaeng", "Bang Kho Laem","10120"),
    ("Rama VI Road",        list(range(1, 15)), "Samsen Nai",        "Phaya Thai",   "10400"),
    # ── Thong Lo / Ekkamai ───────────────────────────────────
    ("Thong Lo Road",       list(range(1, 25)), "Khlong Toei Nuea",  "Watthana",     "10110"),
    ("Ekkamai Road",        list(range(1, 20)), "Khlong Toei Nuea",  "Watthana",     "10110"),
    # ── On Nut / Bang Na ─────────────────────────────────────
    ("On Nut Road",         list(range(1, 30)), "Suan Luang",        "Suan Luang",   "10250"),
    ("Bang Na-Trat Road",   list(range(1, 40)), "Bang Na Nuea",      "Bang Na",      "10260"),
    # ── Pattanakarn / Prawet ─────────────────────────────────
    ("Pattanakarn Road",    list(range(1, 35)), "Suan Luang",        "Suan Luang",   "10250"),
    ("Prawet Road",         list(range(1, 25)), "Prawet",            "Prawet",       "10250"),
    # ── Bangkapi / Ramkhamhaeng ──────────────────────────────
    ("Ramkhamhaeng Road",   list(range(1, 50)), "Hua Mak",           "Bang Kapi",    "10240"),
    ("Ramkhamhaeng Road",   list(range(50, 95)),"Saphan Sung",       "Saphan Sung",  "10240"),
    # ── Bang Sue / Nonthaburi border ─────────────────────────
    ("Ngam Wong Wan Road",  list(range(1, 30)), "Lat Yao",           "Chatuchak",    "10900"),
    ("Si Rat Road",         list(range(1, 20)), "Bang Sue",          "Bang Sue",     "10800"),
    # ── Tha Phra / Thon Buri ─────────────────────────────────
    ("Ratchaphruek Road",   list(range(1, 30)), "Talat Phlu",        "Thon Buri",    "10600"),
    ("Charoen Nakhon Road", list(range(1, 20)), "Khlong San",        "Khlong San",   "10600"),
    # ── Wang Thonglang / Srinakarin ──────────────────────────
    ("Srinakarin Road",     list(range(1, 40)), "Nuan Chan",         "Bueng Kum",    "10230"),
    ("Lat Krabang Road",    list(range(1, 30)), "Lat Krabang",       "Lat Krabang",  "10520"),
    # ── Nong Khaem / Bang Khae ───────────────────────────────
    ("Phetkasem Road",      list(range(1, 45)), "Nong Khaem",        "Nong Khaem",   "10160"),
    ("Bang Khae Road",      list(range(1, 25)), "Bang Khae",         "Bang Khae",    "10160"),
    # ── Don Mueang / Lak Si ──────────────────────────────────
    ("Vibhavadi Rangsit Road", list(range(1, 30)),"Don Mueang",      "Don Mueang",   "10210"),
    ("Lak Si Road",            list(range(1, 20)),"Thung Song Hong",  "Lak Si",      "10210"),
    # ── Khlong Sam Wa / Min Buri ─────────────────────────────
    ("Khlong Sam Wa Road",  list(range(1, 20)), "Khlong Sam Wa",     "Khlong Sam Wa","10510"),
    ("Si Burapha Road",     list(range(1, 20)), "Min Buri",          "Min Buri",     "10510"),
]

# ── Noms de copropriétés / condos ────────────────────────────────
CONDO_NAMES = [
    "Supalai Premier","Lumpini Suite","The Line","The Base","Life One",
    "Rhythm Sukhumvit","Park 24","Noble Reflex","IDEO Q","Aspire Living",
    "Centric Sea","Chapter One","Knightsbridge Prime","The Diplomat",
    "Quattro","Wind Sukhumvit","Hyde Sukhumvit","Sky Walk","Siri Sathorn",
    "Le Luk","The Address","Ivy Thong Lo","H Sukhumvit","Tree Condo",
    "Niche Mono","Metro Luxe","Ceil","Mori","Dori","Amber","Ideo Mobi",
    "Whizdom","Elio","The Nest","Casa Condo","M Silom","The Cube",
    "Mayfair Place","Circle Condominium","Lake Green","The Peak",
    "Rich Park","U Delight","One Plus","Baan Klang Muang","Plum Vibha",
    "Urban Space","Icon House","Life Vibha","Niche Park","Phahon Heights",
    "Pearl Residence","Phahon Space","Metro House","Jade Rama","Ari View",
    "Origin City","Casa Green","Dusk House","Urban Corner","Lumpini Point",
]

_BLDG_PREFIXES = [
    "Baan","The","Casa","Noble","IDEO","Lumpini","Centric","Aspire",
    "Metro","Rhythm","Life","Base","Knightsbridge","Chapter","Park",
    "Supalai","Origin","Plum","Niche","Quad","Veri","Astra","Belle",
    "Cube","Deo","Eden","Flora","Grand","Haven","Icon","Jade","Klass",
    "Lava","Mela","Nue","Optima","Pearl","Quest","Revo","Siamese",
]

_BLDG_SUFFIXES = [
    "Condo","Residence","Place","Court","Tower","Mansion","Park",
    "Villa","Home","Living","Space","Suite","Loft","Hub","One",
    "House","View","Heights","Point","Corner","Edge","Garden",
    "Green","Prime","Plus","Neo","Urban","City",
]

_BLDG_THEMES = [
    "Sukhumvit","Silom","Sathorn","Ratchada","Ari","Ekkamai",
    "Thong Lo","On Nut","Phra Khanong","Bang Na","Lat Phrao",
    "Phahon","Vibha","Rama","Central","Metro","Sky","River","Green",
]


def _make_building(rng: random.Random) -> str:
    """Génère un nom de bâtiment résidentiel réaliste."""
    style = rng.randint(0, 3)
    if style == 0:
        return rng.choice(CONDO_NAMES)
    elif style == 1:
        return f"{rng.choice(_BLDG_PREFIXES)} {rng.choice(_BLDG_THEMES)}"
    elif style == 2:
        return f"{rng.choice(_BLDG_PREFIXES)} {rng.choice(_BLDG_SUFFIXES)}"
    else:
        return f"{rng.choice(_BLDG_THEMES)} {rng.choice(_BLDG_SUFFIXES)}"


def _generate_one(rng: random.Random) -> str:
    """Génère une adresse Bangkok complète en un appel."""
    road, sois, sub_district, district, postcode = rng.choice(ZONES)
    soi      = rng.choice(sois)
    bldg     = _make_building(rng)
    floor    = rng.randint(2, 35)
    unit_num = rng.randint(1, 20)
    unit_str = f"{floor:02d}{unit_num:02d}"
    road_prefix = road.split()[0]

    return (
        f"Room {unit_str}, {bldg}, "
        f"Soi {road_prefix} {soi}, {road}, "
        f"{sub_district}, {district}, Bangkok {postcode}"
    )


# ─────────────────────────────────────────────────────────────────
#  PRÉ-GÉNÉRATION D'UN POOL DE 1500 ADRESSES UNIQUES
# ─────────────────────────────────────────────────────────────────
def _build_pool(n: int = 1500) -> list:
    rng  = random.Random(42)  # seed fixe = pool déterministe
    seen = set()
    pool = []
    attempts = 0
    while len(pool) < n and attempts < n * 30:
        attempts += 1
        addr = _generate_one(rng)
        key  = addr[:50]      # clé = début unique (bâtiment + numéro)
        if key not in seen:
            seen.add(key)
            pool.append(addr)
    return pool


_POOL: list = _build_pool(1500)
_used: set  = set()


# ── API publique ──────────────────────────────────────────────────

def get_address(seed: str = "") -> str:
    """
    Retourne une adresse Bangkok unique.

    Args:
        seed: Seed pour reproductibilité (ex: email iCloud). Si vide,
              retourne la prochaine adresse non utilisée du pool.

    Returns:
        Adresse complète (str), ex:
        "Room 1204, The Base, Soi Sukhumvit 21, Sukhumvit Road,
         Khlong Toei Nuea, Watthana, Bangkok 10110"
    """
    if seed:
        idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(_POOL)
        return _POOL[idx]
    # Mode séquentiel sans seed — évite les doublons
    for i in range(len(_POOL)):
        if i not in _used:
            _used.add(i)
            return _POOL[i]
    # Pool épuisé : regénère aléatoirement
    return _generate_one(random.Random())


def get_batch(n: int) -> list:
    """
    Retourne n adresses uniques du pool (dans l'ordre, sans répétition).

    Args:
        n: Nombre d'adresses souhaitées.

    Returns:
        Liste de str.
    """
    return [get_address() for _ in range(n)]


def get_random(n: int = 1) -> list:
    """
    Retourne n adresses entièrement aléatoires (peut avoir des doublons).

    Args:
        n: Nombre d'adresses.

    Returns:
        Liste de str.
    """
    rng = random.Random()
    return [_generate_one(rng) for _ in range(n)]


def reset_pool():
    """Réinitialise le compteur du pool (les adresses peuvent être réutilisées)."""
    _used.clear()


# ── CLI ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    args  = sys.argv[1:]
    n     = 5
    seed  = ""

    for a in args:
        if a.startswith("--seed="):
            seed = a.split("=", 1)[1]
        elif a.isdigit():
            n = int(a)

    if seed:
        print(f"Adresse pour '{seed}':")
        print(get_address(seed))
    else:
        print(f"{n} adresses Bangkok:\n")
        for i, addr in enumerate(get_batch(n), 1):
            print(f"#{i:03d}  {addr}")
