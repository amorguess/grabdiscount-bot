#!/usr/bin/env python3
"""post_process_emails.py — Associe chaque email iCloud nouvellement généré à :
  - une identité française (prénom + nom) unique via identity_gen
  - une adresse postale Bangkok via identity_gen
puis l'ajoute à accounts.json avec status="available" (prêt pour ajout numéro + création compte Grab).

Appelé par auto_generate.sh après `run.py generate`. Idempotent : les emails déjà présents
dans accounts.json sont ignorés.

Utilise fcntl.flock pour éviter les races avec le dashboard Flask.
"""
import datetime
import fcntl
import json
import os
import sys
from pathlib import Path

GRAB_DIR    = Path(__file__).resolve().parent.parent
ICLOUD_DIR  = GRAB_DIR / "icloud_gen"
EMAILS_F    = ICLOUD_DIR / "emails.txt"
ACCOUNTS_F  = Path(os.environ.get("DATA_DIR", str(GRAB_DIR))) / "accounts.json"

# identity_gen est dans GRAB_DIR
sys.path.insert(0, str(GRAB_DIR))
from identity_gen import (  # noqa: E402
    generate_identity,
    get_bangkok_address,
    get_australia_address,
    get_france_address,
)


def _read_accounts():
    if not ACCOUNTS_F.exists():
        return []
    with open(ACCOUNTS_F, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write_accounts(data):
    ACCOUNTS_F.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_F, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _make_unique_identity(email: str, used_names: set) -> dict:
    """Génère identité française unique + 3 adresses (TH / AU / FR) déterministes par seed."""
    suffix = 0
    while True:
        seed = email if suffix == 0 else f"{email}_{suffix}"
        ident = generate_identity(seed=seed)
        key = (ident["prenom"], ident["nom"])
        if key not in used_names or suffix > 100:
            used_names.add(key)
            return {
                "grab_prenom":       ident["prenom"],
                "grab_nom":          ident["nom"],
                "grab_name":         ident["full_name"],
                # Zone Grab Thaïlande (legacy + champ historique)
                "grab_bangkok_addr": get_bangkok_address(seed=seed),
                # Zone Uber Eats Australie
                "uber_au_address":         get_australia_address(seed=seed),
                "uber_au_phone":           "",
                "uber_au_status":          "available",
                "uber_au_notes":           "",
                "uber_au_used_at":         None,
                "uber_au_phone_bought_at": None,
                "uber_au_fail_count":      0,
                # Zone Uber Eats France
                "uber_fr_address":         get_france_address(seed=seed),
                "uber_fr_phone":           "",
                "uber_fr_status":          "available",
                "uber_fr_notes":           "",
                "uber_fr_used_at":         None,
                "uber_fr_phone_bought_at": None,
                "uber_fr_fail_count":      0,
            }
        suffix += 1


def _new_account(email: str, ts: str, used_names: set) -> dict:
    entry = {
        "email":      email,
        "created":    ts,
        "status":     "available",  # statut zone Grab TH (legacy)
        "grab_phone": "",
        "grab_notes": "",
        "used_at":    None,
    }
    entry.update(_make_unique_identity(email, used_names))
    return entry


def main() -> int:
    try:
        lines = EMAILS_F.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print("❌ emails.txt introuvable", file=sys.stderr)
        return 1

    accounts = _read_accounts()
    existing = {a["email"]: a for a in accounts}
    used_names = {(a.get("grab_prenom", ""), a.get("grab_nom", ""))
                  for a in accounts if a.get("grab_prenom")}

    now_ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    added = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        email = line.split()[0]
        if "@icloud.com" not in email:
            continue
        if email in existing:
            continue
        existing[email] = _new_account(email, now_ts, used_names)
        added += 1

    if added:
        _write_accounts(list(existing.values()))
        print(f"✅ {added} nouveau(x) compte(s) ajouté(s) à accounts.json")
    else:
        print("ℹ Aucun nouveau email à importer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
