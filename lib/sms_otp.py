"""
sms_otp.py — Achat de numéros virtuels pour OTP
=================================================
Fichier autonome. Dépendance : requests (pip install requests).
Réutilisable dans n'importe quel projet Python 3.7+.

Providers supportés :
  - HeroSMS    (hero-sms.com)  — €0.03/numéro TH, PayPal ✅
  - SMSPool    (smspool.net)   — $0.11/numéro TH, PayPal ✅
  - SMSActivate (sms-activate.org) — cartes EU parfois bloquées

Usage en bibliothèque :
    from sms_otp import HeroSMS, SMSPool, SMSActivate

Usage CLI :
    python3 sms_otp.py herosms  VOTRE_CLE balance
    python3 sms_otp.py herosms  VOTRE_CLE buy [service] [pays]
    python3 sms_otp.py smspool  VOTRE_CLE balance
    python3 sms_otp.py smspool  VOTRE_CLE buy
"""
import time
import re
import requests

# ─────────────────────────────────────────────────────────────────
#  HEROSMS — hero-sms.com
# ─────────────────────────────────────────────────────────────────
class HeroSMSError(Exception):
    pass


class HeroSMS:
    """
    Client Hero SMS (API compatible SMS-Activate).
    Numéros TH Grab ≈ €0.03/numéro | stock : 4000+ TH.
    Recharge PayPal ✅, Wise ✅, crypto ✅.

    Exemple :
        sms = HeroSMS("VOTRE_CLE")
        print(sms.balance())        # solde €
        order = sms.buy_grab()      # {"id", "phone", ...}
        code  = sms.wait_otp(order["id"])  # "123456"
        sms.finish(order["id"])
    """

    BASE       = "https://hero-sms.com/stubs/handler_api.php"
    TIMEOUT    = 15

    # Codes pays courants
    COUNTRIES = {
        "thailand":    52,
        "france":      78,
        "us":          0,
        "uk":          16,
        "indonesia":   6,
        "philippines": 4,
        "vietnam":     10,
    }

    def __init__(self, api_key: str):
        self.key  = api_key
        self._ses = requests.Session()
        self._ses.headers["User-Agent"] = "Mozilla/5.0"

    def _call(self, **params) -> str:
        params["api_key"] = self.key
        r = self._ses.get(self.BASE, params=params, timeout=self.TIMEOUT)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("BAD_") or text in ("NO_NUMBERS","NO_BALANCE","ERROR_SQL"):
            raise HeroSMSError(text)
        return text

    def balance(self) -> float:
        """Retourne le solde en euros."""
        r = self._call(action="getBalance")
        m = re.search(r"ACCESS_BALANCE:([\d.]+)", r)
        return float(m.group(1)) if m else 0.0

    def buy(self, service: str = "gr", country: int = 52) -> dict:
        """
        Achète un numéro virtuel.

        Args:
            service: Code service (ex: "gr" = Grab, "ig" = Instagram).
            country: Code pays (52 = Thaïlande, 78 = France, 0 = USA).

        Returns:
            dict: {"id": int, "phone": str "+66...", "service": str}
        """
        r = self._call(action="getNumber", service=service, country=country)
        m = re.match(r"ACCESS_NUMBER:(\d+):(\d+)", r)
        if not m:
            raise HeroSMSError(f"Réponse inattendue: {r}")
        return {
            "id":       int(m.group(1)),
            "phone":    "+" + m.group(2),
            "service":  service,
            "country":  country,
            "_provider": "herosms",
        }

    def buy_grab(self, country: int = 52) -> dict:
        """Raccourci : achète un numéro pour Grab Thailand."""
        return self.buy(service="gr", country=country)

    def check(self, order_id: int) -> dict:
        """
        Vérifie le statut d'une commande.

        Returns:
            dict: {"status": "waiting"|"received"|"canceled", "code": str|None}
        """
        r = self._call(action="getStatus", id=order_id)
        if r in ("STATUS_WAIT_CODE", "STATUS_WAIT_RETRY"):
            return {"status": "waiting", "code": None}
        if r == "STATUS_CANCEL":
            return {"status": "canceled", "code": None}
        m = re.match(r"STATUS_OK:(.+)", r)
        if m:
            return {"status": "received", "code": m.group(1).strip()}
        return {"status": "unknown", "code": None, "raw": r}

    def finish(self, order_id: int):
        """Marque l'OTP comme reçu (libère le numéro)."""
        try:
            self._call(action="setStatus", id=order_id, status=6)
        except HeroSMSError:
            pass

    def cancel(self, order_id: int):
        """Annule la commande et rembourse le solde."""
        try:
            self._call(action="setStatus", id=order_id, status=8)
        except HeroSMSError:
            pass

    def wait_otp(self, order_id: int, timeout: int = 120, poll: int = 5) -> str:
        """
        Attend le code OTP (polling).

        Args:
            order_id: ID retourné par buy().
            timeout:  Durée max en secondes (défaut 120).
            poll:     Intervalle de polling en secondes (défaut 5).

        Returns:
            Code OTP sous forme de string (ex: "123456").

        Raises:
            HeroSMSError: Si timeout ou commande annulée.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.check(order_id)
            if d["status"] == "received" and d["code"]:
                code = re.search(r"\b(\d{4,8})\b", d["code"])
                return code.group(1) if code else d["code"]
            if d["status"] == "canceled":
                raise HeroSMSError(f"Commande {order_id} annulée")
            time.sleep(poll)

        self.cancel(order_id)
        raise HeroSMSError(f"Timeout {timeout}s — OTP non reçu")


# ─────────────────────────────────────────────────────────────────
#  SMSPOOL — smspool.net
# ─────────────────────────────────────────────────────────────────
class SMSPoolError(Exception):
    pass


class SMSPool:
    """
    Client SMSPool (smspool.net).
    Numéros TH Grab ≈ $0.11–0.20/numéro | PayPal ✅.

    Exemple :
        sms = SMSPool("VOTRE_CLE")
        print(sms.balance())       # solde $
        order = sms.buy_grab()     # {"id", "phone", ...}
        code  = sms.wait_otp(order["id"])
        sms.finish(order["id"])
    """

    BASE    = "https://api.smspool.net"
    TIMEOUT = 15

    # IDs service/pays pour Grab Thailand
    THAILAND_ID = 52
    GRAB_ID     = 1093

    def __init__(self, api_key: str):
        self.key  = api_key
        self._ses = requests.Session()
        self._ses.headers["User-Agent"] = "Mozilla/5.0"

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.key
        r = self._ses.get(f"{self.BASE}{path}", params=params, timeout=self.TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, dict) and d.get("success") == 0:
            raise SMSPoolError(d.get("message", str(d)))
        return d

    def _post(self, path: str, **data) -> dict:
        data["key"] = self.key
        r = self._ses.post(f"{self.BASE}{path}", data=data, timeout=self.TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, dict) and d.get("success") == 0:
            raise SMSPoolError(d.get("message", str(d)))
        return d

    def balance(self) -> float:
        """Retourne le solde en dollars."""
        d = self._get("/request/balance")
        return float(d.get("balance", 0))

    def buy(self, country: int = None, service: int = None) -> dict:
        """Achète un numéro virtuel."""
        country = country or self.THAILAND_ID
        service = service or self.GRAB_ID
        return self._post("/purchase/sms", country=country, service=service)

    def buy_grab(self) -> dict:
        """
        Achète un numéro Grab Thailand.

        Returns:
            dict: {"id": str, "phone": str "+66...", ...}
        """
        order = self.buy()
        phone = str(order.get("number", ""))
        if not phone.startswith("+"):
            phone = "+" + phone
        return {
            "id":        str(order["orderid"]),
            "phone":     phone,
            "service":   "Grab",
            "country":   "Thailand",
            "_provider": "smspool",
            "_raw":      order,
        }

    def check(self, order_id: str) -> dict:
        """Vérifie le statut d'une commande."""
        return self._get("/sms/check", orderid=order_id)

    def finish(self, order_id: str):
        """Marque le numéro comme utilisé."""
        try:
            self._post("/sms/set", orderid=order_id, status=6)
        except SMSPoolError:
            pass

    def cancel(self, order_id: str):
        """Annule et rembourse."""
        try:
            self._post("/sms/cancel", orderid=order_id)
        except SMSPoolError:
            pass

    def resend(self, order_id: str):
        """Renvoie le SMS."""
        try:
            self._post("/sms/resend", orderid=order_id)
        except SMSPoolError:
            pass

    def wait_otp(self, order_id: str, timeout: int = 120, poll: int = 5) -> str:
        """
        Attend le code OTP (polling).

        Args:
            order_id: ID de commande (string).
            timeout:  Durée max en secondes.
            poll:     Intervalle de polling en secondes.

        Returns:
            Code OTP (ex: "123456").

        Raises:
            SMSPoolError: Si timeout ou statut invalide.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.check(order_id)
            sms = d.get("sms", "")
            if sms:
                code = re.search(r"\b(\d{4,8})\b", str(sms))
                return code.group(1) if code else str(sms)
            status = d.get("status", 0)
            if status not in (0, 1):
                raise SMSPoolError(f"Statut inattendu: {status} pour {order_id}")
            time.sleep(poll)

        self.cancel(order_id)
        raise SMSPoolError(f"Timeout {timeout}s — OTP non reçu pour {order_id}")


# ─────────────────────────────────────────────────────────────────
#  SMSACTIVATE — sms-activate.org
# ─────────────────────────────────────────────────────────────────
class SMSActivateError(Exception):
    pass


class SMSActivate:
    """
    Client SMS-Activate (sms-activate.org).
    Cartes EU parfois bloquées — préférer HeroSMS ou SMSPool.

    Exemple :
        sms = SMSActivate("VOTRE_CLE")
        print(sms.balance())
        order = sms.buy("gr", 52)
        code  = sms.wait_otp(order["id"])
    """

    BASE    = "https://api.sms-activate.org/stubs/handler_api.php"
    TIMEOUT = 15

    def __init__(self, api_key: str):
        self.key  = api_key
        self._ses = requests.Session()

    def _call(self, **params) -> str:
        params["api_key"] = self.key
        r = self._ses.get(self.BASE, params=params, timeout=self.TIMEOUT)
        r.raise_for_status()
        return r.text.strip()

    def balance(self) -> float:
        r = self._call(action="getBalance")
        m = re.search(r"ACCESS_BALANCE:([\d.]+)", r)
        return float(m.group(1)) if m else 0.0

    def buy(self, service: str = "gr", country: int = 52) -> dict:
        r = self._call(action="getNumber", service=service, country=country)
        if "BAD_" in r or "NO_" in r:
            raise SMSActivateError(r)
        m = re.match(r"ACCESS_NUMBER:(\d+):(\d+)", r)
        if not m:
            raise SMSActivateError(f"Format inattendu: {r}")
        return {
            "id":       int(m.group(1)),
            "phone":    "+" + m.group(2),
            "service":  service,
            "country":  country,
            "_provider": "smsactivate",
        }

    def check(self, order_id: int) -> dict:
        r = self._call(action="getStatus", id=order_id)
        if "STATUS_WAIT" in r:
            return {"status": "waiting", "code": None}
        if "STATUS_CANCEL" in r:
            return {"status": "canceled", "code": None}
        m = re.match(r"STATUS_OK:(.+)", r)
        if m:
            return {"status": "received", "code": m.group(1).strip()}
        return {"status": "unknown", "code": None, "raw": r}

    def cancel(self, order_id: int):
        try:
            self._call(action="setStatus", id=order_id, status=8)
        except SMSActivateError:
            pass

    def wait_otp(self, order_id: int, timeout: int = 120, poll: int = 5) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.check(order_id)
            if d["status"] == "received" and d["code"]:
                code = re.search(r"\b(\d{4,8})\b", d["code"])
                return code.group(1) if code else d["code"]
            if d["status"] == "canceled":
                raise SMSActivateError(f"Commande {order_id} annulée")
            time.sleep(poll)
        self.cancel(order_id)
        raise SMSActivateError(f"Timeout {timeout}s — OTP non reçu")


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    USAGE = """Usage:
  python3 sms_otp.py herosms  CLE balance
  python3 sms_otp.py herosms  CLE buy [service=gr] [country=52]
  python3 sms_otp.py herosms  CLE wait ORDER_ID [timeout=120]
  python3 sms_otp.py smspool  CLE balance
  python3 sms_otp.py smspool  CLE buy
  python3 sms_otp.py smspool  CLE wait ORDER_ID [timeout=120]

