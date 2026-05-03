#!/usr/bin/env python3
"""setup_2fa.py — Génère un secret TOTP + QR-code provisioning pour la 2FA dashboard.

Usage :
  python3 scripts/setup_2fa.py
  python3 scripts/setup_2fa.py --label "GrabDiscount Admin"

Workflow :
1. Génère un secret base32 aléatoire (160 bits)
2. Affiche l'URI provisioning (otpauth://totp/...) → coller dans Authy / Google Auth
3. Affiche le QR code en ASCII (compat terminaux SSH)
4. Affiche la ligne à ajouter dans .env (DASHBOARD_TOTP_SECRET=...)

Une fois l'app authenticator lié et le secret en .env → restart dashboard.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    p = argparse.ArgumentParser(description="Setup 2FA TOTP pour le dashboard")
    p.add_argument("--label", default="GrabDiscount Admin",
                   help="Label affiché dans l'app authenticator")
    p.add_argument("--issuer", default="GrabDiscount",
                   help="Issuer affiché dans l'app authenticator")
    args = p.parse_args()

    try:
        import pyotp
    except ImportError:
        print("❌ pyotp manquant. Installe : pip install pyotp", file=sys.stderr)
        return 1

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=args.label, issuer_name=args.issuer)

    print()
    print("=" * 60)
    print("  Setup 2FA — GrabDiscount Dashboard")
    print("=" * 60)
    print()
    print(f"Secret TOTP (base32) : {secret}")
    print()
    print("URI de provisioning (compatible Authy / Google Auth / 1Password) :")
    print(f"  {uri}")
    print()

    # QR code ASCII (optionnel — nécessite qrcode)
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print("ℹ Pour afficher un QR-code en ASCII : pip install qrcode")
        print("  (alternative : copier l'URI dans un générateur de QR online)")
    print()

    print("=" * 60)
    print("  Étape suivante :")
    print("=" * 60)
    print()
    print("1. Scanner le QR (ou coller l'URI) dans ton authenticator")
    print("2. Ajouter cette ligne dans /root/grabdiscount/.env (sur le VPS) :")
    print()
    print(f"   DASHBOARD_TOTP_SECRET={secret}")
    print()
    print("3. Restart : systemctl restart grabdiscount")
    print("4. Login → un champ 'Code 2FA' apparaît en plus du mdp")
    print()
    print("⚠  Conserve ce secret en lieu sûr (1Password). Si perdu, reset depuis")
    print("   le VPS en regénérant un nouveau secret et l'app authenticator.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
