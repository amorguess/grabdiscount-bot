"""
french_identity.py — Générateur d'identités françaises réalistes
=================================================================
Fichier autonome, zéro dépendance externe (stdlib uniquement).
Réutilisable dans n'importe quel projet Python 3.7+.

Usage en bibliothèque :
    from french_identity import generate_identity, generate_password, generate_pack

Usage CLI :
    python3 french_identity.py          # 5 identités
    python3 french_identity.py 20       # 20 identités
    python3 french_identity.py 10 --pass # avec mots de passe
"""
import random
import hashlib
import string

# ── Prénoms masculins ──────────────────────────────────────────────
PRENOMS_H = [
    "Thomas","Nicolas","Julien","Alexandre","Maxime","Antoine","Pierre","Lucas",
    "Romain","Clément","Hugo","Mathieu","Alexis","Baptiste","Quentin","Kevin",
    "Guillaume","Adrien","Damien","Florian","Arnaud","Cédric","Sébastien","Yann",
    "Loïc","Benoît","Christophe","Emmanuel","François","Gilles","Henri","Ivan",
    "Joachim","Laurent","Marc","Nathan","Olivier","Pascal","Raphaël","Samuel",
    "Théo","Ugo","Valentin","Xavier","Yoann","Léo","Paul","Arthur","Louis",
    "Axel","Dorian","Ethan","Gabin","Ilyan","Jordan","Kévin","Luca","Mathis",
    "Noah","Oscar","Rayan","Sacha","Tom","Victor","William","Zachary","Enzo","Felix",
    "Gabriel","Hamza","Ilian","Killian","Lenny","Mathéo","Nolan","Rémi","Simon",
    "Thibault","Tristan","Titouan","Willy","Yanis","Zinedine","Antonin","Brice",
    "Cyril","Dylan","Erwan","Fabien","Gaël","Hervé","Igor","Jérémy","Kilian",
    "Ludovic","Malo","Noé","Patrice","Ronan","Stéphane","Tanguy","Bruno","Maxence",
    "Pierrick","Matthieu","Benoit","Tomas","Léonard","Édouard","Théophile","Nathaniel",
]

# ── Prénoms féminins ──────────────────────────────────────────────
PRENOMS_F = [
    "Marie","Julie","Sophie","Camille","Laura","Léa","Emma","Clara","Lucie","Alice",
    "Manon","Chloé","Pauline","Sarah","Anaïs","Océane","Inès","Charlotte","Elisa",
    "Amélie","Aurélie","Céline","Delphine","Élodie","Fanny","Gwenaëlle","Hélène",
    "Isabelle","Jessica","Karen","Laure","Mélanie","Nathalie","Ophélie","Patricia",
    "Rébecca","Sandrine","Tiffany","Valentine","Yasmine","Zoé","Adèle","Bérénice",
    "Coralie","Doriane","Estelle","Florence","Jade","Lola","Margot","Nina","Oriane",
    "Alexia","Blanche","Cassandra","Diane","Eva","Giulia","Héloïse","Iris","Julia",
    "Karine","Lilou","Mathilde","Noemie","Priscilla","Romane","Stéphanie","Tania",
    "Vanessa","Wendy","Xénia","Ysaline","Zara","Agathe","Céleste","Daphné",
    "Eleonore","Fabienne","Gaëlle","Hortense","Ingrid","Justine","Kenza","Louise",
    "Maëlle","Naomi","Odile","Pénélope","Roxane","Sylvie","Tatiana","Victoire",
]

# ── Noms de famille ───────────────────────────────────────────────
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
    "Barbier","Arnaud","Couture","Olivier","Pierre","Brunet","Lucas","Benoit",
    "Daniel","Leblanc","Etienne","Hervé","Grondin","Poirier","Marty","Brun",
    "Maillot","Rolland","Tessier","Hubert","Pons","Fleury","Barre","Chabert",
    "Delorme","Ferry","Gros","Huet","Jacquet","Klein","Leduc","Ménard",
    "Noël","Pérez","Rivière","Sabatier","Thibault","Vidal","Wagner","Xavier",
    "Adam","Bauer","Courtois","Dumas","Evrard","Forestier","Gagnon","Hamelin",
    "Isambert","Jacobs","Kramer","Lelong","Martel","Oller","Pillet","Rocher",
    "Sauvage","Tardif","Ullmann","Verne","Lopez","Schmitt","Pons","Sabatier",
    "Leclerc","Clément","François","Girard","Garnier","Fontaine","Barre","Lucas",
]

