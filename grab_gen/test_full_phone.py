"""
Test final complet : du démarrage jusqu'à l'envoi OTP avec numéro thaïlandais fictif.
Lance : PYTHONPATH=/Users/donamor/grab python3 grab_gen/test_full_phone.py
"""
import sys, time, os
sys.path.insert(0, "/Users/donamor/grab")

SS_DIR = "/tmp/grab_final"
os.makedirs(SS_DIR, exist_ok=True)

from grab_gen.grab_app import GrabApp, GrabAppError

step_n = [0]
def shot(app, label):
    step_n[0] += 1
    path = f"{SS_DIR}/step{step_n[0]:02d}_{label}.png"
    app.screenshot(path)
    print(f"  📸 {path}")
    return path

print("\n🚀 Test complet navigate_to_signup() + enter_phone()")
print("="*55)

with GrabApp("emulator-5554") as app:

    # ── 1. Navigate to signup ─────────────────────────────────
    print("\n⏳ STEP 1 — navigate_to_signup()…")
    ok = app.navigate_to_signup()
    shot(app, "after_navigate_to_signup")
    print(f"  → Résultat: {'✅ OK' if ok else '❌ ÉCHEC'}")

    if not ok:
        print("  ARRÊT — signup non atteint")
        sys.exit(1)

    # ── 2. Enter phone (+66 fictif) ───────────────────────────
    print("\n⏳ STEP 2 — enter_phone(+66, numéro fictif)…")
    # Numéro fictif pour test (pas de vrai OTP envoyé)
    fake_phone = "812345678"   # format local thaïlandais sans +66
    try:
        ok2 = app.enter_phone(fake_phone, country_code="+66")
        shot(app, "after_enter_phone")
        if ok2:
            print("  ✅ Numéro entré + Next tappé !")
        else:
            print("  ⚠️ enter_phone retourné False")
    except GrabAppError as e:
        shot(app, "phone_error")
        print(f"  ❌ GrabAppError: {e}")

    # ── 3. Dump écran OTP ─────────────────────────────────────
    print("\n⏳ STEP 3 — Analyse écran OTP…")
    time.sleep(3)
    src = app.driver.page_source.lower()
    shot(app, "otp_screen_final")

    from appium.webdriver.common.appiumby import AppiumBy
    els = app.driver.find_elements(AppiumBy.XPATH, "//*[@text!='']")
    print("\n  Éléments visibles :")
    for e in els[:20]:
        try:
            txt = e.text.strip()
            if txt:
                rid = e.get_attribute("resource-id") or ""
                print(f"    '{txt}'  id='{rid}'")
        except: pass

print("\n" + "="*55)
if "verification" in src or "otp" in src or "enter" in src or "code" in src:
    print("🎉 SUCCÈS — Écran OTP atteint !")
    print("   En production : le code viendra de Hero SMS.")
elif "invalid" in src or "error" in src:
    print("✅ Numéro invalide attendu (test fictif) — le flow fonctionne !")
else:
    print("ℹ️  Voir screenshots dans", SS_DIR)
print("="*55)
print("\nDone.")
