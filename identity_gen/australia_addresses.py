"""
Adresses résidentielles couvrant toute l'Australie pour comptes Uber Eats AU.
Format : "Unit X/N Street Name, Suburb STATE Postcode"
Distribution pondérée par population des grandes villes (Sydney, Melbourne, etc.).
Toutes les paires suburb/postcode/state sont des correspondances réelles.
"""
import random
import hashlib

# ─────────────────────────────────────────────────────────────────
#  ZONES (suburb, state, postcode)
#  Chaque entrée = un quartier réel avec son code postal valide.
#  La répétition d'une ville encode la pondération démographique.
# ─────────────────────────────────────────────────────────────────
ZONES = [
    # ── Sydney NSW (poids ~25%) ───────────────────────────────
    ("Sydney",            "NSW", "2000"),
    ("Surry Hills",       "NSW", "2010"),
    ("Pyrmont",           "NSW", "2009"),
    ("Darlinghurst",      "NSW", "2010"),
    ("Newtown",           "NSW", "2042"),
    ("Bondi",             "NSW", "2026"),
    ("Bondi Junction",    "NSW", "2022"),
    ("Coogee",            "NSW", "2034"),
    ("Randwick",          "NSW", "2031"),
    ("Manly",             "NSW", "2095"),
    ("Mosman",            "NSW", "2088"),
    ("North Sydney",      "NSW", "2060"),
    ("Chatswood",         "NSW", "2067"),
    ("Parramatta",        "NSW", "2150"),
    ("Strathfield",       "NSW", "2135"),
    ("Burwood",           "NSW", "2134"),
    ("Hurstville",        "NSW", "2220"),
    ("Liverpool",         "NSW", "2170"),
    ("Bankstown",         "NSW", "2200"),
    ("Blacktown",         "NSW", "2148"),
    ("Penrith",           "NSW", "2750"),
    ("Hornsby",           "NSW", "2077"),
    ("Ryde",              "NSW", "2112"),
    ("Marrickville",      "NSW", "2204"),
    ("Glebe",             "NSW", "2037"),
    # ── Melbourne VIC (poids ~25%) ────────────────────────────
    ("Melbourne",         "VIC", "3000"),
    ("Southbank",         "VIC", "3006"),
    ("Docklands",         "VIC", "3008"),
    ("Carlton",           "VIC", "3053"),
    ("Fitzroy",           "VIC", "3065"),
    ("Collingwood",       "VIC", "3066"),
    ("Richmond",          "VIC", "3121"),
    ("South Yarra",       "VIC", "3141"),
    ("Prahran",           "VIC", "3181"),
    ("St Kilda",          "VIC", "3182"),
    ("Brunswick",         "VIC", "3056"),
    ("Northcote",         "VIC", "3070"),
    ("Footscray",         "VIC", "3011"),
    ("Williamstown",      "VIC", "3016"),
    ("Hawthorn",          "VIC", "3122"),
    ("Camberwell",        "VIC", "3124"),
    ("Box Hill",          "VIC", "3128"),
    ("Glen Waverley",     "VIC", "3150"),
    ("Dandenong",         "VIC", "3175"),
    ("Frankston",         "VIC", "3199"),
    ("Werribee",          "VIC", "3030"),
    ("Sunshine",          "VIC", "3020"),
    ("Caulfield",         "VIC", "3162"),
    ("Brighton",          "VIC", "3186"),
    ("Preston",           "VIC", "3072"),
    # ── Brisbane QLD (poids ~12%) ─────────────────────────────
    ("Brisbane",          "QLD", "4000"),
    ("South Brisbane",    "QLD", "4101"),
    ("Fortitude Valley",  "QLD", "4006"),
    ("New Farm",          "QLD", "4005"),
    ("West End",          "QLD", "4101"),
    ("Toowong",           "QLD", "4066"),
    ("Indooroopilly",     "QLD", "4068"),
    ("Chermside",         "QLD", "4032"),
    ("Logan Central",     "QLD", "4114"),
    ("Mount Gravatt",     "QLD", "4122"),
    ("Carindale",         "QLD", "4152"),
    ("Ipswich",           "QLD", "4305"),
    # ── Gold Coast / Sunshine Coast QLD (poids ~6%) ───────────
    ("Surfers Paradise",  "QLD", "4217"),
    ("Broadbeach",        "QLD", "4218"),
    ("Southport",         "QLD", "4215"),
    ("Robina",            "QLD", "4226"),
    ("Burleigh Heads",    "QLD", "4220"),
    ("Maroochydore",      "QLD", "4558"),
    ("Caloundra",         "QLD", "4551"),
    ("Noosa Heads",       "QLD", "4567"),
    # ── Perth WA (poids ~10%) ─────────────────────────────────
    ("Perth",             "WA",  "6000"),
    ("Northbridge",       "WA",  "6003"),
    ("East Perth",        "WA",  "6004"),
    ("West Perth",        "WA",  "6005"),
    ("Subiaco",           "WA",  "6008"),
    ("Leederville",       "WA",  "6007"),
    ("Mount Lawley",      "WA",  "6050"),
    ("Cottesloe",         "WA",  "6011"),
    ("Fremantle",         "WA",  "6160"),
    ("Joondalup",         "WA",  "6027"),
    ("Rockingham",        "WA",  "6168"),
    ("Mandurah",          "WA",  "6210"),
    ("Cannington",        "WA",  "6107"),
    ("Morley",            "WA",  "6062"),
    # ── Adelaide SA (poids ~7%) ───────────────────────────────
    ("Adelaide",          "SA",  "5000"),
    ("North Adelaide",    "SA",  "5006"),
    ("Norwood",           "SA",  "5067"),
    ("Glenelg",           "SA",  "5045"),
    ("Unley",             "SA",  "5061"),
    ("Prospect",          "SA",  "5082"),
    ("Marion",            "SA",  "5043"),
    ("Modbury",           "SA",  "5092"),
    ("Salisbury",         "SA",  "5108"),
    ("Port Adelaide",     "SA",  "5015"),
    # ── Canberra ACT (poids ~4%) ──────────────────────────────
    ("Canberra",          "ACT", "2601"),
    ("Braddon",           "ACT", "2612"),
    ("Kingston",          "ACT", "2604"),
    ("Manuka",            "ACT", "2603"),
    ("Belconnen",         "ACT", "2617"),
    ("Woden",             "ACT", "2606"),
    ("Tuggeranong",       "ACT", "2900"),
    ("Gungahlin",         "ACT", "2912"),
    # ── Newcastle / Wollongong NSW (poids ~5%) ────────────────
    ("Newcastle",         "NSW", "2300"),
    ("Newcastle West",    "NSW", "2302"),
    ("Hamilton",          "NSW", "2303"),
    ("Charlestown",       "NSW", "2290"),
    ("Wollongong",        "NSW", "2500"),
    ("Fairy Meadow",      "NSW", "2519"),
    ("Shellharbour",      "NSW", "2529"),
    # ── Hobart TAS (poids ~2%) ────────────────────────────────
    ("Hobart",            "TAS", "7000"),
    ("Sandy Bay",         "TAS", "7005"),
    ("North Hobart",      "TAS", "7000"),
    ("Glenorchy",         "TAS", "7010"),
    ("Launceston",        "TAS", "7250"),
    # ── Darwin NT (poids ~1.5%) ───────────────────────────────
    ("Darwin",            "NT",  "0800"),
    ("Darwin City",       "NT",  "0800"),
    ("Stuart Park",       "NT",  "0820"),
    ("Parap",             "NT",  "0820"),
    ("Palmerston",        "NT",  "0830"),
    # ── Geelong VIC (poids ~1.5%) ─────────────────────────────
    ("Geelong",           "VIC", "3220"),
    ("Geelong West",      "VIC", "3218"),
    ("Belmont",           "VIC", "3216"),
    ("Highton",           "VIC", "3216"),
    # ── Cairns / Townsville QLD (poids ~2%) ───────────────────
    ("Cairns",            "QLD", "4870"),
    ("Cairns North",      "QLD", "4870"),
    ("Townsville",        "QLD", "4810"),
    ("North Ward",        "QLD", "4810"),
    # ── Régionales (poids résiduel) ───────────────────────────
    ("Ballarat",          "VIC", "3350"),
    ("Bendigo",           "VIC", "3550"),
    ("Albury",            "NSW", "2640"),
    ("Wagga Wagga",       "NSW", "2650"),
    ("Toowoomba",         "QLD", "4350"),
    ("Mackay",            "QLD", "4740"),
    ("Rockhampton",       "QLD", "4700"),
    ("Bunbury",           "WA",  "6230"),
    ("Geraldton",         "WA",  "6530"),
    ("Mount Gambier",     "SA",  "5290"),
]

