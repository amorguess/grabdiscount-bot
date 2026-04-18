#!/usr/bin/env python3
"""
Pipeline single-shot : iCloud email → SMSPool numéro TH → Grab emulator
Usage : python3 run_one.py [DEVICE_ID]
"""
import os, sys, json, datetime, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE       = Path(__file__).parent
ACCOUNTS_F = BASE / "accounts.json"
DEVICE_ID  = sys.argv[1] if len(sys.argv) > 1 else "emulator-5554"

def rj(p, default=None):
    try:   return json.loads(Path(p).read_text(encoding="utf-8"))
    except: return default if default is not None else {}

def wj(p, data):
    tmp = str(p) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(tmp).replace(p)

def get_email():
    for a in rj(ACCOUNTS_F, []):
        if (a.get("status") == "available"
                and not a.get("grab_phone")
                and not a.get("grab_created")
                and not a.get("_locked")):
            return a["email"]
    return None

def lock_email(email):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a["_locked"] = True
            a["_locked_at"] = datetime.datetime.now().isoformat()
    wj(ACCOUNTS_F, accounts)

def mark_created(email, phone, ident, password, address):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a["status"]           = "grab_ready"
            a["grab_phone"]       = phone
            a["grab_created"]     = datetime.datetime.now().isoformat()
            a["grab_password"]    = password
            a["grab_name"]        = ident.get("full_name", "")
            a["grab_prenom"]      = ident.get("prenom", "")
            a["grab_nom"]         = ident.get("nom", "")
            a["grab_address"]     = address
            a.pop("_locked", None)
    wj(ACCOUNTS_F, accounts)

def mark_failed(email, reason):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a.pop("_locked", None)
            a["_fail_count"] = a.get("_fail_count", 0) + 1
            a["_last_error"] = reason
            if a.get("_fail_count", 0) >= 3:
                a["status"] = "failed"
    wj(ACCOUNTS_F, accounts)

def address_to_search_query(address: str) -> str:
    """Extrait une requête de recherche courte depuis l'adresse complète."""
    # Format: Room X, Building, Soi Road X, Road, SubDistrict, District, Bangkok CP
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 3:
        soi_part = parts[2]   # ex: "Soi Thong 10"
        road_part = parts[3] if len(parts) > 3 else ""  # ex: "Thong Lo Road"
        # Construire requête : "Thong Lo Soi 10"
        road_name = road_part.replace(" Road", "").strip()
        soi_num   = re.search(r"\d+", soi_part)
        if road_name and soi_num:
            return f"{road_name} Soi {soi_num.group()}"
        return soi_part if soi_part else road_part
    return "Thong Lo Soi 10"

def main():
    # ── 1. Clé SMSPool ────────────────────────────────────────────────────
    pool_key = os.environ.get("SMSPOOL_KEY", "")
    if not pool_key:
        print("❌ SMSPOOL_KEY manquant dans .env")
        sys.exit(1)

    from sms_gen.smspool import SMSPool, SMSPoolError
    pool = SMSPool(pool_key)
    bal  = pool.balance()
    print(f"💰 SMSPool solde : ${bal:.2f}")
    if bal < 0.10:
        print("❌ Solde insuffisant (min $0.10)")
        sys.exit(1)

    # ── 2. Email iCloud ───────────────────────────────────────────────────
    email = get_email()
    if not email:
        print("❌ Aucun email iCloud disponible dans accounts.json")
        sys.exit(1)
    print(f"📧 Email : {email}")
    lock_email(email)

    # ── 3. Identité + adresse Bangkok ─────────────────────────────────────
    sys.path.insert(0, str(BASE))
    from identity_gen import generate_identity, get_bangkok_address
    ident   = generate_identity(seed=email)
    address = get_bangkok_address(seed=email)
    search  = address_to_search_query(address)
    password = "Grab2024lol!"
    print(f"👤 Identité  : {ident['full_name']}")
    print(f"📍 Adresse   : {address[:70]}")
    print(f"🔍 Recherche : {search}")

    # ── 4. Acheter numéro Thaïlande ───────────────────────────────────────
    print("\n📱 Achat numéro Grab Thailand (SMSPool)…")
    order = oid = phone = local_number = None
    try:
        order  = pool.buy_for_grab("thailand")
        phone  = order["phone"]          # ex: +66997088425
        oid    = order["id"]
        local_number = phone.lstrip("+")
        if local_number.startswith("66"):
            local_number = local_number[2:]  # → 997088425
        print(f"   ✅ Numéro  : {phone}")
        print(f"   🆔 Order   : {oid}")
    except SMSPoolError as e:
        print(f"❌ SMSPool : {e}")
        mark_failed(email, str(e))
        sys.exit(1)

    # ── 5. Inscription Grab sur l'émulateur ──────────────────────────────
    from grab_gen.grab_app import GrabApp, GrabAppError
    print(f"\n📲 Lancement GrabApp sur {DEVICE_ID}…")
    try:

        # Nettoyer AVANT d'ouvrir la session Appium (sinon Appium ne relance pas l'app)
        import subprocess, time
        ADB = str(Path.home() / "Library/Android/sdk/platform-tools/adb")
        subprocess.run([ADB, "-s", DEVICE_ID, "shell", "pm", "clear", "com.grabtaxi.passenger"],
                       capture_output=True)
        time.sleep(3)
        print("   App data cleared ✅")

        with GrabApp(DEVICE_ID) as app:
            # Navigation → Sign Up (inclut setup Bangkok avec adresse réelle)
            print("   → navigate_to_signup…")
            if not app.navigate_to_signup(search_query=search):
                raise GrabAppError("Navigation signup échouée")

            # Entrer numéro
            print(f"   → enter_phone {local_number}…")
            app.enter_phone(local_number, "+66")

            # Attente OTP
            print(f"   → Attente OTP (order {oid}, 90s max)…")
            try:
                otp = pool.wait_sms(oid, timeout=90, poll=5)
            except SMSPoolError as e:
                raise GrabAppError(f"OTP échoué : {e}")
            print(f"   ✅ OTP reçu : {otp}")

            # Saisir OTP
            app.enter_otp(otp)

            # Remplir profil
            ok = app.fill_profile(ident["full_name"], email, password)

            if ok:
                mark_created(email, phone, ident, password, address)
                print(f"\n✅ Compte Grab créé !")
                print(f"   📧 {email}")
                print(f"   📱 {phone}")
                print(f"   👤 {ident['full_name']}")
                print(f"   📍 {address[:60]}")
                print(f"   🔑 {password}")
            else:
                raise GrabAppError("fill_profile échoué — vérifier screenshot /tmp/grab_profile_done.png")

    except GrabAppError as e:
        print(f"\n❌ GrabApp : {e}")
        mark_failed(email, str(e))
        try: pool.cancel(oid)
        except: pass
        sys.exit(1)

if __name__ == "__main__":
    main()
