"""
Dump l'écran courant de Grab pour analyse
Usage : PYTHONPATH=/Users/donamor/grab python3 grab_gen/dump_screen.py emulator-5554
"""
import sys, time
from pathlib import Path

device_id = sys.argv[1] if len(sys.argv) > 1 else "emulator-5554"
print(f"[Dump] Device : {device_id}")

from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

GRAB_PACKAGE  = "com.grabtaxi.passenger"
GRAB_ACTIVITY = "com.grab.pax.newface.common.alias.DefaultLauncherAlias"

opts = UiAutomator2Options()
opts.platform_name          = "Android"
opts.device_name            = device_id
opts.udid                   = device_id
opts.app_package            = GRAB_PACKAGE
opts.app_activity           = GRAB_ACTIVITY
opts.auto_grant_permissions = True
opts.no_reset               = True
opts.new_command_timeout    = 120

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Remote("http://localhost:4723", options=opts)
time.sleep(5)

def dump_screen(label):
    print(f"\n{'='*60}")
    print(f"=== {label} ===")
    print('='*60)
    texts = driver.find_elements(AppiumBy.XPATH, "//*[@text!='']")
    for t in texts[:40]:
        try:
            txt = t.text.strip()
            if txt:
                rid = t.get_attribute('resource-id') or 'null'
                print(f"  '{txt}' | id='{rid}'")
        except: pass
    driver.save_screenshot(f"/tmp/grab_{label.replace(' ','_').lower()}.png")
    print(f"Screenshot -> /tmp/grab_{label.replace(' ','_').lower()}.png")

def tap_text(text, timeout=8):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().textContains("{text}")'))
        )
        el.click()
        time.sleep(1.5)
        return True
    except: return False

# ── Ecran 1 : Initial
dump_screen("1_initial")

# ── Step 1 : Dismiss Android system permission dialog
for txt in ["While using the app", "Only this time", "Don't allow", "Allow", "OK"]:
    if tap_text(txt, timeout=5):
        print(f"\n  >> Tapped permission: '{txt}'")
        time.sleep(2)
        break

dump_screen("2_after_permission")

# ── Step 2 : Tap "Enter My Location" on Grab's location intro screen
if tap_text("Enter My Location", timeout=5):
    print("\n  >> Tapped 'Enter My Location'")
    time.sleep(2)
    # Dismiss any Android permission that follows
    for txt in ["While using the app", "Only this time", "Don't allow", "Allow"]:
        if tap_text(txt, timeout=4):
            print(f"\n  >> Tapped permission again: '{txt}'")
            time.sleep(2)
            break

dump_screen("3_after_enter_my_location")

# ── Step 3 : On "Your Location" screen → change country to Thailand then type Bangkok address
src = driver.page_source.lower()
if "nolo_search_input_text" in src or "enter current address" in src:
    print("\n  >> Ecran 'Your Location' detecte")

    # Change country from Singapore → Thailand
    if tap_text("Singapore", timeout=4) or tap_text("Searching in", timeout=4):
        print("  >> Tapped country selector")
        time.sleep(2)
        # Look for Thailand in country list
        if tap_text("Thailand", timeout=5):
            print("  >> Thailand selectionne")
            time.sleep(2)
        else:
            # Try search field in country list
            try:
                search = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.EditText")
                search.send_keys("Thailand")
                time.sleep(2)
                tap_text("Thailand", timeout=5)
                time.sleep(2)
            except Exception as e:
                print(f"  >> Erreur changement pays: {e}")

    dump_screen("3b_after_country_change")

    # Now enter Bangkok address
    print("\n  >> Saisie adresse Bangkok")
    try:
        field = driver.find_element(AppiumBy.ID, "com.grabtaxi.passenger:id/nolo_search_input_text")
        field.click()
        time.sleep(1)
        field.send_keys("Sukhumvit Bangkok")
        time.sleep(3)  # attendre suggestions
        # Tap first suggestion in list
        items = driver.find_elements(AppiumBy.XPATH,
            "//*[contains(@resource-id,'result') or contains(@resource-id,'suggestion') or contains(@resource-id,'item')]")
        if items:
            items[0].click()
            print(f"  >> Suggestion selectionnee: {items[0].text}")
        else:
            # Try RecyclerView first child
            rv = driver.find_elements(AppiumBy.CLASS_NAME, "androidx.recyclerview.widget.RecyclerView")
            if rv:
                children = rv[0].find_elements(AppiumBy.XPATH, ".//*[@clickable='true']")
                if children:
                    children[0].click()
                    print("  >> Premier element RecyclerView clique")
        time.sleep(3)
    except Exception as e:
        print(f"  >> Erreur saisie adresse: {e}")

dump_screen("4_after_location_set")

# ── Step 4 : Dump final
time.sleep(2)
dump_screen("5_final")

driver.quit()
print("\nDone.")
