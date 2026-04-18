"""
Générateur d'identités françaises réalistes
Noms, prénoms et adresses postales — villes & régions variées
"""
import random, hashlib

# ── Prénoms ────────────────────────────────────────────────────
PRENOMS_H = [
    "Thomas","Nicolas","Julien","Alexandre","Maxime","Antoine","Pierre","Lucas",
    "Romain","Clément","Hugo","Mathieu","Alexis","Baptiste","Quentin","Kevin",
    "Guillaume","Adrien","Damien","Florian","Arnaud","Cédric","Sébastien","Yann",
    "Loïc","Benoît","Christophe","Emmanuel","François","Gilles","Henri","Ivan",
    "Joachim","Laurent","Marc","Nathan","Olivier","Pascal","Raphaël","Samuel",
    "Théo","Ugo","Valentin","Xavier","Yoann","Zéphyr","Léo","Paul","Arthur","Louis",
]
PRENOMS_F = [
    "Marie","Julie","Sophie","Camille","Laura","Léa","Emma","Clara","Lucie","Alice",
    "Manon","Chloé","Pauline","Sarah","Anaïs","Océane","Inès","Charlotte","Elisa",
    "Amélie","Aurélie","Céline","Delphine","Élodie","Fanny","Gwenaëlle","Hélène",
    "Isabelle","Jessica","Karen","Laure","Mélanie","Nathalie","Ophélie","Patricia",
    "Rébecca","Sandrine","Tiffany","Valentine","Yasmine","Zoé","Adèle","Bérénice",
    "Coralie","Doriane","Estelle","Florence","Jade","Lola","Margot","Nina","Oriane",
]
PRENOMS = PRENOMS_H + PRENOMS_F

# ── Noms de famille ────────────────────────────────────────────
NOMS = [
    "Martin","Bernard","Dubois","Thomas","Robert","Richard","Petit","Durand",
    "Leroy","Moreau","Simon","Laurent","Lefebvre","Michel","Garcia","David",
    "Bertrand","Roux","Vincent","Fournier","Morel","Girard","André","Lefèvre",
    "Mercier","Dupont","Lambert","Bonnet","François","Martinez","Legrand","Garnier",
    "Faure","Rousseau","Blanc","Guérin","Muller","Henry","Roussel","Nicolas",
    "Perrin","Morin","Mathieu","Clément","Gauthier","Dumont","Lopez","Fontaine",
    "Chevalier","Robin","Masson","Sanchez","Gérard","Nguyen","Boyer","Denis",
    "Lemaire","Steiner","Renard","Schmitt","Roy","Lecomte","Pellegrini","Aubert",
    "Marchand","Giraud","Ferreira","Carpentier","Collet","Charpentier","Gilles",
    "Picard","Bourgeois","Colin","Renaud","Lacroix","Joly","Vasseur","Leclerc",
]

# ── Types de voies ─────────────────────────────────────────────
VOIES = [
    "Rue","Avenue","Boulevard","Impasse","Allée","Passage","Place","Chemin",
    "Route","Voie","Square","Résidence","Cité","Domaine","Hameau",
]

# ── Noms de voies ─────────────────────────────────────────────
NOMS_VOIES = [
    "de la Paix","Victor Hugo","Jean Jaurès","de la République","des Lilas",
    "des Fleurs","du Général de Gaulle","de la Liberté","Émile Zola","Jules Ferry",
    "Georges Pompidou","François Mitterrand","Jean Moulin","de la Fontaine",
    "des Rossignols","du Moulin","de la Forêt","Saint-Exupéry","Pasteur",
    "Molière","Voltaire","Rousseau","Rimbaud","Verlaine","Balzac","Flaubert",
    "du Commerce","de l'Église","du Château","des Écoles","du Stade",
    "de la Gare","des Acacias","des Cerisiers","des Peupliers","des Marronniers",
    "du Bois","de la Colline","du Vallon","de la Prairie","des Champs",
    "du Soleil","de la Lune","des Étoiles","de l'Aurore","du Levant",
    "Aristide Briand","Léon Blum","Simone de Beauvoir","Marie Curie","Albert Camus",
]

