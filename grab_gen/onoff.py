"""
OnOff web scraper — lit les SMS entrants et gère les numéros
Interface : https://app.onoff.app
"""
import asyncio, re, time
from playwright.async_api import async_playwright, Page, BrowserContext

LOGIN_URL  = "https://app.onoff.app"
SMS_WAIT   = 90   # secondes max pour attendre un SMS

class OnOffError(Exception):
    pass

class OnOffClient:
    def __init__(self, email: str, password: str, headless: bool = True):
        self.email     = email
        self.password  = password
        self.headless  = headless
        self._pw       = None
        self._browser  = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self):
        await self._start()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def _start(self):
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.ctx  = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/123 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
        )
        self.page = await self.ctx.new_page()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Connexion ─────────────────────────────────────────────
    async def login(self) -> bool:
        """Se connecte à app.onoff.app. Retourne True si succès."""
        p = self.page
        await p.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Cherche le champ email
        try:
            await p.fill('input[type="email"], input[name="email"]', self.email, timeout=10000)
            await p.fill('input[type="password"], input[name="password"]', self.password, timeout=5000)
            await p.click('button[type="submit"], button:has-text("Connexion"), button:has-text("Sign in")', timeout=5000)
            await p.wait_for_url(lambda url: "app.onoff.app" in url and "login" not in url, timeout=20000)
            print(f"[OnOff] ✅ Connecté : {self.email}")
            return True
        except Exception as e:
            # Tente de sauvegarder un screenshot pour debug
            await p.screenshot(path="/tmp/onoff_login_debug.png")
            raise OnOffError(f"Échec connexion OnOff : {e}")

    # ── Liste des numéros disponibles ─────────────────────────
    async def get_numbers(self) -> list[dict]:
        """Retourne la liste des numéros OnOff du compte."""
        p = self.page
        await p.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)

        numbers = []
        try:
            # Les numéros sont en sidebar ou liste — adapte selon l'UI réelle
            items = await p.query_selector_all('[class*="number"], [class*="phone"], [data-testid*="number"]')
            for item in items:
                text = (await item.inner_text()).strip()
                # Extrait les chiffres qui ressemblent à un numéro de téléphone
                m = re.search(r'(\+?\d[\d\s\-\.]{7,})', text)
                if m:
                    num = re.sub(r'[\s\-\.]', '', m.group(1))
                    numbers.append({"number": num, "raw": text})
        except Exception as e:
            print(f"[OnOff] ⚠ get_numbers: {e}")

        return numbers

    # ── Attendre un SMS entrant sur un numéro ─────────────────
    async def wait_sms(self, number: str, keyword: str = "", timeout: int = SMS_WAIT) -> str | None:
        """
        Poll la boîte SMS OnOff jusqu'à recevoir un message contenant `keyword`
        sur le numéro `number`. Retourne le texte du SMS ou None.
        """
        p    = self.page
        norm = re.sub(r'[\s\-\.]', '', number)
        deadline = time.time() + timeout

        print(f"[OnOff] ⏳ Attente SMS sur {number}…")

        while time.time() < deadline:
            try:
                # Navigue vers la vue SMS du numéro
                # L'URL exacte dépend de l'interface OnOff — ajuster si nécessaire
                await p.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.5)

                # Cherche les messages SMS dans la page
                messages = await p.query_selector_all(
                    '[class*="sms"], [class*="message"], [class*="conversation"], [data-testid*="sms"]'
                )

                for msg in messages:
                    text = (await msg.inner_text()).strip()
                    if keyword and keyword.lower() not in text.lower():
                        continue
                    # Cherche un code OTP (4-8 chiffres)
                    code_m = re.search(r'\b(\d{4,8})\b', text)
                    if code_m:
                        code = code_m.group(1)
                        print(f"[OnOff] ✅ SMS reçu — code : {code}")
                        return text

            except Exception as e:
                print(f"[OnOff] ⚠ poll: {e}")

            await asyncio.sleep(5)

        print(f"[OnOff] ⏱ Timeout — aucun SMS reçu sur {number}")
        return None

    # ── Screenshot debug ──────────────────────────────────────
    async def screenshot(self, path: str = "/tmp/onoff_debug.png"):
        await self.page.screenshot(path=path)
        print(f"[OnOff] 📸 Screenshot → {path}")

    # ── Explore l'interface (pour calibrage) ──────────────────
    async def explore(self) -> dict:
        """Retourne le HTML de la page principale pour identifier les sélecteurs."""
        p = self.page
        await p.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)
        await p.screenshot(path="/tmp/onoff_explore.png")
        url   = p.url
        title = await p.title()
        # Récupère tous les éléments cliquables pour trouver les bons sélecteurs
        elements = await p.evaluate("""() => {
            const els = document.querySelectorAll('button, a, [role="button"], input');
            return Array.from(els).slice(0, 50).map(e => ({
                tag:  e.tagName,
                text: e.innerText?.slice(0, 60),
                cls:  e.className?.slice(0, 80),
                id:   e.id,
                type: e.type,
                href: e.href,
            }));
        }""")
        return {"url": url, "title": title, "elements": elements}


# ── Test standalone ────────────────────────────────────────────
async def _test(email, password):
    async with OnOffClient(email, password, headless=False) as c:
        await c.login()
        print("[OnOff] Exploration de l'interface…")
        info = await c.explore()
        print(f"URL: {info['url']}  |  Titre: {info['title']}")
        print(f"Éléments trouvés ({len(info['elements'])}) :")
        for e in info["elements"][:20]:
            print(f"  {e['tag']:10} | {e.get('text','')[:40]:40} | cls={e.get('cls','')[:50]}")
        print("\n📸 Screenshot → /tmp/onoff_explore.png")
        numbers = await c.get_numbers()
        print(f"\nNuméros détectés : {numbers}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 onoff.py EMAIL PASSWORD")
        sys.exit(1)
    asyncio.run(_test(sys.argv[1], sys.argv[2]))