# ── Noms de rues réalistes (mix arboricole / royal / colonial) ──
STREET_BASES = [
    "George",      "Pitt",       "King",        "Queen",      "Elizabeth",
    "Collins",     "Bourke",     "Flinders",    "Spencer",    "Russell",
    "Macquarie",   "Phillip",    "Hunter",      "Castlereagh","Wentworth",
    "Park",        "Church",     "High",        "Main",       "Station",
    "Victoria",    "Albert",     "William",     "Edward",     "Charles",
    "Oxford",      "Cambridge",  "York",        "London",     "Sydney",
    "Lonsdale",    "Latrobe",    "Swanston",    "Burke",      "Toorak",
    "Chapel",      "Brunswick",  "Smith",       "Brunswick",  "Lygon",
    "Acland",      "Fitzroy",    "Beaufort",    "Hay",        "Murray",
    "Wellington",  "Beaumont",   "Wakefield",   "Currie",     "Grenfell",
    "Rundle",      "Pulteney",   "Gawler",      "North Terrace","South Terrace",
    "Anzac",       "Stirling",   "Hampden",     "Adelaide",   "Brisbane",
    "Hawthorn",    "Riversdale", "Maroondah",   "Springvale", "Glenferrie",
    "Beach",       "Ocean",      "Bay",         "Harbour",    "Marina",
    "Forest",      "Garden",     "Ridge",       "Hill",       "Valley",
    "Sunset",      "Sunrise",    "Pacific",     "Coastal",    "Esplanade",
    "Eucalyptus",  "Wattle",     "Banksia",     "Acacia",     "Jacaranda",
    "Bottlebrush", "Grevillea",  "Casuarina",   "Boronia",    "Kookaburra",
    "Kingsford",   "Kingsway",   "Crown",       "Regent",     "Princes",
]