# ── Villes par région (ville, cp, département) ────────────────
VILLES = [
    # Île-de-France
    ("Versailles",       "78000", "Yvelines"),
    ("Saint-Denis",      "93200", "Seine-Saint-Denis"),
    ("Créteil",          "94000", "Val-de-Marne"),
    ("Nanterre",         "92000", "Hauts-de-Seine"),
    ("Évry-Courcouronnes","91000","Essonne"),
    ("Cergy",            "95000", "Val-d'Oise"),
    ("Melun",            "77000", "Seine-et-Marne"),
    ("Pontoise",         "95300", "Val-d'Oise"),
    # Auvergne-Rhône-Alpes
    ("Lyon",             "69001", "Rhône"),
    ("Grenoble",         "38000", "Isère"),
    ("Clermont-Ferrand", "63000", "Puy-de-Dôme"),
    ("Saint-Étienne",    "42000", "Loire"),
    ("Annecy",           "74000", "Haute-Savoie"),
    ("Chambéry",         "73000", "Savoie"),
    ("Valence",          "26000", "Drôme"),
    ("Roanne",           "42300", "Loire"),
    ("Bourg-en-Bresse",  "01000", "Ain"),
    # Nouvelle-Aquitaine
    ("Bordeaux",         "33000", "Gironde"),
    ("Limoges",          "87000", "Haute-Vienne"),
    ("Poitiers",         "86000", "Vienne"),
    ("La Rochelle",      "17000", "Charente-Maritime"),
    ("Pau",              "64000", "Pyrénées-Atlantiques"),
    ("Bayonne",          "64100", "Pyrénées-Atlantiques"),
    ("Périgueux",        "24000", "Dordogne"),
    ("Agen",             "47000", "Lot-et-Garonne"),
    ("Angoulême",        "16000", "Charente"),
    # Occitanie
    ("Toulouse",         "31000", "Haute-Garonne"),
    ("Montpellier",      "34000", "Hérault"),
    ("Nîmes",            "30000", "Gard"),
    ("Perpignan",        "66000", "Pyrénées-Orientales"),
    ("Albi",             "81000", "Tarn"),
    ("Carcassonne",      "11000", "Aude"),
    ("Tarbes",           "65000", "Hautes-Pyrénées"),
    ("Béziers",          "34500", "Hérault"),
    # Provence-Alpes-Côte d'Azur
    ("Marseille",        "13001", "Bouches-du-Rhône"),
    ("Nice",             "06000", "Alpes-Maritimes"),
    ("Toulon",           "83000", "Var"),
    ("Aix-en-Provence",  "13100", "Bouches-du-Rhône"),
    ("Avignon",          "84000", "Vaucluse"),
    ("Cannes",           "06400", "Alpes-Maritimes"),
    ("Antibes",          "06600", "Alpes-Maritimes"),
    ("Fréjus",           "83600", "Var"),
    # Grand Est
    ("Strasbourg",       "67000", "Bas-Rhin"),
    ("Reims",            "51100", "Marne"),
    ("Metz",             "57000", "Moselle"),
    ("Mulhouse",         "68100", "Haut-Rhin"),
    ("Nancy",            "54000", "Meurthe-et-Moselle"),
    ("Colmar",           "68000", "Haut-Rhin"),
    ("Troyes",           "10000", "Aube"),
    ("Épinal",           "88000", "Vosges"),
    # Hauts-de-France
    ("Lille",            "59000", "Nord"),
    ("Amiens",           "80000", "Somme"),
    ("Roubaix",          "59100", "Nord"),
    ("Dunkerque",        "59140", "Nord"),
    ("Calais",           "62100", "Pas-de-Calais"),
    ("Lens",             "62300", "Pas-de-Calais"),
    ("Valenciennes",     "59300", "Nord"),
    ("Beauvais",         "60000", "Oise"),
    # Normandie
    ("Rouen",            "76000", "Seine-Maritime"),
    ("Caen",             "14000", "Calvados"),
    ("Le Havre",         "76600", "Seine-Maritime"),
    ("Cherbourg-en-Cotentin","50100","Manche"),
    ("Alençon",          "61000", "Orne"),
    ("Évreux",           "27000", "Eure"),
    # Bretagne
    ("Rennes",           "35000", "Ille-et-Vilaine"),
    ("Brest",            "29200", "Finistère"),
    ("Quimper",          "29000", "Finistère"),
    ("Lorient",          "56100", "Morbihan"),
    ("Vannes",           "56000", "Morbihan"),
    ("Saint-Malo",       "35400", "Ille-et-Vilaine"),
    ("Saint-Brieuc",     "22000", "Côtes-d'Armor"),
    # Pays de la Loire
    ("Nantes",           "44000", "Loire-Atlantique"),
    ("Le Mans",          "72000", "Sarthe"),
    ("Angers",           "49000", "Maine-et-Loire"),
    ("Saint-Nazaire",    "44600", "Loire-Atlantique"),
    ("Laval",            "53000", "Mayenne"),
    # Centre-Val de Loire
    ("Tours",            "37000", "Indre-et-Loire"),
    ("Orléans",          "45000", "Loiret"),
    ("Bourges",          "18000", "Cher"),
    ("Blois",            "41000", "Loir-et-Cher"),
    ("Chartres",         "28000", "Eure-et-Loir"),
    # Bourgogne-Franche-Comté
    ("Dijon",            "21000", "Côte-d'Or"),
    ("Besançon",         "25000", "Doubs"),
    ("Belfort",          "90000", "Territoire de Belfort"),
    ("Chalon-sur-Saône", "71100", "Saône-et-Loire"),
    ("Mâcon",            "71000", "Saône-et-Loire"),
]


