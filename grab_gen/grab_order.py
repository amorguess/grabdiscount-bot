"""
GrabOrder — Ouvre Grab avec un compte existant et entre l'adresse de livraison client.
L'admin finalise le panier + paiement depuis le dashboard.
"""
import time, random, subprocess
from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

GRAB_PACKAGE  = "com.grabtaxi.passenger"
GRAB_ACTIVITY = "com.grab.pax.newface.common.alias.DefaultLauncherAlias"
APPIUM_URL    = "http://localhost:4723"


class GrabOrderError(Exception):
    pass


class GrabOrder:
    """
    Ouvre Grab avec le compte assigné à la commande et entre l'adresse de livraison.
    L'admin complète ensuite le panier depuis l'émulateur visible dans le dashboard.
    """

    def __init__(self, device_id: str = "emulator-5554"):
        self.device_id = device_id
        self.driver    = None

    def start(self):
        opts = UiAutomator2Options()
        opts.platform_name          = "Android"
        opts.device_name            = self.device_id
        opts.udid                   = self.device_id
        opts.app_package            = GRAB_PACKAGE
        opts.app_activity           = GRAB_ACTIVITY
        opts.auto_grant_permissions = True
        opts.no_reset               = True    # compte déjà connecté
        opts.new_command_timeout    = 600     # 10 min (admin prend le temps)
        self.driver = webdriver.Remote(APPIUM_URL, options=opts)
        self.wait   = WebDriverWait(self.driver, 20)
        return self

    def stop(self):
        if self.driver:
            try: self.driver.quit()
            except: pass

    def __enter__(self): return self.start()
    def __exit__(self, *_): self.stop()

    def _human_delay(self, mn=0.5, mx=1.5):
        time.sleep(random.uniform(mn, mx))

    def _tap_text(self, text: str, timeout=10) -> bool:
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().textContains("{text}")'))
            )
            el.click()
            self._human_delay()
            return True
        except TimeoutException:
            return False

    def _tap_id(self, rid: str, timeout=8) -> bool:
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((AppiumBy.ID, rid))
            )
            el.click()
            self._human_delay()
            return True
        except TimeoutException:
            return False

    def screenshot(self, path: str):
        try: self.driver.save_screenshot(path)
        except: pass

    def navigate_to_food(self) -> bool:
        """Depuis l'accueil Grab, va sur la section Food/Livraison."""
        self._human_delay(2, 4)
        for text in ["Food", "GrabFood", "Order Food", "Delivery", "Food Delivery"]:
            if self._tap_text(text, timeout=5):
                print(f"[GrabOrder] Food delivery via '{text}'")
                self._human_delay(2, 3)
                return True
        for rid in [
            f"{GRAB_PACKAGE}:id/food",
            f"{GRAB_PACKAGE}:id/grab_food",
            f"{GRAB_PACKAGE}:id/food_delivery",
            f"{GRAB_PACKAGE}:id/iv_food",
            f"{GRAB_PACKAGE}:id/service_food",
            f"{GRAB_PACKAGE}:id/home_food_card",
        ]:
            if self._tap_id(rid, timeout=4):
                print(f"[GrabOrder] Food delivery via ID {rid}")
                return True
        self.screenshot("/tmp/grab_order_food_fail.png")
        return False

    def set_delivery_address(self, address: str) -> bool:
        """Entre l'adresse de livraison du client."""
        self._human_delay(1, 2)
        for text in ["Where to?", "Deliver to", "Add delivery address",
                     "Enter delivery address", "Delivery address", "Where?"]:
            if self._tap_text(text, timeout=5):
                self._human_delay(0.5, 1)
                break

        for rid in [
            f"{GRAB_PACKAGE}:id/delivery_address",
            f"{GRAB_PACKAGE}:id/et_address",
            f"{GRAB_PACKAGE}:id/address_input",
            f"{GRAB_PACKAGE}:id/nolo_search_input_text",
            f"{GRAB_PACKAGE}:id/location_input",
            f"{GRAB_PACKAGE}:id/search_input",
        ]:
            try:
                el = WebDriverWait(self.driver, 6).until(
                    EC.element_to_be_clickable((AppiumBy.ID, rid))
                )
                el.clear()
                self._human_delay(0.3, 0.6)
                el.send_keys(address)
                self._human_delay(2.5, 3.5)
                for sel in [
                    'new UiSelector().resourceIdMatches(".*result.*").instance(0)',
                    'new UiSelector().resourceIdMatches(".*suggestion.*").instance(0)',
                    'new UiSelector().resourceIdMatches(".*list.*item.*").instance(0)',
                ]:
                    try:
                        sug = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                        sug.click()
                        print(f"[GrabOrder] ✅ Adresse : {address}")
                        self._human_delay(2, 3)
                        return True
                    except: continue
                rvs = self.driver.find_elements(
                    AppiumBy.CLASS_NAME, "androidx.recyclerview.widget.RecyclerView"
                )
                if rvs:
                    items = rvs[0].find_elements(AppiumBy.XPATH, ".//*[@clickable='true']")
                    if items:
                        items[0].click()
                        self._human_delay(2, 3)
                        return True
            except: continue

        self.screenshot("/tmp/grab_order_address_fail.png")
        return False

    def open_for_order(self, delivery_address: str) -> dict:
        """Flow complet : Food → adresse → ready pour admin."""
        result = {"ok": False, "step": "", "screenshot": ""}
        try:
            if not self.navigate_to_food():
                result["step"] = "food_nav_failed"
                result["screenshot"] = "/tmp/grab_order_food_fail.png"
                return result
            if not self.set_delivery_address(delivery_address):
                result["step"] = "address_failed"
                result["screenshot"] = "/tmp/grab_order_address_fail.png"
                return result
            shot = f"/tmp/grab_order_ready_{int(time.time())}.png"
            self.screenshot(shot)
            result["ok"] = True
            result["step"] = "ready_for_admin"
            result["screenshot"] = shot
        except Exception as e:
            result["step"] = f"error: {e}"
            self.screenshot("/tmp/grab_order_error.png")
            result["screenshot"] = "/tmp/grab_order_error.png"
        return result


def launch_order(order_id: str, delivery_address: str,
                 device_id: str = "emulator-5554") -> dict:
    """Point d'entrée appelé par l'API Flask lors du clic 'Valider & Commander'."""
    with GrabOrder(device_id) as go:
        return go.open_for_order(delivery_address)
