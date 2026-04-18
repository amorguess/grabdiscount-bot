"""
Test du flow d'inscription Grab étape par étape avec screenshots.
Lance : PYTHONPATH=/Users/donamor/grab python3 grab_gen/test_signup_flow.py
"""
import sys, time, os
sys.path.insert(0, "/Users/donamor/grab")

from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

GRAB_PACKAGE  = "com.grabtaxi.passenger"
GRAB_ACTIVITY = "com.grab.pax.newface.common.alias.DefaultLauncherAlias"
DEVICE        = "emulator-5554"
SS_DIR        = "/tmp/grab_test"
os.makedirs(SS_DIR, exist_ok=True)

step_n = [0]
def shot(label):
    step_n[0] += 1
    path = f"{SS_DIR}/step{step_n[0]:02d}_{label}.png"
    try: driver.save_screenshot(path)
    except: pass
    print(f"  📸 {path}")
    return path

def dump(label=""):
    print(f"\n{'─'*55}")
    if label: print(f"  [{label}]")
    try:
        els = driver.find_elements(AppiumBy.XPATH, "//*[@text!='']")
        for e in els[:30]:
            txt = e.text.strip()
            if txt:
                rid = e.get_attribute("resource-id") or ""
                print(f"  '{txt}'  id='{rid}'")
    except: pass

def tap_text(text, timeout=10):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().textContains("{text}")'))
        )
        el.click()
        time.sleep(1.5)
        print(f"  ✅ Tapped: '{text}'")
        return True
    except: return False

def tap_id(rid, timeout=8):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((AppiumBy.ID, rid))
        )
        el.click()
        time.sleep(1.5)
        print(f"  ✅ Tapped ID: '{rid}'")
        return True
    except: return False

# ── Connexion Appium ──────────────────────────────────────────
print("\n🚀 Connexion à l'émulateur…")
opts = UiAutomator2Options()
opts.platform_name          = "Android"
opts.device_name            = DEVICE
opts.udid                   = DEVICE
opts.app_package            = GRAB_PACKAGE
opts.app_activity           = GRAB_ACTIVITY
opts.auto_grant_permissions = True
opts.no_reset               = True
opts.new_command_timeout    = 300

driver = webdriver.Remote("http://localhost:4723", options=opts)
wait   = WebDriverWait(driver, 20)
print("  ✅ Connecté !")

# ── STEP 1 : Démarrage ────────────────────────────────────────
print("\n⏳ STEP 1 — Attente splash screen…")
time.sleep(6)
dump("1_splash")
shot("splash")

# ── STEP 2 : Permission Android système ──────────────────────
print("\n⏳ STEP 2 — Gestion permissions Android…")
for txt in ["While using the app", "Only this time", "Allow", "OK"]:
    if tap_text(txt, timeout=5):
        print(f"  → Permission système dismissée : '{txt}'")
        time.sleep(2)
        break
dump("2_after_perm")
shot("after_permission")

# ── STEP 3 : Écran "Location access is important" Grab ───────
print("\n⏳ STEP 3 — Écran location Grab…")
src = driver.page_source.lower()
if "enter my location" in src:
    tap_text("Enter My Location", timeout=6)
    time.sleep(2)
    # Deuxième permission système qui peut suivre
    for txt in ["While using the app", "Only this time", "Allow"]:
        if tap_text(txt, timeout=4):
            time.sleep(2)
            break
dump("3_after_enter_location")
shot("after_enter_location")

# ── STEP 4 : Écran "Your Location" → Bangkok ─────────────────
print("\n⏳ STEP 4 — Configuration adresse Bangkok…")
src = driver.page_source.lower()
is_location_screen = any(k in src for k in [
    "enter current address", "your location", "nolo_search", "searching in", "first, tell us"
])

