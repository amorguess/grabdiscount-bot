"""Zones de service — mapping logique → champs `accounts.json`.

Chaque compte iCloud expose 3 zones indépendantes :
- `grab_th` : Grab Food Thaïlande (zone historique, champs legacy `status`, `grab_*`)
- `uber_au` : Uber Eats Australie (champs préfixés `uber_au_*`)
- `uber_fr` : Uber Eats France (champs préfixés `uber_fr_*`)

Les statuts, numéros de téléphone et historique d'usage sont 100 % indépendants
par zone : un compte `used` côté Grab TH peut rester `available` côté Uber AU.

Le mapping ci-dessous évite la string-magic et concentre la rétrocompat legacy
(zone `grab_th` réutilise les champs plats sans préfixe pour ne pas casser le
dashboard 5001).
"""

from __future__ import annotations

from enum import StrEnum


class Zone(StrEnum):
    """Plateforme + pays de livraison d'un compte."""

    GRAB_TH = "grab_th"
    UBER_AU = "uber_au"
    UBER_FR = "uber_fr"


# Champs JSON par zone (logique → clef réelle dans accounts.json).
# `grab_th` = champs legacy plats (compat dashboard 5001).
_FIELDS: dict[Zone, dict[str, str]] = {
    Zone.GRAB_TH: {
        "status":         "status",
        "address":        "grab_bangkok_addr",
        "phone":          "grab_phone",
        "notes":          "grab_notes",
        "used_at":        "used_at",
        "phone_bought_at":"phone_bought_at",
        "fail_count":     "_fail_count",
        "locked_at":      "_locked_at",
    },
    Zone.UBER_AU: {
        "status":         "uber_au_status",
        "address":        "uber_au_address",
        "phone":          "uber_au_phone",
        "notes":          "uber_au_notes",
        "used_at":        "uber_au_used_at",
        "phone_bought_at":"uber_au_phone_bought_at",
        "fail_count":     "uber_au_fail_count",
        "locked_at":      "uber_au_locked_at",
    },
    Zone.UBER_FR: {
        "status":         "uber_fr_status",
        "address":        "uber_fr_address",
        "phone":          "uber_fr_phone",
        "notes":          "uber_fr_notes",
        "used_at":        "uber_fr_used_at",
        "phone_bought_at":"uber_fr_phone_bought_at",
        "fail_count":     "uber_fr_fail_count",
        "locked_at":      "uber_fr_locked_at",
    },
}


def field(zone: Zone | str, logical_name: str) -> str:
    """Résout un nom logique (`status`, `phone`, `address`...) en clef JSON.

    Lève KeyError si la zone ou le nom logique est inconnu — fail-fast est
    préférable au silent fallback : un typo dans `field(z, "stat")` doit
    péter à l'écriture, pas corrompre des données.
    """
    z = Zone(zone) if isinstance(zone, str) else zone
    return _FIELDS[z][logical_name]


def zone_status(account: dict, zone: Zone | str) -> str:
    """Lit le statut d'une zone donnée sur un compte. `available` par défaut."""
    return account.get(field(zone, "status"), "available")


def zone_address(account: dict, zone: Zone | str) -> str:
    """Lit l'adresse de livraison de la zone."""
    return account.get(field(zone, "address"), "")


def all_zones() -> tuple[Zone, ...]:
    return (Zone.GRAB_TH, Zone.UBER_AU, Zone.UBER_FR)
