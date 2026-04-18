"""
Grab Food — création de compte automatique via Playwright
Supporte : SMS OTP ou WhatsApp OTP
"""
import asyncio, re, time, json, random, string
from playwright.async_api import async_playwright, Page

GRAB_SIGNUP_URL = "https://food.grab.com/th/en/signup"
GRAB_LOGIN_URL  = "https://food.grab.com/th/en/login"

# Stealth — évite la détection Playwright
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-TH','en','th']});
window.chrome = {runtime: {}};
"""

class GrabRegError(Exception):
    pass

class GrabRegistration:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw      = None
        self._browser = None
        self.page: Page | None = None

    async def __aenter__(self):
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--lang=en-TH",
            ],
        )
        ctx = await self._browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            viewport={"width": 390, "height": 844},
            locale="en-TH",
            timezone_id="Asia/Bangkok",
            geolocation={"latitude": 13.7563, "longitude": 100.5018},
            permissions=["geolocation"],
        )
        self.page = await ctx.new_page()
        # Injecte stealth JS
        await self.page.add_init_script(STEALTH_JS)
        return self

    async def __aexit__(self, *_):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Délai humain ──────────────────────────────────────────
    async def _human_delay(self, min_ms=800, max_ms=2000):
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    async def _type_human(self, selector: str, text: str):
        """Tape caractère par caractère avec délais aléatoires."""
        await self.page.click(selector)
        await self._human_delay(200, 500)
        for ch in text:
            await self.page.type(selector, ch, delay=random.randint(80, 180))

    # ── Explore l'interface signup ─────────────────────────────
    async def explore_signup(self) -> dict:
        """Visite la page signup et retourne les infos pour calibrage."""
        p = self.page
        await p.goto(GRAB_SIGNUP_URL, wait_until="networkidle", timeout=30000)
        await self._human_delay(1500, 3000)
        await p.screenshot(path="/tmp/grab_signup.png")
        url   = p.url
        title = await p.title()
        inputs = await p.evaluate("""() => {
            const els = document.querySelectorAll('input, button, select, [role="button"]');
            return Array.from(els).slice(0, 40).map(e => ({
                tag:         e.tagName,
                type:        e.type,
                placeholder: e.placeholder,
                name:        e.name,
                id:          e.id,
                text:        e.innerText?.slice(0,60),
                cls:         e.className?.slice(0,80),
            }));
        }""")
        return {"url": url, "title": title, "inputs": inputs}

    # ── Étape 1 : Entrer numéro de téléphone ─────────────────
    async def enter_phone(self, phone: str, country_code: str = "+33") -> bool:
        """
        Navigue vers signup Grab, entre le numéro.
        phone = numéro sans indicatif (ex: "612345678")
        country_code = "+33", "+1", "+66"…
        Retourne True si OTP demandé avec succès.
        """
        p = self.page
        await p.goto(GRAB_SIGNUP_URL, wait_until="networkidle", timeout=30000)
        await self._human_delay(1500, 2500)
        await p.screenshot(path="/tmp/grab_step1.png")

        try:
            # Clique sur le sélecteur de pays (+XX)
            country_selectors = [
                '[class*="country"]',
                '[class*="phone-code"]',
                '[class*="dial-code"]',
                'button:has-text("+")',
                '[data-testid*="country"]',
            ]
            for sel in country_selectors:
                el = await p.query_selector(sel)
                if el:
                    await el.click()
                    await self._human_delay(500, 1000)
                    break

            # Cherche et sélectionne l'indicatif pays
            code_input = await p.query_selector('input[placeholder*="country"], input[placeholder*="pays"], input[placeholder*="search"]')
            if code_input:
                await code_input.fill(country_code.replace("+", ""))
                await self._human_delay(500, 800)

            # Sélectionne le bon pays dans la liste
            option_sels = [
                f'[data-value="{country_code}"]',
                f'li:has-text("{country_code}")',
                f'[class*="option"]:has-text("{country_code}")',
            ]
            for sel in option_sels:
                el = await p.query_selector(sel)
                if el:
                    await el.click()
                    await self._human_delay(400, 700)
                    break

        except Exception as e:
            print(f"[GrabReg] ⚠ Sélection pays: {e}")

        # Entre le numéro
        phone_sels = [
            'input[type="tel"]',
            'input[placeholder*="phone"], input[placeholder*="téléphone"], input[placeholder*="mobile"]',
            'input[name*="phone"], input[id*="phone"]',
        ]
        phone_entered = False
        for sel in phone_sels:
            try:
                await self.page.wait_for_selector(sel, timeout=5000)
                await self._type_human(sel, phone)
                phone_entered = True
                break
            except Exception:
                continue

        if not phone_entered:
            await p.screenshot(path="/tmp/grab_phone_error.png")
            raise GrabRegError("Impossible de trouver le champ téléphone")

        await self._human_delay(800, 1500)

        # Clique sur le bouton "Continuer" / "Get OTP"
        submit_sels = [
            'button:has-text("Continue")',
            'button:has-text("Get OTP")',
            'button:has-text("Send OTP")',
            'button[type="submit"]',
            'button:has-text("Next")',
        ]
        submitted = False
        for sel in submit_sels:
            try:
                await p.click(sel, timeout=4000)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            raise GrabRegError("Bouton submit non trouvé")

        await self._human_delay(2000, 3000)
        await p.screenshot(path="/tmp/grab_step2.png")

        # Vérifie si on est sur l'étape OTP
        page_text = await p.inner_text("body")
        otp_keywords = ["otp", "verification", "code", "verify", "whatsapp", "sms"]
        if any(k in page_text.lower() for k in otp_keywords):
            print(f"[GrabReg] ✅ OTP demandé pour {country_code}{phone}")
            return True

        print(f"[GrabReg] ⚠ Statut incertain après submit — screenshot → /tmp/grab_step2.png")
        return False

    # ── Choisir WhatsApp comme canal OTP ─────────────────────
    async def choose_whatsapp_otp(self) -> bool:
        """Si Grab propose le choix SMS/WhatsApp, sélectionne WhatsApp."""
        p = self.page
        try:
            wa_sels = [
                'button:has-text("WhatsApp")',
                '[class*="whatsapp"]',
                'label:has-text("WhatsApp")',
            ]
            for sel in wa_sels:
                el = await p.query_selector(sel)
                if el:
                    await el.click()
                    await self._human_delay(500, 1000)
                    print("[GrabReg] ✅ Canal WhatsApp sélectionné")
                    return True
        except Exception:
            pass
        print("[GrabReg] ℹ Canal WhatsApp non trouvé — SMS utilisé par défaut")
        return False

    # ── Étape 2 : Entrer le code OTP ─────────────────────────
    async def enter_otp(self, code: str) -> bool:
        """Entre le code OTP reçu par SMS ou WhatsApp."""
        p = self.page
        await self._human_delay(500, 1000)

        otp_sels = [
            'input[type="number"]',
            'input[placeholder*="OTP"], input[placeholder*="code"], input[placeholder*="Code"]',
            'input[name*="otp"], input[id*="otp"], input[name*="code"]',
            'input[maxlength="6"], input[maxlength="4"]',
        ]

        entered = False
        for sel in otp_sels:
            try:
                await p.wait_for_selector(sel, timeout=5000)
                # Certains Grab ont des cases individuelles (1 chiffre par case)
                inputs = await p.query_selector_all(sel)
                if len(inputs) > 1:
                    # Cases individuelles
                    for i, digit in enumerate(code[:len(inputs)]):
                        await inputs[i].click()
                        await asyncio.sleep(random.uniform(0.1, 0.3))
                        await inputs[i].type(digit, delay=random.randint(80, 150))
                else:
                    await self._type_human(sel, code)
                entered = True
                break
            except Exception:
                continue

        if not entered:
            await p.screenshot(path="/tmp/grab_otp_error.png")
            raise GrabRegError("Champ OTP introuvable")

        await self._human_delay(800, 1500)

        # Valide
        confirm_sels = [
            'button:has-text("Verify")',
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
            'button[type="submit"]',
        ]
        for sel in confirm_sels:
            try:
                await p.click(sel, timeout=3000)
                break
            except Exception:
                continue

        await self._human_delay(2000, 4000)
        await p.screenshot(path="/tmp/grab_step3.png")

        page_text = await p.inner_text("body")
        success_kw = ["name", "nom", "profile", "profil", "welcome", "bienvenue", "email", "password"]
        return any(k in page_text.lower() for k in success_kw)

    # ── Étape 3 : Remplir le profil ───────────────────────────
    async def fill_profile(self, name: str, email: str, password: str) -> bool:
        """Remplit nom, email, mot de passe pour finaliser l'inscription."""
        p = self.page
        await self._human_delay(500, 1000)

        fields = {
            'input[name*="name"], input[placeholder*="Name"], input[placeholder*="name"]': name,
            'input[type="email"], input[name*="email"]': email,
            'input[type="password"], input[name*="password"]': password,
        }

        for sel, val in fields.items():
            try:
                el = await p.query_selector(sel)
                if el:
                    await self._type_human(sel, val)
                    await self._human_delay(300, 700)
            except Exception:
                continue

        await self._human_delay(500, 1000)

        # Submit final
        for sel in ['button[type="submit"]', 'button:has-text("Create")', 'button:has-text("Register")']:
            try:
                await p.click(sel, timeout=3000)
                break
            except Exception:
                continue

        await self._human_delay(3000, 5000)
        await p.screenshot(path="/tmp/grab_final.png")

        page_text = await p.inner_text("body")
        return any(k in page_text.lower() for k in ["home", "restaurant", "food", "order", "accueil"])


# ── Test standalone ────────────────────────────────────────────
async def _test():
    async with GrabRegistration(headless=False) as gr:
        print("[Test] Exploration interface signup Grab…")
        info = await gr.explore_signup()
        print(f"URL: {info['url']}")
        print(f"Champs ({len(info['inputs'])}) :")
        for f in info["inputs"]:
            print(f"  {f['tag']:8} type={f.get('type',''):10} placeholder={f.get('placeholder',''):30} name={f.get('name','')}")
        print("📸 → /tmp/grab_signup.png")

if __name__ == "__main__":
    asyncio.run(_test())