STREET_TYPES = [
    "Street", "Road", "Avenue", "Lane", "Place", "Drive", "Court", "Way",
    "Crescent", "Parade", "Highway", "Boulevard", "Terrace", "Close",
    "Esplanade", "Square", "Walk",
]

# ── Préfixes d'unité (appartements / townhouses) ────────────────
UNIT_PREFIXES = ["Unit", "Apt", "Apartment", "Suite", "Flat"]


def _generate_one(rng: random.Random) -> str:
    """Génère une adresse australienne complète."""
    suburb, state, postcode = rng.choice(ZONES)
    street_base = rng.choice(STREET_BASES)
    street_type = rng.choice(STREET_TYPES)
    street_num  = rng.randint(1, 350)

    # 70% des adresses sont en immeuble (Unit X/N), 30% maison individuelle
    if rng.random() < 0.7:
        unit_pref = rng.choice(UNIT_PREFIXES)
        unit_num  = rng.randint(1, 80)
        return (
            f"{unit_pref} {unit_num}/{street_num} {street_base} {street_type}, "
            f"{suburb} {state} {postcode}"
        )
    else:
        return (
            f"{street_num} {street_base} {street_type}, "
            f"{suburb} {state} {postcode}"
        )


# ─────────────────────────────────────────────────────────────────
#  PRÉ-GÉNÉRATION DE 2000 ADRESSES UNIQUES
# ─────────────────────────────────────────────────────────────────
def _build_pool(n: int = 2000) -> list:
    rng  = random.Random(8024)  # seed fixe → déterministe
    seen = set()
    pool = []
    attempts = 0
    while len(pool) < n and attempts < n * 30:
        attempts += 1
        addr = _generate_one(rng)
        if addr not in seen:
            seen.add(addr)
            pool.append(addr)
    return pool


AUSTRALIA_ADDRESSES: list = _build_pool(2000)


# ─────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────
_used_indices: set = set()


def get_australia_address(seed: str = "") -> str:
    """
    Retourne une adresse australienne unique basée sur un seed (email).
    Sans seed : retourne une adresse séquentielle non-utilisée.
    """
    if seed:
        idx = int(hashlib.md5(f"AU::{seed}".encode()).hexdigest(), 16) % len(AUSTRALIA_ADDRESSES)
        return AUSTRALIA_ADDRESSES[idx]
    for i in range(len(AUSTRALIA_ADDRESSES)):
        if i not in _used_indices:
            _used_indices.add(i)
            return AUSTRALIA_ADDRESSES[i]
    return _generate_one(random.Random())


def get_all_australia_addresses() -> list:
    return list(AUSTRALIA_ADDRESSES)


def reset_used_australia():
    _used_indices.clear()


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"Pool total : {len(AUSTRALIA_ADDRESSES)} adresses\n")
    for i in range(n):
        print(f"#{i+1:04d}  {AUSTRALIA_ADDRESSES[i]}")
