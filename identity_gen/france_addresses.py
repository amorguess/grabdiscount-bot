"""
Adresses résidentielles couvrant toute la France pour comptes Uber Eats FR.
Format : "Apt X, N Rue/Avenue/Boulevard ..., POSTCODE Ville"
Distribution pondérée par population : Paris > Lyon, Marseille > Toulouse, Nice...
Toutes les paires ville/code postal sont des correspondances réelles.
"""
import random
import hashlib

# ─────────────────────────────────────────────────────────────────
#  ZONES (ville, code_postal)
#  Pour Paris, chaque arrondissement = une entrée distincte (poids fort).
#  Pour les grandes villes, chaque code postal de district = une entrée.
# ─────────────────────────────────────────────────────────────────
ZONES = [
    # ── Paris (poids ~28%, 20 arrondissements) ────────────────
    ("Paris", "75001"), ("Paris", "75002"), ("Paris", "75003"), ("Paris", "75004"),
    ("Paris", "75005"), ("Paris", "75006"), ("Paris", "75007"), ("Paris", "75008"),
    ("Paris", "75009"), ("Paris", "75010"), ("Paris", "75011"), ("Paris", "75012"),
    ("Paris", "75013"), ("Paris", "75014"), ("Paris", "75015"), ("Paris", "75016"),
    ("Paris", "75017"), ("Paris", "75018"), ("Paris", "75019"), ("Paris", "75020"),
    # Petite couronne (banlieue Paris) — incluse dans la zone parisienne
    ("Boulogne-Billancourt", "92100"),
    ("Neuilly-sur-Seine",    "92200"),
    ("Levallois-Perret",     "92300"),
    ("Nanterre",             "92000"),
    ("Issy-les-Moulineaux",  "92130"),
    ("Courbevoie",           "92400"),
    ("Asnières-sur-Seine",   "92600"),
    ("Vincennes",            "94300"),
    ("Saint-Denis",          "93200"),
    ("Montreuil",            "93100"),
    ("Versailles",           "78000"),
    ("Saint-Germain-en-Laye","78100"),
    ("Cergy",                "95000"),
    ("Créteil",              "94000"),
    # ── Lyon (poids ~7%, 9 arrondissements) ───────────────────
    ("Lyon", "69001"), ("Lyon", "69002"), ("Lyon", "69003"), ("Lyon", "69004"),
    ("Lyon", "69005"), ("Lyon", "69006"), ("Lyon", "69007"), ("Lyon", "69008"),
    ("Lyon", "69009"),
    ("Villeurbanne", "69100"),
    ("Vénissieux",   "69200"),
    ("Caluire-et-Cuire", "69300"),
    # ── Marseille (poids ~7%, arrondissements) ────────────────
    ("Marseille", "13001"), ("Marseille", "13002"), ("Marseille", "13003"),
    ("Marseille", "13004"), ("Marseille", "13005"), ("Marseille", "13006"),
    ("Marseille", "13007"), ("Marseille", "13008"), ("Marseille", "13009"),
    ("Marseille", "13010"), ("Marseille", "13011"), ("Marseille", "13012"),
    ("Marseille", "13013"), ("Marseille", "13014"), ("Marseille", "13015"),
    ("Marseille", "13016"),
    ("Aix-en-Provence", "13100"),
    # ── Toulouse (poids ~5%) ──────────────────────────────────
    ("Toulouse", "31000"),
    ("Toulouse", "31100"),
    ("Toulouse", "31200"),
    ("Toulouse", "31300"),
    ("Toulouse", "31400"),
    ("Toulouse", "31500"),
    ("Colomiers",  "31770"),
    ("Tournefeuille", "31170"),
    # ── Nice (poids ~5%) ──────────────────────────────────────
    ("Nice", "06000"), ("Nice", "06100"), ("Nice", "06200"), ("Nice", "06300"),
    ("Cannes",        "06400"),
    ("Antibes",       "06600"),
    ("Cagnes-sur-Mer","06800"),
    # ── Nantes (poids ~4%) ────────────────────────────────────
    ("Nantes", "44000"),
    ("Nantes", "44100"),
    ("Nantes", "44200"),
    ("Nantes", "44300"),
    ("Saint-Herblain", "44800"),
    ("Rezé",           "44400"),
    # ── Strasbourg (poids ~4%) ────────────────────────────────
    ("Strasbourg", "67000"),
    ("Strasbourg", "67100"),
    ("Strasbourg", "67200"),
    ("Schiltigheim", "67300"),
    # ── Montpellier (poids ~4%) ───────────────────────────────
    ("Montpellier", "34000"),
    ("Montpellier", "34070"),
    ("Montpellier", "34080"),
    ("Montpellier", "34090"),
    # ── Bordeaux (poids ~4%) ──────────────────────────────────
    ("Bordeaux", "33000"),
    ("Bordeaux", "33100"),
    ("Bordeaux", "33200"),
    ("Bordeaux", "33300"),
    ("Bordeaux", "33800"),
    ("Mérignac", "33700"),
    ("Pessac",   "33600"),
    ("Talence",  "33400"),
    # ── Lille (poids ~4%) ─────────────────────────────────────
    ("Lille", "59000"),
    ("Lille", "59800"),
    ("Lille", "59160"),
    ("Lille", "59260"),
    ("Roubaix",   "59100"),
    ("Tourcoing", "59200"),
    ("Villeneuve-d'Ascq", "59650"),
    # ── Rennes (poids ~3%) ────────────────────────────────────
    ("Rennes", "35000"),
    ("Rennes", "35200"),
    ("Rennes", "35700"),
    ("Cesson-Sévigné", "35510"),
    # ── Reims (poids ~2%) ─────────────────────────────────────
    ("Reims", "51100"),
    ("Reims", "51420"),
    # ── Le Havre (poids ~2%) ──────────────────────────────────
    ("Le Havre", "76600"),
    ("Le Havre", "76610"),
    ("Le Havre", "76620"),
    # ── Saint-Étienne (poids ~2%) ─────────────────────────────
    ("Saint-Étienne", "42000"),
    ("Saint-Étienne", "42100"),
    # ── Toulon (poids ~2%) ────────────────────────────────────
    ("Toulon", "83000"),
    ("Toulon", "83100"),
    ("Toulon", "83200"),
    # ── Grenoble (poids ~2%) ──────────────────────────────────
    ("Grenoble", "38000"),
    ("Grenoble", "38100"),
    ("Échirolles", "38130"),
    # ── Dijon / Angers / Nîmes (poids ~2% chacun) ─────────────
    ("Dijon",  "21000"),
    ("Angers", "49000"),
    ("Angers", "49100"),
    ("Nîmes",  "30000"),
    ("Nîmes",  "30900"),
    # ── Brest / Limoges / Tours / Clermont-Ferrand ────────────
    ("Brest",            "29200"),
    ("Limoges",          "87000"),
    ("Limoges",          "87100"),
    ("Tours",            "37000"),
    ("Tours",            "37100"),
    ("Tours",            "37200"),
    ("Clermont-Ferrand", "63000"),
    ("Clermont-Ferrand", "63100"),
    # ── Amiens / Metz / Besançon / Orléans / Mulhouse ─────────
    ("Amiens",   "80000"),
    ("Amiens",   "80090"),
    ("Metz",     "57000"),
    ("Metz",     "57050"),
    ("Besançon", "25000"),
    ("Orléans",  "45000"),
    ("Orléans",  "45100"),
    ("Mulhouse", "68100"),
    ("Mulhouse", "68200"),
    # ── Caen / Nancy / Avignon / Poitiers ─────────────────────
    ("Caen",     "14000"),
    ("Nancy",    "54000"),
    ("Avignon",  "84000"),
    ("Poitiers", "86000"),
    ("Poitiers", "86180"),
    # ── La Rochelle / Pau / Annecy / Chambéry ─────────────────
    ("La Rochelle", "17000"),
    ("Pau",         "64000"),
    ("Annecy",      "74000"),
    ("Chambéry",    "73000"),
    # ── Régionales / mer / montagne ───────────────────────────
    ("Perpignan",   "66000"),
    ("Béziers",     "34500"),
    ("Sète",        "34200"),
    ("Biarritz",    "64200"),
    ("Bayonne",     "64100"),
    ("Saint-Malo",  "35400"),
    ("Quimper",     "29000"),
    ("Lorient",     "56100"),
    ("Vannes",      "56000"),
    ("Le Mans",     "72000"),
    ("Niort",       "79000"),
    ("Bourges",     "18000"),
    ("Troyes",      "10000"),
    ("Valence",     "26000"),
    ("Cherbourg-en-Cotentin", "50100"),
    ("Rouen",       "76000"),
    ("Rouen",       "76100"),
    # ── Outre-mer ─────────────────────────────────────────────
    ("Fort-de-France",   "97200"),
    ("Pointe-à-Pitre",   "97110"),
    ("Saint-Denis",      "97400"),  # La Réunion
    ("Cayenne",          "97300"),
    ("Nouméa",           "98800"),
    ("Papeete",          "98714"),
]