PRENOMS_ALL = PRENOMS_H + PRENOMS_F

# ── Mots de passe ────────────────────────────────────────────────
_ALPHA  = string.ascii_letters
_DIGITS = string.digits
_SPEC   = "!@#$%"

def generate_password(length: int = 12, seed: str = "") -> str:
    """
    Génère un mot de passe fort (lettres + chiffres + symbole).
    Reproductible si seed fourni.
    """
    rng = random.Random(
        int(hashlib.md5((seed + "_pwd").encode()).hexdigest(), 16) if seed else random.randint(0, 2**31)
    )
    charset = _ALPHA + _DIGITS
    # Au moins 1 chiffre, 1 majuscule, 1 minuscule
    pwd = [
        rng.choice(string.ascii_uppercase),
        rng.choice(string.ascii_lowercase),
        rng.choice(_DIGITS),
        rng.choice(_DIGITS),
    ]
    pwd += [rng.choice(charset) for _ in range(length - len(pwd))]
    rng.shuffle(pwd)
    return "".join(pwd)


# ── API principale ────────────────────────────────────────────────

def generate_identity(seed: str = "") -> dict:
    """
    Génère une identité française aléatoire.

    Args:
        seed: Chaîne pour rendre le résultat reproductible (ex: email).
              Laisser vide pour un résultat aléatoire.

    Returns:
        dict avec clés: prenom, nom, full_name, genre
    """
    rng = random.Random(
        int(hashlib.md5(seed.encode()).hexdigest(), 16) if seed else random.randint(0, 2**31)
    )
    genre  = rng.choice(["M", "F"])
    prenom = rng.choice(PRENOMS_H if genre == "M" else PRENOMS_F)
    nom    = rng.choice(NOMS)
    return {
        "prenom":    prenom,
        "nom":       nom,
        "full_name": f"{prenom} {nom}",
        "genre":     genre,
    }


def generate_pack(seed: str = "", pwd_length: int = 12) -> dict:
    """
    Génère un pack complet : identité + mot de passe fort.

    Args:
        seed: Seed pour reproductibilité (ex: email iCloud).
        pwd_length: Longueur du mot de passe (défaut 12).

    Returns:
        dict: prenom, nom, full_name, genre, password
    """
    ident = generate_identity(seed)
    ident["password"] = generate_password(pwd_length, seed)
    return ident


def generate_batch(n: int, with_password: bool = False, pwd_length: int = 12) -> list:
    """
    Génère n identités uniques.

    Args:
        n: Nombre d'identités à générer.
        with_password: Inclure un mot de passe dans chaque identité.
        pwd_length: Longueur du mot de passe.

    Returns:
        Liste de dicts.
    """
    seen    = set()
    results = []
    rng     = random.Random()
    attempts = 0

    while len(results) < n and attempts < n * 30:
        attempts += 1
        seed  = str(rng.random())
        ident = generate_identity(seed)
        key   = (ident["prenom"], ident["nom"])
        if key not in seen:
            seen.add(key)
            if with_password:
                ident["password"] = generate_password(pwd_length, seed)
            results.append(ident)

    return results


# ── CLI ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    n           = int(args[0]) if args else 5
    with_pwd    = "--pass" in flags or "--password" in flags
    pwd_len     = 12

    for f in flags:
        if f.startswith("--len="):
            try: pwd_len = int(f.split("=")[1])
            except: pass

    identities = generate_batch(n, with_password=with_pwd, pwd_length=pwd_len)

    print(f"{'#':<5} {'Prénom':<15} {'Nom':<20} {'Genre':<7}", end="")
    if with_pwd:
        print(f"  {'Mot de passe'}")
    else:
        print()
    print("-" * (50 + (20 if with_pwd else 0)))

    for i, ident in enumerate(identities, 1):
        line = f"{i:<5} {ident['prenom']:<15} {ident['nom']:<20} {ident['genre']:<7}"
        if with_pwd:
            line += f"  {ident['password']}"
        print(line)
