"""
Pipeline complet : iCloud email → numéro OnOff → OTP → compte Grab
Usage : python3 pipeline.py --onoff-email x@x.com --onoff-pass xxx --phone +33XXXXXXXXX
"""
import asyncio, argparse, json, datetime, sys, re
from pathlib import Path

BASE        = Path(__file__).parent.parent
ACCOUNTS_F  = BASE / "accounts.json"

def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return []

def wj(p, data):
    tmp = str(p) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(tmp).replace(p)

# ── Étape 1 : Choisit l'email iCloud suivant disponible ───────
def get_next_email() -> str | None:
    accounts = rj(ACCOUNTS_F)
    for a in accounts:
        if a.get("status") == "available" and not a.get("grab_phone") and not a.get("grab_created"):
            return a["email"]
    return None

# ── Étape finale : Sauvegarde le compte créé ──────────────────
def mark_account_created(email: str, phone: str, ident: dict = None, password: str = ""):
    accounts = rj(ACCOUNTS_F)
    for a in accounts:
        if a["email"] == email:
            a["status"]        = "grab_created"
            a["grab_phone"]    = phone
            a["grab_created"]  = datetime.datetime.now().isoformat()
            if password:
                a["grab_password"] = password
            if ident:
                a["grab_name"]    = ident.get("full_name", "")
                a["grab_adresse"] = ident.get("adresse_full", "")
                a["grab_ville"]   = ident.get("ville", "")
                a["grab_cp"]      = ident.get("cp", "")
            break
    wj(ACCOUNTS_F, accounts)
    print(f"[Pipeline] ✅ Compte Grab sauvegardé → {email} / {phone}")


# ── Pipeline principal ─────────────────────────────────────────
async def run_pipeline(
    onoff_email:  str,
    onoff_pass:   str,
    phone_number: str,     # numéro OnOff avec indicatif ex: "+33612345678"
    icloud_email: str = "",  # laisser vide = prend le prochain disponible
    headless:     bool = True,
    otp_channel:  str = "sms",   # "sms" ou "whatsapp"
):
    from grab_gen.onoff   import OnOffClient, OnOffError
    from grab_gen.grab_reg import GrabRegistration, GrabRegError

    # ── Sélection email ────────────────────────────────────────
    email = icloud_email or get_next_email()
    if not email:
        print("[Pipeline] ❌ Aucun email iCloud disponible dans accounts.json")
        return None

    print(f"\n{'━'*55}")
    print(f"[Pipeline] 🚀 Démarrage")
    print(f"  📧 Email iCloud : {email}")
    print(f"  📱 Numéro OnOff : {phone_number}")
    print(f"  📡 Canal OTP    : {otp_channel.upper()}")
    print(f"{'━'*55}\n")

    # Parse indicatif / numéro local
    m = re.match(r'(\+\d{1,3})(.*)', phone_number.replace(" ", ""))
    if not m:
        print("[Pipeline] ❌ Format numéro invalide (ex: +33612345678)")
        return None
    country_code = m.group(1)
    local_number = m.group(2)

    # ── Génère identité française + mot de passe ──────────────
    import secrets, string as _s
    from grab_gen.fake_fr import generate_identity
    ident    = generate_identity(seed=email)   # reproductible depuis l'email
    alphabet = _s.ascii_letters + _s.digits + "!@#$"
    password = "Grab" + "".join(secrets.choice(alphabet) for _ in range(10)) + "1!"

    print(f"[Pipeline] 👤 Identité : {ident['full_name']}")
    print(f"[Pipeline] 📍 Adresse  : {ident['adresse_full']}")

    # ── Grab Registration ──────────────────────────────────────
    print("[Pipeline] 🌐 Ouverture Grab signup…")
    async with GrabRegistration(headless=headless) as gr:

        # Étape 1 : entre le numéro
        ok = await gr.enter_phone(local_number, country_code)
        if not ok:
            print("[Pipeline] ❌ Échec saisie téléphone")
            return None

        # Choix WhatsApp si demandé
        if otp_channel == "whatsapp":
            await gr.choose_whatsapp_otp()

        # ── OnOff : attend le SMS ──────────────────────────────
        print(f"\n[Pipeline] 📲 Connexion OnOff pour lire le SMS…")
        otp_code = None

        async with OnOffClient(onoff_email, onoff_pass, headless=headless) as oc:
            await oc.login()
            sms_text = await oc.wait_sms(phone_number, keyword="Grab", timeout=90)
            if sms_text:
                code_m = re.search(r'\b(\d{4,8})\b', sms_text)
                otp_code = code_m.group(1) if code_m else None

        if not otp_code:
            print("[Pipeline] ❌ OTP non reçu dans les délais")
            return None

        print(f"[Pipeline] ✅ OTP reçu : {otp_code}")

        # ── Étape 2 : entre l'OTP ─────────────────────────────
        # Reprise de la session Grab (le navigateur est déjà ouvert)
        ok = await gr.enter_otp(otp_code)
        if not ok:
            print("[Pipeline] ❌ OTP rejeté ou étape suivante introuvable")
            return None

        # ── Étape 3 : remplit le profil ───────────────────────
        # Génère un nom aléatoire crédible
        first_names = ["Alex", "Chris", "Sam", "Jordan", "Morgan", "Taylor", "Jamie"]
        last_names  = ["Martin", "Smith", "Brown", "Wilson", "Davis", "Lee"]
        import random
        name = f"{random.choice(first_names)} {random.choice(last_names)}"

        ok = await gr.fill_profile(name=ident["full_name"], email=email, password=password)
        if not ok:
            print("[Pipeline] ⚠ Finalisation incertaine — voir /tmp/grab_final.png")

    # ── Sauvegarde ────────────────────────────────────────────
    result = {
        "icloud_email": email,
        "phone":        phone_number,
        "password":     password,
        "name":         ident["full_name"],
        "adresse":      ident["adresse_full"],
        "ville":        ident["ville"],
        "cp":           ident["cp"],
        "created_at":   datetime.datetime.now().isoformat(),
        "status":       "created" if ok else "uncertain",
    }
    mark_account_created(email, phone_number, ident=ident, password=password)

    print(f"\n{'━'*55}")
    print(f"[Pipeline] 🎉 COMPTE GRAB CRÉÉ !")
    print(f"  📧 Login    : {email}")
    print(f"  🔑 Password : {password}")
    print(f"  📱 Phone    : {phone_number}")
    print(f"{'━'*55}\n")

    return result


# ── CLI ────────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser(description="Crée un compte Grab automatiquement")
    ap.add_argument("--onoff-email",  required=True,  help="Email du compte OnOff")
    ap.add_argument("--onoff-pass",   required=True,  help="Mot de passe OnOff")
    ap.add_argument("--phone",        required=True,  help="Numéro OnOff avec indicatif ex: +33612345678")
    ap.add_argument("--icloud-email", default="",     help="Email iCloud à utiliser (optionnel)")
    ap.add_argument("--channel",      default="sms",  choices=["sms","whatsapp"], help="Canal OTP")
    ap.add_argument("--visible",      action="store_true", help="Affiche le navigateur")
    args = ap.parse_args()

    result = await run_pipeline(
        onoff_email  = args.onoff_email,
        onoff_pass   = args.onoff_pass,
        phone_number = args.phone,
        icloud_email = args.icloud_email,
        headless     = not args.visible,
        otp_channel  = args.channel,
    )

    if result:
        print(json.dumps(result, indent=2))
    else:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