# ── Types de voies françaises ────────────────────────────────────
STREET_TYPES = [
    "Rue", "Avenue", "Boulevard", "Place", "Allée", "Chemin",
    "Impasse", "Quai", "Cours", "Square", "Passage", "Esplanade",
    "Route", "Voie", "Promenade", "Villa",
]

# ── Noms de rues récurrents (figures historiques + génériques) ──
STREET_NAMES = [
    # Figures historiques / République
    "de la République", "de la Liberté", "de l'Égalité", "de la Fraternité",
    "Victor Hugo", "Émile Zola", "Jean Jaurès", "Léon Blum", "Pasteur",
    "Gambetta", "Carnot", "Clemenceau", "Mendès France", "Jean Moulin",
    "Charles de Gaulle", "Général Leclerc", "Maréchal Foch", "Maréchal Joffre",
    "du 14 Juillet", "du 8 Mai 1945", "du 11 Novembre", "du 4 Septembre",
    "de Verdun", "de la Marne", "de la Somme", "de la Bastille",
    # Saints
    "Saint-Michel", "Saint-Jacques", "Saint-Antoine", "Saint-Honoré",
    "Saint-Germain", "Saint-Louis", "Saint-Denis", "Saint-Martin",
    "Sainte-Catherine", "Sainte-Anne", "Sainte-Marie",
    # Auteurs / artistes
    "Voltaire", "Rousseau", "Diderot", "Molière", "Racine", "Corneille",
    "Balzac", "Flaubert", "Maupassant", "Baudelaire", "Rimbaud", "Verlaine",
    "Mozart", "Beethoven", "Debussy", "Ravel", "Berlioz",
    "Monet", "Renoir", "Degas", "Cézanne", "Matisse", "Picasso",
    # Géographie
    "des Alpes", "des Pyrénées", "du Rhône", "de la Loire", "de la Seine",
    "de Provence", "de Bretagne", "de Bourgogne", "d'Alsace", "d'Aquitaine",
    "de Normandie", "du Languedoc", "de Champagne", "de Savoie",
    # Nature / arbres
    "des Acacias", "des Tilleuls", "des Marronniers", "des Platanes",
    "des Lilas", "des Roses", "des Violettes", "des Jasmins",
    "des Cerisiers", "des Pommiers", "des Vignes", "des Oliviers",
    "des Mimosas", "des Magnolias", "des Camélias",
    # Lieux-dits classiques
    "du Marché", "du Château", "de l'Église", "de la Mairie", "de la Gare",
    "de la Poste", "de la Fontaine", "des Écoles", "du Stade", "du Pont",
    "du Moulin", "de la Source", "des Champs", "des Prés", "du Bois",
    "de la Forêt", "du Lac", "de la Rivière", "de la Plage", "du Port",
    # Génériques
    "Principal", "Centrale", "Nationale", "Royale", "Impériale",
    "Neuve", "Vieille", "Haute", "Basse", "Grande", "Petite",
    # Numérotés (boulevards extérieurs Paris-style)
    "Diderot", "Beaumarchais", "Magenta", "Sébastopol", "Haussmann",
    "Malesherbes", "Pereire", "Voltaire", "Henri IV", "Saint-Marcel",
]


