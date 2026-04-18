"""
Grab Food — création de compte via Appium (émulateur Android)
IDs calibrés sur grab_bot AVD — Pixel 6 / Android 34
"""
import subprocess, sys, time, random, re
from pathlib import Path

from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE          = Path(__file__).parent.parent
GRAB_PACKAGE  = "com.grabtaxi.passenger"
GRAB_ACTIVITY = "com.grab.pax.newface.common.alias.DefaultLauncherAlias"
APPIUM_URL    = "http://localhost:4723"
ADB           = str(Path.home() / "Library/Android/sdk/platform-tools/adb")


class GrabAppError(Exception):
    pass


class GrabApp:
    def __init__(self, device_id: str, headless: bool = False):
        self.device_id = device_id
        self.driver    = None

    # ── Appium session ─────────────────────────────────────────────────────
    def start(self):
        opts = UiAutomator2Options()
        opts.platform_name          = "Android"
        opts.device_name            = self.device_id
        opts.udid                   = self.device_id
        opts.app_package            = GRAB_PACKAGE
        opts.app_activity           = GRAB_ACTIVITY
        opts.auto_grant_permissions  = True
        opts.no_reset               = True
        opts.auto_launch            = True
        opts.new_command_timeout    = 120
        self.driver = webdriver.Remote(APPIUM_URL, options=opts)
        self.wait   = WebDriverWait(self.driver, 20)
        try:
            self.driver.activate_app(GRAB_PACKAGE)
            time.sleep(2)
        except Exception:
            pass
        return self

    def stop(self):
        if self.driver:
            try: self.driver.quit()
            except: pass

    def __enter__(self): return self.start()
    def __exit__(self, *_): self.stop()

    # ── ADB helpers (plus fiables que Appium pour certaines actions) ────────
    def _adb(self, *args, timeout=10):
        return subprocess.run(
            [ADB, "-s", self.device_id, *args],
            capture_output=True, text=True, timeout=timeout
        )

    def _adb_tap(self, x: int, y: int):
        self._adb("shell", "input", "tap", str(x), str(y))

    def _adb_type(self, text: str):
        safe = text.replace(" ", "%s").replace("'", "\\'")
        self._adb("shell", "input", "text", safe)

    def _adb_key(self, keycode: int):
        self._adb("shell", "input", "keyevent", str(keycode))

    def _adb_screenshot(self, path: str):
        self._adb("exec-out", "screencap", "-p", timeout=10)
        subprocess.run(
            f'{ADB} -s {self.device_id} exec-out screencap -p > {path}',
            shell=True, timeout=10
        )

    def _dump_ui(self, remote="/sdcard/_ui.xml", local="/tmp/_grab_ui.xml") -> dict:
        """Dump UI XML via ADB → dict {id: bounds, text: bounds, ...}"""
        self._adb("shell", "uiautomator", "dump", remote)
        self._adb("pull", remote, local)
        import xml.etree.ElementTree as ET
        result = {}
        try:
            tree = ET.parse(local)
            for el in tree.iter():
                rid    = el.get("resource-id", "").split("/")[-1]
                txt    = el.get("text", "")
                bounds = el.get("bounds", "")
                desc   = el.get("content-desc", "")
                if rid:   result[f"id:{rid}"] = bounds
                if txt:   result[f"txt:{txt}"] = bounds
                if desc:  result[f"desc:{desc}"] = bounds
        except Exception:
            pass
        return result

    @staticmethod
    def _bounds_center(bounds_str: str):
        """Parse '[x1,y1][x2,y2]' → (cx, cy)"""
        m = re.findall(r"\d+", bounds_str or "")
        if len(m) == 4:
            x1, y1, x2, y2 = map(int, m)
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    def _tap_bounds(self, bounds_str: str) -> bool:
        c = self._bounds_center(bounds_str)
        if c:
            self._adb_tap(*c)
            return True
        return False

    def _h(self, min_s=0.5, max_s=1.2):
        time.sleep(random.uniform(min_s, max_s))

    def screenshot(self, path: str):
        try: self.driver.save_screenshot(path)
        except: pass

    # ── Appium element helpers ──────────────────────────────────────────────
    def _find(self, by, val, timeout=12):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, val))
        )

    def _click(self, by, val, timeout=10) -> bool:
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, val))
            )
            el.click()
            self._h(0.4, 0.9)
            return True
        except TimeoutException:
            return False

    def _click_text(self, text: str, timeout=8) -> bool:
        return self._click(
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().textContains("{text}")',
            timeout
        )

    def _click_id(self, rid: str, timeout=8) -> bool:
        return self._click(AppiumBy.ID, f"{GRAB_PACKAGE}:id/{rid}", timeout)

    def _type_id(self, rid: str, text: str, timeout=10):
        el = self._find(AppiumBy.ID, f"{GRAB_PACKAGE}:id/{rid}", timeout)
        el.click(); self._h(0.2, 0.4)
        el.clear(); self._h(0.1, 0.3)
        for ch in text:
            el.send_keys(ch)
            time.sleep(random.uniform(0.04, 0.10))

    # ── ÉTAPE 1 : Localisation Bangkok ─────────────────────────────────────
    def setup_bangkok_location(self, search_query: str = "Thong Lo Soi 10"):
        """
        Navigue le flow 'Your Location' :
        1. Cliquer 'Enter My Location'
        2. Changer pays : Singapore → Thailand
        3. Taper l'adresse de recherche
        4. Sélectionner le premier résultat non-parent
        5. Confirmer
        """
        # Attendre l'écran "Location access is important"
        self._h(3, 5)

        ui = self._dump_ui()
        if "txt:Enter My Location" in ui:
            self._tap_bounds(ui["txt:Enter My Location"])
            self._h(3, 5)
            print("[GrabApp] 'Enter My Location' tappé")
        else:
            print("[GrabApp] Écran location non détecté, on continue")
            return

        # ── Changer pays → Thailand ──────────────────────────────────────
        ui = self._dump_ui()
        # "Searching in Singapore" ou "Searching in Thailand"
        country_row = (
            ui.get("id:nolo_search_input_search_in_container")
            or ui.get("txt:Searching in")
        )
        if country_row:
            self._tap_bounds(country_row)
            self._h(2, 3)

            # Dans la liste pays, trouver Thailand
            ui2 = self._dump_ui()
            th_bounds = ui2.get("txt:Thailand")
            if th_bounds:
                self._tap_bounds(th_bounds)
                self._h(2, 3)
                print("[GrabApp] Thailand sélectionné")
            else:
                # Taper Thailand dans le champ recherche pays
                self._adb_type("Thailand")
                self._h(2, 3)
                ui3 = self._dump_ui()
                if ui3.get("txt:Thailand"):
                    self._tap_bounds(ui3["txt:Thailand"])
                    self._h(1, 2)
                    print("[GrabApp] Thailand sélectionné via recherche")

        # ── Taper l'adresse Bangkok ──────────────────────────────────────
        ui = self._dump_ui()
        field_bounds = ui.get("id:nolo_search_input_text")
        if field_bounds:
            self._tap_bounds(field_bounds)
            self._h(0.5, 1)
        else:
            self._adb_tap(540, 481)  # fallback position connue
            self._h(0.5, 1)

        # Effacer et taper
        self._adb_key(123)  # KEYCODE_MOVE_END
        self._adb("shell", "input", "keyevent", "--longpress", "67")  # clear
        self._adb_type(search_query)
        self._h(3, 5)
        print(f"[GrabApp] Adresse tapée : {search_query}")

        # ── Sélectionner résultat non-parent ─────────────────────────────
        ui = self._dump_ui()
        skip_keywords = [
            "choose a point", "pick-up", "drop-off", "dispensary", "phuket",
            "airport", "hospital", "hotel", "mall", "plaza", "bank", "atm",
        ]
        picked = False
        import xml.etree.ElementTree as ET
        try:
            tree = ET.parse("/tmp/_grab_ui.xml")
            items = []
            for el in tree.iter():
                rid = el.get("resource-id", "")
                txt = el.get("text", "")
                bounds = el.get("bounds", "")
                if "nolo_item_title" in rid and txt and bounds:
                    items.append((txt, bounds))
                elif txt and bounds and any(
                    k in txt.lower() for k in [search_query.lower()[:6]]
                ):
                    items.append((txt, bounds))

            for txt, bounds in items:
                if any(k in txt.lower() for k in skip_keywords):
                    continue
                if search_query.lower()[:4] in txt.lower():
                    self._tap_bounds(bounds)
                    picked = True
                    print(f"[GrabApp] Résultat sélectionné : '{txt[:50]}'")
                    break

            if not picked and items:
                # Premier résultat non-vide
                self._tap_bounds(items[0][1])
                picked = True
                print(f"[GrabApp] Fallback → '{items[0][0][:50]}'")
        except Exception as e:
            print(f"[GrabApp] Erreur sélection résultat : {e}")

        self._h(2, 3)

        # ── Confirm ───────────────────────────────────────────────────────
        ui = self._dump_ui()
        confirm = (
            ui.get("txt:Confirm")
            or ui.get("id:btn_nolo_enter_location_manual")
        )
        if confirm:
            self._tap_bounds(confirm)
            self._h(4, 6)
            print("[GrabApp] Location confirmée ✅")
        else:
            # Fallback : tap bas de l'écran
            self._adb_tap(540, 2232)
            self._h(4, 6)
            print("[GrabApp] Location confirmée via fallback")

    # ── ÉTAPE 2 : Machine à états → Get Started ────────────────────────────
    def navigate_to_signup(self, search_query: str = "Terminal 21 Asoke") -> bool:
        """
        Machine à états robuste.
        Avance écran par écran jusqu'à l'écran 'Get Started' (saisie numéro).
        """
        for step in range(35):   # max 35 états
            self._h(1.5, 3) if step < 5 else self._h(2, 4)
            ui = self._dump_ui()
            print(f"[GrabApp] état {step} — clés : {[k for k in ui if not k.startswith('id:') or 'nav' not in k][:6]}")

            # ── Permission système Android ────────────────────────────────
            if "txt:While using the app" in ui:
                self._tap_bounds(ui["txt:While using the app"])
                print("[GrabApp] Permission localisation accordée")
                continue

            if "txt:Allow" in ui and "txt:Don't allow" in ui:
                self._tap_bounds(ui["txt:Allow"])
                print("[GrabApp] Permission Allow tappée")
                continue

            # ── "Too many times" dialog (OTP rate-limit) ─────────────────
            if ("txt:You've tried too many times" in ui
                    or "txt:tried too many" in ui.get("txt:You've tried too many times", "")):
                btn_ok = ui.get("txt:OK") or ui.get("id:button_positive")
                if btn_ok:
                    self._tap_bounds(btn_ok)
                    print("[GrabApp] 'Too many times' dialog → OK")
                    self._h(1, 2)
                else:
                    self._adb_key(4)
                continue

            # ── OTP screen stuck (previous session) ──────────────────────
            if ("txt:Enter the 6-digit code" in ui or "id:btn_back_verify_number" in ui
                    and "txt:Get Started" not in ui):
                # Stuck on OTP screen — go back to phone entry
                self._adb_key(4)
                print("[GrabApp] Écran OTP résiduel → BACK")
                self._h(1, 2)
                continue

            # ── "Select Country / Region" dialog (country picker) ────────
            if "id:country_search" in ui or "txt:Select Country / Region" in ui:
                # Thailand already shown — tap the first "Thailand" item
                try:
                    items = self.driver.find_elements(
                        AppiumBy.ID, f"{GRAB_PACKAGE}:id/country"
                    )
                    tapped = False
                    for item in items:
                        if "Thailand" in (item.text or ""):
                            item.click()
                            tapped = True
                            print("[GrabApp] Thailand sélectionné dans country picker ✅")
                            self._h(0.5, 1)
                            break
                    if not tapped:
                        # Close with back key
                        self._adb_key(4)
                        print("[GrabApp] Country picker → BACK (Thailand non trouvé)")
                except Exception as _ce:
                    print(f"[GrabApp] Country picker error: {_ce}")
                    self._adb_key(4)
                continue

            # ── "Location access is important" ───────────────────────────
            if "txt:Enter My Location" in ui:
                self._tap_bounds(ui["txt:Enter My Location"])
                print("[GrabApp] Enter My Location tappé")
                continue

            # ── Écran location / recherche Bangkok ───────────────────────
            # nolo_search_input_text = barre de recherche (onboarding OU home search)
            if "id:nolo_search_input_text" in ui or "txt:Your Location" in ui:
                if "txt:Confirm" in ui:
                    # Écran de sélection initiale → chercher et confirmer
                    print("[GrabApp] Écran location → setup Bangkok")
                    done = self._do_bangkok_location(ui, search_query)
                    if done:
                        print("[GrabApp] Location + Confirm ✅")
                else:
                    # Barre de recherche sans Confirm = home screen search overlay
                    # Presser BACK pour revenir à l'accueil
                    print("[GrabApp] Overlay search sans Confirm → BACK")
                    self._adb_key(4)   # BACK
                    self._h(1.5, 2.5)
                continue

            # ── Confirm sur un écran sans barre de recherche (cas rare) ──
            if "txt:Confirm" in ui and "id:nolo_search_input_text" not in ui:
                self._tap_bounds(ui["txt:Confirm"])
                self._h(4, 6)
                print("[GrabApp] Confirm (post-location) ✅")
                continue

            # ── Bottom sheet "Sign in another way" ───────────────────────
            if "desc:Dismiss" in ui:
                self._tap_bounds(ui["desc:Dismiss"])
                print("[GrabApp] Bottom sheet fermée")
                continue

            # ── Home screen → Sign Up ─────────────────────────────────────
            if "txt:Sign Up" in ui or "txt:Sign up" in ui:
                bounds = ui.get("txt:Sign Up") or ui.get("txt:Sign up")
                self._tap_bounds(bounds)
                print("[GrabApp] Sign Up tappé ✅")
                self._h(2, 3)
                continue

            # ── Popup Google "Choose a phone number" ─────────────────────
            if "txt:Choose a phone number" in ui:
                cancel = ui.get("id:cancel") or ui.get("desc:Cancel") or ui.get("desc:Dismiss")
                if cancel:
                    self._tap_bounds(cancel)
                    print("[GrabApp] Popup Google fermé")
                continue

            # ── Get Started (écran saisie numéro) → SUCCÈS ───────────────
            if ("txt:Get Started" in ui or "id:get_started_header" in ui
                    or "id:verify_number_edit_number" in ui):
                print("[GrabApp] Écran 'Get Started' atteint ✅")
                return True

            print(f"[GrabApp] État inconnu — on attend…")
            self._h(3, 5)

        self.screenshot("/tmp/grab_signup_fail.png")
        return False

    def _do_bangkok_location(self, ui: dict, search_query: str) -> bool:
        """
        Sous-routine complète : change pays → Thailand, tape adresse,
        sélectionne le résultat, puis tape Confirm.
        Retourne True si Confirm a été tapé avec succès.
        """
        import xml.etree.ElementTree as ET
        from appium.webdriver.common.appiumby import AppiumBy

        # ── 1. Changer pays si pas Thailand ──────────────────────────────
        if "txt:Singapore" in ui or (
            "txt:Searching in" in ui and "txt:Thailand" not in ui
        ):
            country_row = (
                ui.get("id:nolo_search_input_search_in_container")
                or ui.get("txt:Singapore")
            )
            if country_row:
                self._tap_bounds(country_row)
                self._h(2, 3)
                ui2 = self._dump_ui()
                if "txt:Thailand" in ui2:
                    self._tap_bounds(ui2["txt:Thailand"])
                    self._h(1.5, 2.5)
                    print("[GrabApp] Thailand sélectionné")
            return False  # laisser l'état recharger

        # ── 2. Taper adresse dans le champ ───────────────────────────────
        field = ui.get("id:nolo_search_input_text")
        if field:
            self._tap_bounds(field)
            self._h(0.3, 0.6)

        self._adb_key(123)          # MOVE_END
        for _ in range(25):
            self._adb_key(67)       # BACKSPACE
        self._adb_type(search_query)
        self._h(3, 5)               # attendre suggestions
        print(f"[GrabApp] Adresse tapée : {search_query}")

        # ── 3. Sélectionner 1er résultat dans la liste ───────────────────
        skip_kw = ["hotel", "resort", "mall", "carlton", "sofitel", "ibis",
                   "marriott", "hilton", "hyatt", "airport", "dispensary",
                   "atm", "bank", "choose a point", "phuket"]
        tapped = False

        # Essai 1 : via nolo_item_title (resource-id officiel)
        try:
            items = self.driver.find_elements(
                AppiumBy.ID, f"{GRAB_PACKAGE}:id/nolo_item_title")
            for el in items:
                try:
                    txt = (el.text or "").strip()
                    if not txt: continue
                    if any(k in txt.lower() for k in skip_kw): continue
                    el.click()
                    tapped = True
                    print(f"[GrabApp] Résultat tappé (nolo_item_title) : '{txt[:50]}'")
                    break
                except: continue
        except: pass

        # Essai 2 : parser le XML directement
        if not tapped:
            try:
                tree = ET.parse("/tmp/_grab_ui.xml")
                for el in tree.iter():
                    txt  = el.get("text", "")
                    bounds = el.get("bounds", "")
                    if not txt or not bounds: continue
                    if any(k in txt.lower() for k in skip_kw): continue
                    if search_query.lower()[:5] in txt.lower():
                        self._tap_bounds(bounds)
                        tapped = True
                        print(f"[GrabApp] Résultat tappé (XML) : '{txt[:50]}'")
                        break
            except Exception as e:
                print(f"[GrabApp] XML parse: {e}")

        if not tapped:
            print("[GrabApp] ⚠ Aucun résultat trouvé — on laisse Grab suggérer")
            return False

        # ── 4. Attendre que Confirm soit ENABLED puis le tapper ──────────
        self._h(2, 4)
        for attempt in range(8):
            try:
                confirm_el = self.driver.find_element(
                    AppiumBy.XPATH, "//*[@text='Confirm']")
                enabled = confirm_el.get_attribute("enabled")
                if enabled == "true":
                    confirm_el.click()
                    self._h(4, 7)
                    print(f"[GrabApp] Confirm tappé (enabled) ✅")
                    return True
                else:
                    print(f"[GrabApp] Confirm grisé (tentative {attempt+1}/8)…")
                    self._h(1.5, 2)
            except Exception as e:
                print(f"[GrabApp] Confirm non trouvé: {e}")
                self._h(1, 2)

        print("[GrabApp] ⚠ Confirm jamais activé — on retente la sélection")
        return False

    # ── ÉTAPE 3 : Entrer numéro thaïlandais ────────────────────────────────
    def enter_phone(self, phone: str, country_code: str = "+66") -> bool:
        """
        Écran 'Get Started' :
        - change indicatif → +66 (Thaïlande)
        - saisit le numéro
        - clique Next
        """
        self._h(1, 2)

        # ── Vérifier qu'on est sur 'Get Started' ─────────────────────────
        ui = self._dump_ui()
        if "txt:Get Started" not in ui and "id:get_started_header" not in ui:
            print("[GrabApp] ⚠ Pas sur l'écran Get Started")

        # ── Changer indicatif pays si pas +66 ────────────────────────────
        code_bounds = ui.get("id:verify_number_code_country")
        current_code = ""
        if code_bounds:
            # Lire le texte via Appium
            try:
                el = self.driver.find_element(AppiumBy.ID, f"{GRAB_PACKAGE}:id/verify_number_code_country")
                current_code = (el.text or "").strip()
            except: pass

        if "+66" not in current_code:
            # Tapper le sélecteur de pays
            sel_bounds = ui.get("id:verify_number_btn_select_country") or code_bounds
            if sel_bounds:
                self._tap_bounds(sel_bounds)
            else:
                self._click_id("verify_number_btn_select_country")
            self._h(1.5, 2.5)
            print("[GrabApp] Sélecteur pays ouvert")

            # Dans la liste : chercher Thailand
            ui2 = self._dump_ui()
            th = ui2.get("txt:Thailand")
            if th:
                self._tap_bounds(th)
                self._h(1, 2)
                print("[GrabApp] +66 (Thailand) sélectionné ✅")
            else:
                # Taper "Thailand" dans le champ recherche du modal
                self._adb_type("Thailand")
                self._h(2, 3)
                ui3 = self._dump_ui()
                th3 = ui3.get("txt:Thailand")
                if th3:
                    self._tap_bounds(th3)
                    self._h(1, 2)
                    print("[GrabApp] +66 sélectionné via recherche")
                else:
                    print("[GrabApp] ⚠ Thailand non trouvé — on continue")
        else:
            print(f"[GrabApp] Indicatif déjà {current_code}")

        # ── Saisir le numéro ──────────────────────────────────────────────
        self._h(0.5, 1)
        ui = self._dump_ui()
        field_bounds = ui.get("id:verify_number_edit_number")
        if field_bounds:
            self._tap_bounds(field_bounds)
            self._h(0.3, 0.6)
        else:
            self._click_id("verify_number_edit_number", timeout=5)

        # Vider et taper
        self._adb_key(123)   # MOVE_END
        for _ in range(15):
            self._adb_key(67)  # BACKSPACE x15
        self._adb_type(phone)
        print(f"[GrabApp] Numéro saisi : {country_code}{phone}")
        self._h(0.8, 1.5)

        # ── Tapper Next ───────────────────────────────────────────────────
        ui = self._dump_ui()
        next_bounds = ui.get("id:btn_next_verify_number") or ui.get("txt:Next")
        if next_bounds:
            self._tap_bounds(next_bounds)
            self._h(3, 5)
            print("[GrabApp] Next tappé → OTP demandé ✅")
            self.screenshot("/tmp/grab_otp_screen.png")
            return True
        else:
            # Fallback Appium
            if self._click_id("btn_next_verify_number", timeout=6):
                self._h(3, 5)
                print("[GrabApp] Next via Appium ✅")
                return True
            self.screenshot("/tmp/grab_next_fail.png")
            raise GrabAppError("Bouton Next introuvable")

    # ── ÉTAPE 4 : Saisir OTP ───────────────────────────────────────────────
    def enter_otp(self, code: str) -> bool:
        self._h(1, 2)
        # Cherche des champs OTP individuels ou un seul champ
        try:
            fields = self.driver.find_elements(
                AppiumBy.ANDROID_UIAUTOMATOR,
                'new UiSelector().className("android.widget.EditText")'
            )
            if len(fields) >= len(code):
                for i, digit in enumerate(code[:len(fields)]):
                    fields[i].click()
                    time.sleep(random.uniform(0.1, 0.25))
                    fields[i].send_keys(digit)
            elif len(fields) == 1:
                fields[0].click(); self._h(0.2, 0.4)
                fields[0].clear()
                fields[0].send_keys(code)
            else:
                self._adb_type(code)
        except Exception:
            self._adb_type(code)

        print(f"[GrabApp] OTP saisi : {code}")
        self._h(3, 5)
        self.screenshot("/tmp/grab_after_otp.png")
        return True

    # ── ÉTAPE 5 : Remplir profil ───────────────────────────────────────────
    def fill_profile(self, full_name: str, email: str, password: str) -> bool:
        self._h(1, 2)
        ui = self._dump_ui()

        # Chercher les champs par IDs connus ou ordre des EditText
        fields_data = [
            (["full_name", "name", "display_name", "user_name"], full_name),
            (["email", "email_address", "email_input"],           email),
            (["password", "passwd", "pwd"],                       password),
        ]

        for keywords, value in fields_data:
            filled = False
            for kw in keywords:
                try:
                    self._type_id(kw, value, timeout=4)
                    filled = True
                    self._h(0.3, 0.6)
                    break
                except: continue

            if not filled:
                # Fallback : premier EditText vide
                try:
                    fields = self.driver.find_elements(
                        AppiumBy.CLASS_NAME, "android.widget.EditText"
                    )
                    for f in fields:
                        if not (f.text or "").strip():
                            f.click(); self._h(0.2, 0.4)
                            f.send_keys(value)
                            filled = True
                            break
                except: pass

        self._h(0.8, 1.5)

        # Submit
        for text in ["Create account", "Register", "Sign up", "Done", "Finish", "Continue", "Next"]:
            if self._click_text(text, timeout=5):
                self._h(5, 8)
                self.screenshot("/tmp/grab_profile_done.png")
                src = ""
                try: src = self.driver.page_source.lower()
                except: pass
                return any(k in src for k in ["home", "restaurant", "food", "order", "welcome", "done"])

        return False

    # ── Reset app ──────────────────────────────────────────────────────────
    def reset_app(self):
        try:
            self._adb("shell", "pm", "clear", GRAB_PACKAGE)
            print("[GrabApp] App data cleared via ADB ✅")
        except Exception as e:
            print(f"[GrabApp] reset_app warning: {e}")
        self._h(2, 3)
