"""
Générateur d'identités françaises réalistes
Prénoms + noms de famille — sans adresse postale (adresse = Bangkok)
"""
import random, hashlib

# ── Prénoms masculins ──────────────────────────────────────
PRENOMS_H = [
    "Thomas","Nicolas","Julien","Alexandre","Maxime","Antoine","Pierre","Lucas",
    "Romain","Clément","Hugo","Mathieu","Alexis","Baptiste","Quentin","Kevin",
    "Guillaume","Adrien","Damien","Florian","Arnaud","Cédric","Sébastien","Yann",
    "Loïc","Benoît","Christophe","Emmanuel","François","Gilles","Henri","Ivan",
    "Joachim","Laurent","Marc","Nathan","Olivier","Pascal","Raphaël","Samuel",
    "Théo","Ugo","Valentin","Xavier","Yoann","Zéphyr","Léo","Paul","Arthur","Louis",
    "Axel","Dorian","Ethan","Gabin","Ilyan","Jordan","Kévin","Luca","Mathis",
    "Noah","Oscar","Rayan","Sacha","Tom","Victor","William","Zachary","Enzo","Felix",
    "Gabriel","Hamza","Ilian","Julien","Killian","Lenny","Mathéo","Nathan","Nolan",
    "Rémi","Simon","Thibault","Tristan","Titouan","Willy","Yanis","Zinedine",
    "Antonin","Brice","Cyril","Dylan","Erwan","Fabien","Gaël","Hervé","Igor","Jérémy",
    "Kilian","Ludovic","Malo","Noé","Patrice","Quentin","Ronan","Stéphane","Tanguy",
]

# ── Prénoms féminins ──────────────────────────────────────
PRENOMS_F = [
    "Marie","Julie","Sophie","Camille","Laura","Léa","Emma","Clara","Lucie","Alice",
    "Manon","Chloé","Pauline","Sarah","Anaïs","Océane","Inès","Charlotte","Elisa",
    "Amélie","Aurélie","Céline","Delphine","Élodie","Fanny","Gwenaëlle","Hélène",
    "Isabelle","Jessica","Karen","Laure","Mélanie","Nathalie","Ophélie","Patricia",
    "Rébecca","Sandrine","Tiffany","Valentine","Yasmine","Zoé","Adèle","Bérénice",
    "Coralie","Doriane","Estelle","Florence","Jade","Lola","Margot","Nina","Oriane",
    "Alexia","Blanche","Cassandra","Diane","Eva","Giulia","Héloïse","Iris","Julia",
    "Karine","Lilou","Mathilde","Noemie","Priscilla","Romane","Stéphanie","Tania",
    "Vanessa","Wendy","Xénia","Ysaline","Zara","Agathe","Brunilde","Céleste","Daphné",
    "Eleonore","Fabienne","Gaëlle","Hortense","Ingrid","Justine","Kenza","Louise",
    "Maëlle","Naomi","Odile","Pénélope","Roxane","Sylvie","Tatiana","Ursule","Victoire",
]

PRENOMS = PRENOMS_H + PRENOMS_F

# ── Noms de famille ────────────────────────────────────────
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
    "Maillot","Rolland","Barbeau","Tessier","Hubert","Pons","Fleury","Barre",
    "Chabert","Delorme","Ferry","Gros","Huet","Jacquet","Klein","Leduc","Ménard",
    "Noël","Pérez","Rivière","Sabatier","Thibault","Vidal","Wagner","Xavier",
    "Ybert","Zimmermann","Adam","Bauer","Courtois","Dumas","Evrard","Forestier",
    "Gagnon","Hamelin","Isambert","Jacobs","Kramer","Lelong","Martel","Noel",
    "Oller","Pillet","Quentin","Rocher","Sauvage","Tardif","Ullmann","Verne",
]


def generate_identity(seed: str = "") -> dict:
    """
    Génère une identité française aléatoire (prénom + nom uniquement).
    seed = email pour reproductibilité.
    """
    rng = random.Random(
        int(hashlib.md5(seed.encode()).hexdigest(), 16) if seed else random.randint(0, 2**31)
    )
    prenom = rng.choice(PRENOMS)
    nom    = rng.choice(NOMS)
    return {
        "prenom":    prenom,
        "nom":       nom,
        "full_name": f"{prenom} {nom}",
    }


def generate_batch(n: int) -> list:
    """Génère n identités uniques."""
    seen = set()
    results = []
    attempts = 0
    while len(results) < n and attempts < n * 20:
        attempts += 1
        ident = generate_identity()
        key = (ident["prenom"], ident["nom"])
        if key not in seen:
            seen.add(key)
            results.append(ident)
    return results


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    for i, ident in enumerate(generate_batch(n), 1):
        print(f"#{i:03d}  {ident['full_name']}")