def generate_identity(seed: str = "") -> dict:
    """
    Génère une identité française aléatoire et reproductible si seed fourni.
    Retourne : {prenom, nom, full_name, adresse, ville, cp, departement, pays}
    """
    rng = random.Random(
        int(hashlib.md5(seed.encode()).hexdigest(), 16) if seed else random.randint(0, 2**31)
    )

    prenom = rng.choice(PRENOMS)
    nom    = rng.choice(NOMS)
    ville, cp, dept = rng.choice(VILLES)

    numero = rng.randint(1, 120)
    voie   = rng.choice(VOIES)
    nom_v  = rng.choice(NOMS_VOIES)

    # Parfois ajoute un complément (appt, bâtiment…)
    complement = ""
    if rng.random() < 0.3:
        complement = rng.choice([
            f"Appartement {rng.randint(1,50)}",
            f"Bâtiment {rng.choice(['A','B','C','D'])}",
            f"Résidence Les {rng.choice(['Pins','Roses','Lilas','Chênes'])}",
        ])

    adresse_ligne1 = f"{numero} {voie} {nom_v}"
    adresse_ligne2 = complement

    return {
        "prenom":      prenom,
        "nom":         nom,
        "full_name":   f"{prenom} {nom}",
        "adresse1":    adresse_ligne1,
        "adresse2":    adresse_ligne2,
        "ville":       ville,
        "cp":          cp,
        "departement": dept,
        "pays":        "France",
        # Format compact pour formulaires
        "adresse_full": f"{adresse_ligne1}{', ' + adresse_ligne2 if adresse_ligne2 else ''}, {cp} {ville}, France",
    }


def generate_batch(n: int) -> list[dict]:
    """Génère n identités toutes différentes."""
    seen = set()
    results = []
    attempts = 0
    while len(results) < n and attempts < n * 10:
        attempts += 1
        ident = generate_identity()
        key = (ident["prenom"], ident["nom"], ident["ville"])
        if key not in seen:
            seen.add(key)
            results.append(ident)
    return results


if __name__ == "__main__":
    import json, sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    for i, ident in enumerate(generate_batch(n), 1):
        print(f"\n{'─'*50}")
        print(f"  #{i}  {ident['full_name']}")
        print(f"  {ident['adresse1']}")
        if ident['adresse2']:
            print(f"  {ident['adresse2']}")
        print(f"  {ident['cp']} {ident['ville']} ({ident['departement']})")
        print(f"  {ident['pays']}")
