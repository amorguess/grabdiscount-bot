"""
SMS-Activate (sms-activate.org) — client API
Numéros virtuels pour OTP Grab Thaïlande
"""
import time, re, requests

BASE    = "https://api.sms-activate.org/stubs/handler_api.php"
TIMEOUT = 15

# Codes pays SMS-Activate
COUNTRIES = {
    "thailand":     52,
    "france":       78,
    "us":           0,
    "uk":           16,
    "indonesia":    6,
    "philippines":  4,
    "vietnam":      10,
}

# Services Grab sur SMS-Activate
GRAB_SERVICES = ["gr", "grab", "gg"]   # "gr" = Grab code officiel

class SMSActivateError(Exception):
    pass

class SMSActivate:
    def __init__(self, api_key: str):
        self.key     = api_key
        self.session = requests.Session()

    def _call(self, **params) -> str:
        params["api_key"] = self.key
        r = self.session.get(BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("BAD_"):
            raise SMSActivateError(text)
        if text == "NO_NUMBERS":
            raise SMSActivateError("NO_NUMBERS — stock épuisé pour ce service/pays")
        if text == "NO_BALANCE":
            raise SMSActivateError("NO_BALANCE — solde insuffisant")
        if text == "ERROR_SQL":
            raise SMSActivateError("Erreur serveur SMS-Activate")
        return text

    # ── Solde ─────────────────────────────────────────────
    def balance(self) -> float:
        r = self._call(action="getBalance")
        # réponse : "ACCESS_BALANCE:12.50"
        m = re.search(r"ACCESS_BALANCE:([\d.]+)", r)
        return float(m.group(1)) if m else 0.0

    # ── Acheter un numéro ─────────────────────────────────
    def buy(self, service: str = "gr", country: int = 52) -> dict:
        """
        Achète un numéro. Retourne {id, phone}.
        service : code SMS-Activate (ex: "gr" pour Grab)
        country : 52 = Thaïlande
        """
        r = self._call(action="getNumber", service=service, country=country)
        # réponse : "ACCESS_NUMBER:12345678:66812345678"
        m = re.match(r"ACCESS_NUMBER:(\d+):(\d+)", r)
        if not m:
            raise SMSActivateError(f"Format inattendu getNumber: {r}")
        order_id = int(m.group(1))
        phone    = "+" + m.group(2)
        return {"id": order_id, "phone": phone, "service": service, "country": country}

    # ── Statut / récupérer SMS ────────────────────────────
    def check(self, order_id: int) -> dict:
        """
        Retourne {status, code}.
        status : waiting | received | canceled | timeout
        """
        r = self._call(action="getStatus", id=order_id)
        if r == "STATUS_WAIT_CODE":
            return {"status": "waiting", "code": None}
        if r == "STATUS_WAIT_RETRY":
            return {"status": "waiting", "code": None}
        if r == "STATUS_CANCEL":
            return {"status": "canceled", "code": None}
        m = re.match(r"STATUS_OK:(.+)", r)
        if m:
            return {"status": "received", "code": m.group(1).strip()}
        return {"status": "unknown", "code": None, "raw": r}

    # ── Annuler ───────────────────────────────────────────
    def cancel(self, order_id: int):
        try:
            self._call(action="setStatus", id=order_id, status=8)
        except SMSActivateError:
            pass

    # ── Confirmer réception ───────────────────────────────
    def finish(self, order_id: int):
        try:
            self._call(action="setStatus", id=order_id, status=6)
        except SMSActivateError:
            pass

    # ── Redemander SMS ────────────────────────────────────
    def retry(self, order_id: int):
        try:
            self._call(action="setStatus", id=order_id, status=3)
        except SMSActivateError:
            pass

    # ── Poll jusqu'au SMS ─────────────────────────────────
    def wait_sms(self, order_id: int, timeout: int = 120, poll: int = 5) -> str:
        """
        Poll toutes les `poll` secondes.
        Retourne le code OTP (string) ou lève SMSActivateError.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.check(order_id)
            if result["status"] == "received":
                self.finish(order_id)
                return result["code"]
            if result["status"] == "canceled":
                raise SMSActivateError(f"Order {order_id} annulé")
            time.sleep(poll)
        self.cancel(order_id)
        raise SMSActivateError(f"Timeout {timeout}s — OTP non reçu")

    # ── Achat Grab avec fallback services ─────────────────
    def buy_for_grab(self, country: str = "thailand") -> dict:
        """
        Essaie les services Grab dans l'ordre jusqu'à succès.
        Retourne le dict order avec client attaché.
        """
        country_id = COUNTRIES.get(country, 52)
        last_err   = None
        for svc in GRAB_SERVICES:
            try:
                order = self.buy(service=svc, country=country_id)
                order["_provider"] = "smsactivate"
                return order
            except SMSActivateError as e:
                last_err = e
                if "NO_NUMBERS" in str(e):
                    continue   # essaie service suivant
                raise          # autre erreur → arrête
        raise SMSActivateError(
            f"Aucun numéro Grab dispo en {country} (country_id={country_id}): {last_err}"
        )


# ── Test standalone ───────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 smsactivate.py API_KEY")
        sys.exit(1)

    key    = sys.argv[1]
    client = SMSActivate(key)

    print(f"💰 Solde : {client.balance():.2f}₽")

    print("\n📱 Achat numéro Grab Thaïlande...")
    try:
        order = client.buy_for_grab("thailand")
        print(f"  ✅ Numéro  : {order['phone']}")
        print(f"  🆔 Order   : {order['id']}")
        print(f"  📦 Service : {order['service']}")
        print(f"\n⏳ Attente OTP (90s max)...")
        code = client.wait_sms(order["id"], timeout=90)
        print(f"  ✅ Code OTP : {code}")
    except SMSActivateError as e:
        print(f"  ❌ {e}")
