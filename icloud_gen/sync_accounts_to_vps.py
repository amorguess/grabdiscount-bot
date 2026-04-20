#!/usr/bin/env python3
"""
sync_accounts_to_vps.py — Merge Mac accounts.json → VPS /data/accounts.json.

Règles safe :
- VPS = source de vérité (il a les enrichissements admin : grab_name, grab_phone, etc.)
- On AJOUTE seulement les nouveaux emails Mac qui ne sont pas déjà sur VPS
- On ne TOUCHE PAS les entrées existantes sur VPS
- Backup VPS avant chaque push (rotation gardée 7j)

Usage :
    python3 sync_accounts_to_vps.py         # sync Mac → VPS
    python3 sync_accounts_to_vps.py --pull  # pull VPS → Mac (align Mac sur VPS)
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GRAB_DIR        = Path("/Users/donamor/grab")
MAC_ACCOUNTS    = GRAB_DIR / "accounts.json"
VPS_HOST        = "root@82.197.70.190"
VPS_PATH        = "/data/accounts.json"
TMP_VPS         = Path("/tmp/vps_accounts.json")
TMP_MERGED      = Path("/tmp/merged_accounts.json")
BACKUP_DIR_VPS  = "/data/backups"


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


def fetch_vps() -> list[dict]:
    code, out = run([
        "scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        f"{VPS_HOST}:{VPS_PATH}", str(TMP_VPS),
    ])
    if code != 0:
        raise RuntimeError(f"scp fetch failed: {out}")
    return json.loads(TMP_VPS.read_text(encoding="utf-8"))


def push_vps(path: Path) -> None:
    # Backup distant avant push
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run([
        "ssh", "-o", "StrictHostKeyChecking=no",
        VPS_HOST,
        f"mkdir -p {BACKUP_DIR_VPS} && cp {VPS_PATH} {BACKUP_DIR_VPS}/accounts_{ts}.json && "
        f"find {BACKUP_DIR_VPS} -name 'accounts_*.json' -mtime +7 -delete",
    ])
    code, out = run([
        "scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        str(path), f"{VPS_HOST}:{VPS_PATH}",
    ])
    if code != 0:
        raise RuntimeError(f"scp push failed: {out}")


def merge_mac_into_vps() -> tuple[int, int, int]:
    mac = json.loads(MAC_ACCOUNTS.read_text(encoding="utf-8"))
    vps = fetch_vps()

    vps_emails = {a.get("email"): i for i, a in enumerate(vps) if a.get("email")}
    added = 0
    skipped_existing = 0
    skipped_noemail = 0
    for a in mac:
        e = a.get("email")
        if not e:
            skipped_noemail += 1
            continue
        if e in vps_emails:
            skipped_existing += 1
            continue
        vps.append(a)
        added += 1

    TMP_MERGED.write_text(json.dumps(vps, ensure_ascii=False, indent=2), encoding="utf-8")
    if added > 0:
        push_vps(TMP_MERGED)
    return added, skipped_existing, skipped_noemail


def pull_vps_to_mac() -> int:
    vps = fetch_vps()
    # Backup local
    if MAC_ACCOUNTS.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = MAC_ACCOUNTS.with_name(f"accounts_backup_{ts}.json")
        backup.write_text(MAC_ACCOUNTS.read_text(encoding="utf-8"), encoding="utf-8")
    MAC_ACCOUNTS.write_text(json.dumps(vps, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(vps)


def main() -> int:
    if "--pull" in sys.argv:
        n = pull_vps_to_mac()
        print(f"✅ Pull OK — Mac aligné sur VPS ({n} comptes)")
        return 0

    try:
        added, skipped, noemail = merge_mac_into_vps()
    except Exception as e:
        print(f"❌ Sync échec: {e}")
        return 1
    if added == 0:
        print(f"✓ Rien à sync (VPS à jour, {skipped} comptes communs, {noemail} sans email)")
    else:
        print(f"✅ {added} compte(s) ajouté(s) au VPS · {skipped} existants préservés · {noemail} skip (sans email)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