Exemples :
  python3 sms_otp.py herosms  abc123 balance
  python3 sms_otp.py herosms  abc123 buy gr 52
  python3 sms_otp.py smspool  xyz789 balance
  python3 sms_otp.py smspool  xyz789 buy"""

    if len(sys.argv) < 4:
        print(USAGE)
        sys.exit(1)

    provider = sys.argv[1].lower()
    api_key  = sys.argv[2]
    action   = sys.argv[3].lower()
    extra    = sys.argv[4:]

    if provider == "herosms":
        client = HeroSMS(api_key)
        ErrCls = HeroSMSError
    elif provider == "smspool":
        client = SMSPool(api_key)
        ErrCls = SMSPoolError
    elif provider == "smsactivate":
        client = SMSActivate(api_key)
        ErrCls = SMSActivateError
    else:
        print(f"Provider inconnu: {provider}  (herosms / smspool / smsactivate)")
        sys.exit(1)

    try:
        if action == "balance":
            bal = client.balance()
            symbol = "$" if provider == "smspool" else "€"
            print(f"Solde {provider}: {symbol}{bal:.2f}")

        elif action == "buy":
            if provider == "smspool":
                order = client.buy_grab()
            else:
                svc     = extra[0] if extra else "gr"
                country = int(extra[1]) if len(extra) > 1 else 52
                order   = client.buy(svc, country)
            print(f"Numéro acheté: {order['phone']}")
            print(f"ID commande  : {order['id']}")
            print(f"Pour attendre l'OTP: python3 sms_otp.py {provider} {api_key} wait {order['id']}")

        elif action == "wait":
            if not extra:
                print("Erreur: préciser ORDER_ID")
                sys.exit(1)
            order_id = extra[0]
            timeout  = int(extra[1]) if len(extra) > 1 else 120
            print(f"Attente OTP pour commande {order_id} (max {timeout}s)…")
            if provider == "herosms":
                order_id = int(order_id)
            code = client.wait_otp(order_id, timeout=timeout)
            print(f"OTP recu: {code}")

        else:
            print(f"Action inconnue: {action}")
            print(USAGE)
            sys.exit(1)

    except (HeroSMSError, SMSPoolError, SMSActivateError) as e:
        print(f"Erreur {provider}: {e}")
        sys.exit(1)
