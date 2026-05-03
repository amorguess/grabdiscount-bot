#!/usr/bin/env python3
"""migrate_dual_zone.py — Migration accounts.json : ajout zones Uber AU + FR.

Pour chaque compte existant :
  - Ajoute uber_au_address (seed = email, déterministe via identity_gen.get_australia_address)
  - Ajoute uber_au_phone = "", uber_au_status = "available", uber_au_notes = "",
    uber_au_used_at = None, uber_au_phone_bought_at = None
  - Idem pour uber_fr_*

Idempotent : si uber_au_address (resp. uber_fr_*) est déjà set, on respecte.
Crée un backup horodaté avant écriture.

Usage :
  python3 scripts/migrate_dual_zone.py            # dry-run (affiche le plan)
  python3 scripts/migrate_dual_zone.py --apply    # applique réellement
  python3 scripts/migrate_dual_zone.py --apply --file /data/accounts.json
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import shutil
import sys
from pathlib import Path

GRAB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAB_DIR))

from identity_gen import get_australia_address, get_france_address  # noqa: E402

ZONES = [
    ("uber_au", get_australia_address),
    ("uber_fr", get_france_address),
]


def _read(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write(path: Path, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _ensure_zone(account: dict, prefix: str, addr_fn) -> bool:
    """Ajoute les champs {prefix}_* si absents. Retourne True si modifié."""
    addr_key = f"{prefix}_address"
    if account.get(addr_key):
        return False  # déjà migré

    email = account.get("email", "")
    if not email:
        return False  # squelette invalide → on ne touche pas

    account[addr_key]              = addr_fn(seed=email)
    account.setdefault(f"{prefix}_phone", "")
    account.setdefault(f"{prefix}_status", "available")
    account.setdefault(f"{prefix}_notes", "")
    account.setdefault(f"{prefix}_used_at", None)
    account.setdefault(f"{prefix}_phone_bought_at", None)
    account.setdefault(f"{prefix}_fail_count", 0)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migration dual-zone accounts.json")
    parser.add_argument("--file", default=str(GRAB_DIR / "accounts.json"),
                        help="Chemin accounts.json (défaut : ./accounts.json)")
    parser.add_argument("--apply", action="store_true",
                        help="Applique réellement (sinon dry-run)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"❌ Fichier introuvable : {path}", file=sys.stderr)
        return 1

    accounts = _read(path)
    print(f"📂 {len(accounts)} comptes lus depuis {path}")

    changes_au = 0
    changes_fr = 0
    untouched  = 0

    for acc in accounts:
        a = _ensure_zone(acc, "uber_au", get_australia_address)
        f = _ensure_zone(acc, "uber_fr", get_france_address)
        if a:
            changes_au += 1
        if f:
            changes_fr += 1
        if not a and not f:
            untouched += 1

    print(f"  • uber_au_* ajouté à : {changes_au}")
    print(f"  • uber_fr_* ajouté à : {changes_fr}")
    print(f"  • déjà à jour        : {untouched}")

    # Aperçu (3 premiers)
    if accounts:
        print("\n🔎 Aperçu (3 premiers) :")
        for acc in accounts[:3]:
            print(f"  {acc.get('email')}")
            print(f"    grab_th  : {acc.get('grab_bangkok_addr', '—')[:80]}")
            print(f"    uber_au  : {acc.get('uber_au_address', '—')[:80]}")
            print(f"    uber_fr  : {acc.get('uber_fr_address', '—')[:80]}")

    if not args.apply:
        print("\nℹ Dry-run terminé. Relance avec --apply pour écrire.")
        return 0

    # Backup avant écriture
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.parent / f"accounts_backup_dual_zone_{ts}.json"
    shutil.copy2(path, backup)
    print(f"\n💾 Backup : {backup.name}")

    _write(path, accounts)
    print(f"✅ accounts.json mis à jour ({changes_au + changes_fr} ajouts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
