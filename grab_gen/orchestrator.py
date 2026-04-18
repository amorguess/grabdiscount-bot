"""
Orchestrateur permanent — crée des comptes Grab en boucle infinie
Lance un worker par device Android connecté
"""
import asyncio, json, datetime, re, time, subprocess, threading, sys, os, random
from pathlib import Path
import logging

BASE       = Path(__file__).parent.parent
ACCOUNTS_F = BASE / "accounts.json"
LOG_F      = BASE / "grab_gen" / "orchestrator.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_F),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("Orchestrator")

# State partagé entre workers — importé par dashboard
_state = {
    "running":       False,
    "started_at":    None,
    "total_created": 0,
    "total_failed":  0,
    "workers":       {},   # device_id → {status, current_email, created, failed}
    "last_account":  None,
    "errors":        [],   # last 20 errors
    "speed":         0.0,  # comptes/heure calculé glissant
    "log":           [],   # last 50 log lines
}
_state_lock = threading.Lock()
_stop_event = threading.Event()


def rj(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except: return default if default is not None else {}


def wj(p, data):
    tmp = str(p) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(tmp).replace(p)


def slog(msg: str, level="INFO"):
    """Add to state log + real log."""
    with _state_lock:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        _state["log"].append(f"[{ts}] {msg}")
        if len(_state["log"]) > 50:
            _state["log"] = _state["log"][-50:]
    if level == "ERROR":
        log.error(msg)
    else:
        log.info(msg)


# ── Détection des devices ADB ─────────────────────────────
def get_adb_devices() -> list:
    """Retourne la liste des devices Android connectés."""
    try:
        r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        devices = []
        for line in r.stdout.strip().splitlines()[1:]:
            line = line.strip()
            if line and "\tdevice" in line:
                device_id = line.split("\t")[0]
                devices.append(device_id)
        return devices
    except Exception:
        return []  # ADB non disponible sur ce serveur (normal sur VPS)


# ── Récupère email disponible ─────────────────────────────
def get_available_email():
    """Retourne le prochain email iCloud disponible (grab_phone peut déjà être pré-assigné)."""
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if (a.get("status", "available") == "available"
                and not a.get("grab_created")
                and not a.get("_locked")):
            return a["email"]
    return None


def lock_email(email: str):
    """Marque l'email comme 'en cours' pour éviter double-usage."""
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a["_locked"] = True
            a["_locked_at"] = datetime.datetime.now().isoformat()
            break
    wj(ACCOUNTS_F, accounts)


def unlock_email(email: str):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a.pop("_locked", None)
            a.pop("_locked_at", None)
            break
    wj(ACCOUNTS_F, accounts)


def mark_created(email: str, phone: str, ident: dict, password: str, bangkok_address: str = ""):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a["status"]           = "grab_ready"          # prêt à être utilisé
            a["grab_phone"]       = phone
            a["grab_created"]     = datetime.datetime.now().isoformat()
            a["grab_password"]    = password
            a["grab_name"]        = ident.get("full_name", "")
            a["grab_prenom"]      = ident.get("prenom", "")
            a["grab_nom"]         = ident.get("nom", "")
            a["grab_bangkok_addr"]= bangkok_address        # adresse résidentielle Bangkok
            a.pop("_locked", None)
            break
    wj(ACCOUNTS_F, accounts)


def mark_failed(email: str, reason: str):
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a["_locked"] = False
            a["_fail_count"] = a.get("_fail_count", 0) + 1
            a["_last_error"] = reason
            # Après 3 échecs, marque comme inutilisable
            if a["_fail_count"] >= 3:
                a["status"] = "failed"
            break
    wj(ACCOUNTS_F, accounts)


def clear_phone(email: str):
    """Efface le numéro pré-assigné pour forcer l'achat d'un nouveau numéro."""
    accounts = rj(ACCOUNTS_F, [])
    for a in accounts:
        if a["email"] == email:
            a.pop("grab_phone", None)
            a.pop("smspool_order_id", None)
            a["_fail_count"] = max(0, a.get("_fail_count", 1) - 1)  # ne pénalise pas
            break
    wj(ACCOUNTS_F, accounts)
    slog(f"Numéro effacé pour {email} — prochain cycle achètera un nouveau numéro")


# ── Worker par device ─────────────────────────────────────
async def worker(device_id: str):
    """Worker autonome qui crée des comptes en boucle sur un device."""
    from grab_gen.grab_app   import GrabApp, GrabAppError
    from sms_gen.smspool     import SMSPool,      SMSPoolError      as _PoolErr
    from sms_gen.fivesim     import FiveSim,      FiveSimError      as _5SimErr
    from sms_gen.smsactivate import SMSActivate,  SMSActivateError  as _SMSErr
    from sms_gen.herosms     import HeroSMS,       HeroSMSError     as _HeroErr
    _AllSMSErrors = (_PoolErr, _5SimErr, _SMSErr, _HeroErr)

    slog(f"[{device_id}] Worker demarre")

    with _state_lock:
        _state["workers"][device_id] = {
            "status": "starting", "created": 0, "failed": 0,
            "current_email": None, "current_phone": None,
        }

    # Priorité : SMSPool (PayPal FR ✅) → 5sim → SMS-Activate → Hero SMS
    pool_key    = os.environ.get("SMSPOOL_KEY", "")
    fivesim_key = os.environ.get("FIVESIM_KEY", "")
    sa_key      = os.environ.get("SMSACTIVATE_KEY", "")
    hero_key    = os.environ.get("HEROSMS_KEY", "")

    if pool_key:
        client_sms = SMSPool(pool_key)
        slog(f"[{device_id}] Provider SMS : SMSPool ✅ (PayPal)")
    elif fivesim_key:
        client_sms = FiveSim(fivesim_key)
        slog(f"[{device_id}] Provider SMS : 5sim.net")
    elif sa_key:
        client_sms = SMSActivate(sa_key)
        slog(f"[{device_id}] Provider SMS : SMS-Activate")
    elif hero_key:
        client_sms = HeroSMS(hero_key)
        slog(f"[{device_id}] Provider SMS : Hero SMS")
    else:
        client_sms = None
        slog(f"[{device_id}] ⚠ Aucune clé SMS — ajouter SMSPOOL_KEY dans .env", "ERROR")

    consecutive_errors = 0

    while not _stop_event.is_set():
        email = None
        phone = None

        try:
            # ── 1. Attendre un email disponible ──────────────
            with _state_lock:
                _state["workers"][device_id]["status"] = "waiting_email"

            email = None
            for _ in range(60):  # attend max 5 min
                if _stop_event.is_set(): return
                email = get_available_email()
                if email: break
                await asyncio.sleep(5)

            if not email:
                slog(f"[{device_id}] Pas d'email dispo — on attend...")
                await asyncio.sleep(30)
                continue

            lock_email(email)
            with _state_lock:
                _state["workers"][device_id]["current_email"] = email
                _state["workers"][device_id]["status"] = "buying_phone"

            slog(f"[{device_id}] Email : {email}")

            # ── 2. Numéro SMS : pré-acheté ou achat maintenant ───────────
            import re as _re
            # Vérifier si le pack a déjà un numéro pré-acheté
            accounts_current = rj(ACCOUNTS_F, [])
            pack_data = next((a for a in accounts_current if a.get("email") == email), {})
            prebuilt_phone    = pack_data.get("grab_phone", "")
            prebuilt_order_id = pack_data.get("smspool_order_id", "")

            if prebuilt_phone and prebuilt_order_id:
                # Utiliser le numéro pré-acheté
                phone    = prebuilt_phone
                order_id = prebuilt_order_id
                slog(f"[{device_id}] 📱 Numéro pré-assigné : {phone}")
            else:
                # Acheter un nouveau numéro
                if not client_sms:
                    slog(f"[{device_id}] ⚠ Pas de clé SMS — skip", "ERROR")
                    unlock_email(email)
                    await asyncio.sleep(60)
                    continue

                try:
                    order = await asyncio.get_event_loop().run_in_executor(
                        None, client_sms.buy_for_grab, "thailand"
                    )
                except _AllSMSErrors as e:
                    slog(f"[{device_id}] ❌ SMSPool achat : {e}", "ERROR")
                    unlock_email(email)
                    await asyncio.sleep(30)
                    continue

                phone    = order["phone"]
                order_id = order["id"]
                # Sauvegarder immédiatement dans accounts.json
                accs = rj(ACCOUNTS_F, [])
                for a in accs:
                    if a.get("email") == email:
                        a["grab_phone"]       = phone
                        a["smspool_order_id"] = order_id
                        break
                wj(ACCOUNTS_F, accs)
                slog(f"[{device_id}] 📱 Numéro acheté : {phone}")

            country_code = "+66"  # Thaïlande
            local_number = _re.sub(r"^\+?66", "", phone)

            with _state_lock:
                _state["workers"][device_id]["current_phone"] = phone
                _state["workers"][device_id]["status"] = "registering"

            slog(f"[{device_id}] Numero : {phone}")

            # ── 3. Générer identité française + adresse Bangkok ──
            from identity_gen import generate_identity as _gen_id, get_bangkok_address
            ident           = _gen_id(seed=email)
            bangkok_address = get_bangkok_address(seed=email)
            password        = "114722165uLCL"   # mot de passe fixe tous comptes

            slog(f"[{device_id}] Identite : {ident['full_name']}")
            slog(f"[{device_id}] Adresse  : {bangkok_address[:60]}…")

            # ── 4. Ouvrir Grab app + inscription ─────────────
            loop = asyncio.get_event_loop()

            def full_registration():
                with GrabApp(device_id) as app:
                    # Reset app data first — ensures clean state each attempt
                    app.reset_app()

                    # Navigate to signup
                    if not app.navigate_to_signup():
                        raise GrabAppError("Navigation signup echouee")

                    # Enter phone
                    if not app.enter_phone(local_number, country_code):
                        raise GrabAppError("Saisie telephone echouee")

                    # Wait for OTP — poll 150s, resend at 50s if needed
                    slog(f"[{device_id}] ⏳ Attente OTP…")
                    try:
                        otp_code = client_sms.wait_sms(order_id, timeout=50, poll=5)
                    except _AllSMSErrors:
                        # Pas reçu en 50s → demander renvoi et repoll 100s de plus
                        slog(f"[{device_id}] ⏳ OTP pas encore arrivé — resend…")
                        try: client_sms.resend(order_id)
                        except: pass
                        try:
                            otp_code = client_sms.wait_sms(order_id, timeout=100, poll=5)
                        except _AllSMSErrors as e:
                            # Toujours rien après 150s — efface le numéro pour forcer rachat
                            clear_phone(email)
                            raise GrabAppError(f"OTP échoué : {e}")

                    slog(f"[{device_id}] OTP : {otp_code}")

                    # Enter OTP
                    app.enter_otp(otp_code)

                    # Fill profile (nom/prénom français)
                    ok = app.fill_profile(
                        full_name=ident["full_name"],
                        email=email,
                        password=password,
                    )

                    # ── OTP email iCloud (si Grab envoie un code de vérification) ──
                    # Grab peut demander une vérification email après le profil
                    icloud_email_key = os.environ.get("ICLOUD_EMAIL", "")
                    icloud_app_pass  = os.environ.get("ICLOUD_APPPASS", "")
                    if icloud_email_key and icloud_app_pass:
                        try:
                            slog(f"[{device_id}] ⏳ Vérification OTP email…")
                            ui_check = app._dump_ui()
                            # Chercher champ de code email sur l'écran actuel
                            needs_email_otp = any(
                                k in ui_check for k in [
                                    "txt:Enter code", "txt:Verify email",
                                    "id:email_otp", "txt:verification code"
                                ]
                            )
                            if needs_email_otp:
                                from icloud_imap import wait_grab_email_otp, ICloudIMAPError
                                try:
                                    email_otp = wait_grab_email_otp(email, timeout=90)
                                    slog(f"[{device_id}] ✉ OTP email : {email_otp}")
                                    app.enter_otp(email_otp)
                                except ICloudIMAPError as ie:
                                    slog(f"[{device_id}] ⚠ OTP email manqué : {ie}", "ERROR")
                        except Exception as _ie:
                            slog(f"[{device_id}] iCloud IMAP skip : {_ie}")

                    # Finish SMS order (libère le numéro)
                    try: client_sms.finish(order_id)
                    except: pass

                    # Reset app pour prochain compte
                    app.reset_app()

                    return ok

            ok = await loop.run_in_executor(None, full_registration)

            # ── 5. Sauvegarder avec adresse Bangkok ──────────
            mark_created(email, phone, ident, password, bangkok_address)

            with _state_lock:
                _state["total_created"] += 1
                _state["workers"][device_id]["created"] += 1
                _state["workers"][device_id]["status"] = "idle"
                _state["workers"][device_id]["current_email"] = None
                _state["workers"][device_id]["current_phone"] = None
                _state["last_account"] = {
                    "email":   email,
                    "phone":   phone,
                    "name":    ident["full_name"],
                    "address": bangkok_address,
                    "at":      datetime.datetime.now().isoformat(),
                }

            slog(f"[{device_id}] Compte cree ! {ident['full_name']} / {email}")
            consecutive_errors = 0

            # Small pause between accounts
            await asyncio.sleep(random.uniform(10, 20))

        except Exception as e:
            consecutive_errors += 1
            err_msg = str(e)
            slog(f"[{device_id}] Erreur : {err_msg}", "ERROR")

            with _state_lock:
                _state["total_failed"] += 1
                _state["workers"][device_id]["failed"] += 1
                _state["workers"][device_id]["status"] = "error"
                _state["errors"].append({
                    "device": device_id, "error": err_msg,
                    "at": datetime.datetime.now().isoformat(),
                })
                if len(_state["errors"]) > 20:
                    _state["errors"] = _state["errors"][-20:]

            if email:
                mark_failed(email, err_msg)

            # Backoff exponentiel si erreurs répétées
            wait = min(60 * consecutive_errors, 300)
            slog(f"[{device_id}] Pause {wait}s avant retry...")
            await asyncio.sleep(wait)

    slog(f"[{device_id}] Worker arrete")
    with _state_lock:
        _state["workers"][device_id]["status"] = "stopped"


# ── Speed calculator ──────────────────────────────────────
async def speed_calculator():
    """Calcule les comptes/heure toutes les minutes."""
    history = []
    while not _stop_event.is_set():
        await asyncio.sleep(60)
        with _state_lock:
            now = time.time()
            total = _state["total_created"]
            history.append((now, total))
            # Fenêtre glissante 1 heure
            history = [(t, n) for t, n in history if now - t < 3600]
            if len(history) >= 2:
                dt = history[-1][0] - history[0][0]
                dn = history[-1][1] - history[0][1]
                _state["speed"] = round(dn / dt * 3600, 1) if dt > 0 else 0


# ── Entry point ───────────────────────────────────────────
async def run_orchestrator():
    """Lance l'orchestrateur sur tous les devices détectés."""
    global _stop_event
    _stop_event = threading.Event()

    with _state_lock:
        _state["running"]    = True
        _state["started_at"] = datetime.datetime.now().isoformat()

    slog("Orchestrateur demarre")

    # Détecte les devices
    devices = get_adb_devices()
    if not devices:
        slog("Aucun device ADB detecte — mode emulateur attendu")
        # On attend qu'un device se connecte
        for _ in range(12):  # 60 secondes
            await asyncio.sleep(5)
            devices = get_adb_devices()
            if devices: break

    if not devices:
        slog("Aucun device trouve apres 60s — abandon", "ERROR")
        with _state_lock:
            _state["running"] = False
        return

    slog(f"{len(devices)} device(s) detecte(s) : {devices}")

    # Lance 1 worker par device + speed calculator
    tasks = [asyncio.create_task(worker(d)) for d in devices]
    tasks.append(asyncio.create_task(speed_calculator()))

    await asyncio.gather(*tasks, return_exceptions=True)

    with _state_lock:
        _state["running"] = False
    slog("Orchestrateur arrete")


def start_background():
    """Lance l'orchestrateur dans un thread background (depuis dashboard)."""
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_orchestrator())
        loop.close()
    t = threading.Thread(target=_run, daemon=True, name="orchestrator")
    t.start()
    return t


def stop():
    """Arrête proprement l'orchestrateur."""
    _stop_event.set()


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


if __name__ == "__main__":
    asyncio.run(run_orchestrator())
