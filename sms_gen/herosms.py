"""
Hero SMS (hero-sms.com) — client API
API identique à SMS-Activate
Numéros virtuels pour OTP Grab Thaïlande
"""
import time, re, requests

BASE    = "https://hero-sms.com/stubs/handler_api.php"
TIMEOUT = 15

COUNTRIES = {
    "thailand":    52,
    "france":      78,
    "us":          0,
    "uk":          16,
    "indonesia":   6,
    "philippines": 4,
    "vietnam":     10,
}

# "gr" = Grab (3242 numéros dispo confirmés)
GRAB_SERVICES = ["gr", "grab", "gg"]

class HeroSMSError(Exception):
    pass

class HeroSMS:
    def __init__(self, api_key: str):
        self.key     = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def _call(self, **params) -> str:
        params["api_key"] = self.key
        r = self.session.get(BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("BAD_"):
            raise HeroSMSError(text)
        if text == "NO_NUMBERS":
            raise HeroSMSError("NO_NUMBERS — stock épuisé")
        if text == "NO_BALANCE":
            raise HeroSMSError("NO_BALANCE — solde insuffisant")
        if text == "ERROR_SQL":
            raise HeroSMSError("Erreur serveur Hero SMS")
        return text

    # ── Solde ─────────────────────────────────────────────
    def balance(self) -> float:
        r = self._call(action="getBalance")
        m = re.search(r"ACCESS_BALANCE:([\d.]+)", r)
        return float(m.group(1)) if m else 0.0

    # ── Acheter un numéro ─────────────────────────────────
    def buy(self, service: str = "gr", country: int = 52) -> dict:
        r = self._call(action="getNumber", service=service, country=country)
        # ACCESS_NUMBER:order_id:phone
        m = re.match(r"ACCESS_NUMBER:(\d+):(\d+)", r)
        if not m:
            raise HeroSMSError(f"Format inattendu: {r}")
        return {
            "id":      int(m.group(1)),
            "phone":   "+" + m.group(2),
            "service": service,
            "country": country,
        }

    # ── Statut ────────────────────────────────────────────
    def check(self, order_id: int) -> dict:
        r = self._call(action="getStatus", id=order_id)
        if r in ("STATUS_WAIT_CODE", "STATUS_WAIT_RETRY"):
            return {"status": "waiting", "code": None}
        if r == "STATUS_CANCEL":
            return {"status": "canceled", "code": None}
        m = re.match(r"STATUS_OK:(.+)", r)
        if m:
            return {"status": "received", "code": m.group(1).strip()}
        return {"status": "unknown", "code": None, "raw": r}

    # ── Annuler ───────────────────────────────────────────
    def cancel(self, order_id: int):
        try: self._call(action="setStatus", id=order_id, status=8)
        except: pass

    # ── Confirmer ─────────────────────────────────────────
    def finish(self, order_id: int):
        try: self._call(action="setStatus", id=order_id, status=6)
        except: pass

    # ── Redemander SMS ────────────────────────────────────
    def retry(self, order_id: int):
        try: self._call(action="setStatus", id=order_id, status=3)
        except: pass

    # ── Poll jusqu'au SMS ─────────────────────────────────
    def wait_sms(self, order_id: int, timeout: int = 120, poll: int = 5) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.check(order_id)
            if result["status"] == "received":
                self.finish(order_id)
                return result["code"]
            if result["status"] == "canceled":
                raise HeroSMSError(f"Order {order_id} annulé")
            time.sleep(poll)
        self.cancel(order_id)
        raise HeroSMSError(f"Timeout {timeout}s — OTP non reçu")

    # ── Achat Grab avec fallback ───────────────────────────
    def buy_for_grab(self, country: str = "thailand") -> dict:
        country_id = COUNTRIES.get(country, 52)
        last_err   = None
        for svc in GRAB_SERVICES:
            try:
                order = self.buy(service=svc, country=country_id)
                order["_provider"] = "herosms"
                return order
            except HeroSMSError as e:
                last_err = e
                if "NO_NUMBERS" in str(e):
                    continue
                raise
        raise HeroSMSError(f"Aucun numéro Grab dispo: {last_err}")

    # ── Stock disponible ──────────────────────────────────
    def stock(self, country: int = 52) -> dict:
        """Retourne le nombre de numéros dispo par service pour un pays."""
        r = self._call(action="getNumbersStatus", country=country, operator="any")
        try:
            import json
            d = json.loads(r)
            return {k: int(v) for k, v in d.items() if int(v) > 0}
        except:
            return {}


# ── Test standalone ───────────────────────────────────────
if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else "05ef0b6f9230A0e7951514952f60e553"
    c   = HeroSMS(key)

    print(f"💰 Solde : {c.balance():.2f} €")

    stock = c.stock(52)
    grab_stock = stock.get("gr", 0)
    print(f"📱 Stock Grab Thaïlande : {grab_stock} numéros")

    if len(sys.argv) > 2 and sys.argv[2] == "buy":
        print("\n🛒 Achat numéro Grab Thaïlande...")
        try:
            order = c.buy_for_grab("thailand")
            print(f"  ✅ Numéro  : {order['phone']}")
            print(f"  🆔 Order   : {order['id']}")
            print(f"\n⏳ Attente OTP (90s)...")
            code = c.wait_sms(order["id"], timeout=90)
            print(f"  ✅ OTP : {code}")
        except HeroSMSError as e:
            print(f"  ❌ {e}")
