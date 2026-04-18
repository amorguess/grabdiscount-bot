"""
SMSPool (smspool.net) — client API corrigé
✅ PayPal accepté (idéal carte européenne)
✅ Numéros thaïlandais Grab confirmés
✅ $0.11–0.22 par numéro / Solde actuel : ~$9.38

Endpoints confirmés via tests directs :
  Balance : GET  /request/balance?key=
  Buy     : POST /purchase/sms  (country=52, service=1093)
  Check   : GET  /sms/check?key=&orderid=
  Cancel  : POST /sms/cancel    (orderid=)
"""
import time, re, requests

BASE    = "https://api.smspool.net"
TIMEOUT = 15

# IDs confirmés par l'API
THAILAND_ID = 52
GRAB_ID     = 1093   # service "Grab" Thailand

class SMSPoolError(Exception):
    pass

class SMSPool:
    def __init__(self, api_key: str):
        self.key     = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.key
        r = self.session.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, dict) and d.get("success") == 0:
            raise SMSPoolError(d.get("message", str(d)))
        return d

    def _post(self, path: str, **data) -> dict:
        data["key"] = self.key
        r = self.session.post(f"{BASE}{path}", data=data, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, dict) and d.get("success") == 0:
            raise SMSPoolError(d.get("message", str(d)))
        return d

    # ── Solde ────────────────────────────────────────────────
    def balance(self) -> float:
        d = self._get("/request/balance")
        return float(d.get("balance", 0))

    # ── Acheter un numéro Grab Thailand ─────────────────────
    def buy(self, country: int = THAILAND_ID, service: int = GRAB_ID) -> dict:
        return self._post("/purchase/sms", country=country, service=service)

    # ── Vérifier statut / récupérer SMS ─────────────────────
    def check(self, order_id: str) -> dict:
        return self._get("/sms/check", orderid=order_id)

    # ── Terminer (libérer le numéro après réception OTP) ────
    def finish(self, order_id: str):
        """Marque le numéro comme utilisé (status=6 = SMS reçu)."""
        try:
            self._post("/sms/set", orderid=order_id, status=6)
        except: pass

    # ── Annuler ──────────────────────────────────────────────
    def cancel(self, order_id: str):
        try:
            self._post("/sms/cancel", orderid=order_id)
        except: pass

    # ── Resend SMS ───────────────────────────────────────────
    def resend(self, order_id: str):
        try:
            self._post("/sms/resend", orderid=order_id)
        except: pass

    # ── Poll jusqu'au SMS (interface unifiée) ────────────────
    def wait_sms(self, order_id: str, timeout: int = 120, poll: int = 5) -> str:
        """
        Retourne le CODE OTP (string).
        Compatible avec le reste du projet (HeroSMS, 5sim, etc.)
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.check(order_id)
            sms = d.get("sms", "")

            if sms:
                # Extraire les chiffres OTP du texte du SMS
                code = re.search(r"\b(\d{4,8})\b", str(sms))
                if code:
                    return code.group(1)
                return str(sms)

            # status 0 = en attente, autre = problème
            status = d.get("status", 0)
            if status not in (0, 1):
                raise SMSPoolError(f"Order {order_id} terminé, statut={status}")

            time.sleep(poll)

        self.cancel(order_id)
        raise SMSPoolError(f"Timeout ({timeout}s) — OTP non reçu pour {order_id}")

    # ── Interface unifiée buy_for_grab ───────────────────────
    def buy_for_grab(self, country: str = "thailand") -> dict:
        """
        Achète un numéro Grab Thailand.
        Retourne {id, phone, service, country, _provider}
        Compatible orchestrateur.
        """
        order = self.buy(country=THAILAND_ID, service=GRAB_ID)

        phone = str(order.get("number", ""))
        if not phone.startswith("+"):
            phone = "+" + phone          # ex: +66863982138

        return {
            "id":        str(order["orderid"]),
            "phone":     phone,
            "service":   "Grab",
            "country":   "Thailand",
            "_provider": "smspool",
            "_raw":      order,
        }


# ── Test standalone ────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 smspool.py API_KEY [buy]")
        sys.exit(1)

    key    = sys.argv[1]
    client = SMSPool(key)

    bal = client.balance()
    print(f"💰 Solde     : ${bal:.2f}")
    print(f"📱 Prix Grab : $0.11–0.22 / numéro")
    print(f"🔢 Numéros   : ~{int(bal/0.15)} comptes possibles")

    if len(sys.argv) > 2 and sys.argv[2] == "buy":
        print("\n🛒 Achat numéro Grab Thailand...")
        try:
            order = client.buy_for_grab()
            print(f"  ✅ Numéro  : {order['phone']}")
            print(f"  🆔 Order   : {order['id']}")
            print(f"\n⏳ Attente OTP (90s)...")
            code = client.wait_sms(order["id"], timeout=90)
            print(f"  ✅ OTP : {code}")
        except SMSPoolError as e:
            print(f"  ❌ {e}")