def _generate_one(rng: random.Random) -> str:
    """Génère une adresse française complète."""
    ville, postcode = rng.choice(ZONES)
    street_type = rng.choice(STREET_TYPES)
    street_name = rng.choice(STREET_NAMES)
    street_num  = rng.randint(1, 280)

    # 65% en immeuble (Apt N), 35% maison
    if rng.random() < 0.65:
        apt = rng.randint(1, 60)
        floor = rng.randint(0, 9)
        # Format réaliste : "Apt 12 (4e étage), 45 Rue ..., 75011 Paris"
        # Simplifié : "Apt 12, 45 Rue ..., 75011 Paris"
        return (
            f"Apt {apt}, {street_num} {street_type} {street_name}, "
            f"{postcode} {ville}"
        )
    else:
        return (
            f"{street_num} {street_type} {street_name}, "
            f"{postcode} {ville}"
        )


# ─────────────────────────────────────────────────────────────────
#  PRÉ-GÉNÉRATION DE 2000 ADRESSES UNIQUES
# ─────────────────────────────────────────────────────────────────
def _build_pool(n: int = 2000) -> list:
    rng  = random.Random(3314)  # seed fixe → déterministe
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


FRANCE_ADDRESSES: list = _build_pool(2000)


# ─────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────
_used_indices: set = set()


def get_france_address(seed: str = "") -> str:
    """
    Retourne une adresse française unique basée sur un seed (email).
    Sans seed : retourne une adresse séquentielle non-utilisée.
    """
    if seed:
        idx = int(hashlib.md5(f"FR::{seed}".encode()).hexdigest(), 16) % len(FRANCE_ADDRESSES)
        return FRANCE_ADDRESSES[idx]
    for i in range(len(FRANCE_ADDRESSES)):
        if i not in _used_indices:
            _used_indices.add(i)
            return FRANCE_ADDRESSES[i]
    return _generate_one(random.Random())


def get_all_france_addresses() -> list:
    return list(FRANCE_ADDRESSES)


def reset_used_france():
    _used_indices.clear()


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"Pool total : {len(FRANCE_ADDRESSES)} adresses\n")
    for i in range(n):
        print(f"#{i+1:04d}  {FRANCE_ADDRESSES[i]}")