if is_location_screen:
    print("  → Écran 'Your Location' détecté")

    # Changer pays Singapore → Thailand
    changed = False
    for txt in ["Singapore", "Searching in"]:
        try:
            el = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().textContains("{txt}")')
            el.click()
            time.sleep(2)
            print(f"  → Country selector cliqué: '{txt}'")
            changed = True
            break
        except: continue

    if changed:
        dump("4a_country_list")
        shot("country_list")
        if tap_text("Thailand", timeout=6):
            time.sleep(2)
        else:
            # Chercher dans la liste avec EditText
            try:
                fields = driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.EditText")
                if fields:
                    fields[0].clear()
                    fields[0].send_keys("Thailand")
                    time.sleep(2)
                    tap_text("Thailand", timeout=5)
                    time.sleep(2)
            except Exception as e:
                print(f"  ⚠️ Erreur recherche pays: {e}")
        dump("4b_after_thailand")
        shot("after_thailand")

    # Saisir adresse Bangkok
    print("  → Saisie adresse Bangkok…")
    try:
        field = driver.find_element(AppiumBy.ID,
            f"{GRAB_PACKAGE}:id/nolo_search_input_text")
        field.click()
        time.sleep(1)
        field.clear()
        field.send_keys("Sukhumvit Bangkok")
        time.sleep(4)  # attendre suggestions

        dump("4c_suggestions")
        shot("suggestions_visible")

        # Cacher le clavier avant de tapper une suggestion
        try:
            driver.hide_keyboard()
            time.sleep(1)
        except: pass

        # ── Stratégie : tapper un sous-point spécifique (active le bouton Confirm) ──
        # Les items parents (hotels) ont "Choose a point below" comme description
        # → il faut tapper un sub-item (Lobby Entrance, Exit, Bus Stop, Soi...)
        # qui active directement le bouton Confirm en bleu.
        tapped = False

        # Chercher tous les nolo_item_title
        items = driver.find_elements(AppiumBy.ID, f"{GRAB_PACKAGE}:id/nolo_item_title")
        print(f"  → {len(items)} nolo_item_title trouvés")

        # Mots-clés de PARENT venues à éviter (hotels, malls, etc.)
        parent_keywords = [
            "hotel", "resort", "mall", "plaza", "centre", "center",
            "suites", "inn", "hostel", "intercontinental", "marriott",
            "carlton", "sofitel", "ibis", "hilton", "novotel", "sheraton",
            "hyatt", "westin", "le méridien", "mandarin", "four seasons",
        ]
        for el in items:
            try:
                txt = (el.text or "").strip()
                txt_l = txt.lower()
                if not txt: continue
                # Skip les noms de venues (contiennent des mots d'hôtels)
                if any(k in txt_l for k in parent_keywords): continue
                # Skip "Choose a point below..."
                if "choose" in txt_l or "point" in txt_l: continue
                # Skip champ de saisie lui-même
                if "sukhumvit bangkok" in txt_l: continue
                # Ce qui reste = sous-points spécifiques (Lobby, Exit, Bus Stop, Soi...)
                el.click()
                tapped = True
                print(f"  ✅ Sub-point sélectionné: '{txt[:50]}'")
                time.sleep(2)
                break
            except: continue

        if not tapped:
            print("  ⚠️ Pas de sous-point trouvé, essai item[1] (2ème suggestion)…")
            if len(items) > 1:
                items[1].click()
                tapped = True
                print(f"  ✅ Fallback items[1]: '{items[1].text[:50]}'")
                time.sleep(2)

        if not tapped:
            print("  ❌ Aucune suggestion sélectionnable !")

        # ── Confirmer la sélection ─────────────────────────────────────────
        if tapped:
            time.sleep(2)
            confirmed = False
            # Essai 1 : XPath direct (fonctionne même si id='null')
            for xpath in ["//*[@text='Confirm']", "//*[@text='CONFIRM']",
                          "//*[contains(@text,'Confirm')]"]:
                try:
                    btn = driver.find_element(AppiumBy.XPATH, xpath)
                    btn.click()
                    confirmed = True
                    print(f"  ✅ 'Confirm' tappé via XPath ({xpath})")
                    time.sleep(4)
                    break
                except: continue
            # Essai 2 : textContains UiAutomator
            if not confirmed:
                confirmed = tap_text("Confirm", timeout=5)
                if confirmed:
                    print("  ✅ 'Confirm' tappé via tap_text")
                    time.sleep(4)
            if not confirmed:
                print("  ⚠️ 'Confirm' non trouvé")

    except Exception as e:
        print(f"  ⚠️ Erreur adresse: {e}")

dump("4d_after_bangkok")
shot("after_bangkok_setup")
time.sleep(3)

# ── STEP 5 : Écran d'accueil — tapper "Sign Up" ──────────────
print("\n⏳ STEP 5 — Tap Sign Up…")
time.sleep(3)
dump("5_home_screen")
shot("home_screen")

# Fermer le toast "Sign in another way" si présent
try:
    btn = driver.find_element(AppiumBy.XPATH,
        "//*[@content-desc='Close' or @content-desc='Dismiss' or @text='✕']")
    btn.click()
    time.sleep(1)
except: pass

signup_found = False
# Tenter directement Sign Up (visible sur l'écran d'accueil Bangkok)
for text in ["Sign Up", "Sign up", "SIGN UP"]:
    if tap_text(text, timeout=8):
        print(f"  ✅ 'Sign Up' tappé!")
        signup_found = True
        time.sleep(4)
        break

dump("5b_after_signup_tap")
shot("after_signup_tap")

# ── STEP 6 : Fermer popup Google + voir champ téléphone ──────────
print("\n⏳ STEP 6 — Fermeture popup Google 'Choose a phone number'…")
time.sleep(2)

# Le popup Google affiche un ✕ en haut à droite (resource-id: cancel ou close)
google_closed = False
for sel in [
    (AppiumBy.ID,                "com.google.android.gms:id/cancel"),
    (AppiumBy.XPATH,             "//*[@resource-id='com.google.android.gms:id/cancel']"),
    (AppiumBy.ANDROID_UIAUTOMATOR,'new UiSelector().resourceId("com.google.android.gms:id/cancel")'),
]:
    try:
        btn = driver.find_element(sel[0], sel[1])
        btn.click()
        google_closed = True
        print("  ✅ Popup Google fermé")
        time.sleep(2)
        break
    except: continue

dump("6_after_google_dismiss")
shot("after_google_dismiss")

# ── STEP 7 : Champ téléphone Grab — changer +1 → +66 ────────────
print("\n⏳ STEP 7 — Écran saisie téléphone Grab…")
time.sleep(2)
dump("7_phone_field")
shot("phone_field")

# ── STEP 8 : Résumé final ─────────────────────────────────────
print("\n" + "="*55)
src_final = driver.page_source.lower()

if any(k in src_final for k in ["phone number", "mobile number", "enter your phone",
                                  "phone_number", "enter phone", "+66", "thailand"]):
    print("🎉 SUCCÈS TOTAL — Écran saisie téléphone atteint !")
    print("   Le bot peut entrer un numéro thaïlandais (+66) ici.")
    print("   → Prêt pour l'intégration Hero SMS !")
elif any(k in src_final for k in ["sign up", "register", "create account", "sign_up"]):
    print("✅ Écran inscription atteint")
elif any(k in src_final for k in ["here for the first time", "food", "transport"]):
    print("✅ Accueil Bangkok atteint — 'Sign Up' non cliqué")
else:
    print("⚠️  Écran inconnu — voir dernier screenshot")

print(f"\n📁 Screenshots dans: {SS_DIR}/")
print("="*55)

driver.quit()
print("\nDone.")
