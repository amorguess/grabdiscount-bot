"""
5sim.net API client — numéros virtuels thaïlandais pour Grab
Accepte les cartes Visa/Mastercard européennes via Stripe ✅
Inscription : https://5sim.net → Profil → API Token
"""
import time, re, requests

BASE = "https://5sim.net/v1"

class FiveSimError(Exception):
    pass

class FiveSim:
    def __init__(self, api_key: str):
        self.key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept":        "application/json",
        })

    def _get(self, path: str, **kwargs):
        r = self.session.get(f"{BASE}{path}", timeout=15, **kwargs)
        if r.status_code == 401:
            raise FiveSimError("Clé API invalide ou expirée")
        if r.status_code == 400:
            try:
                msg = r.json().get("message", r.text[:200])
            except:
                msg = r.text[:200]
            raise FiveSimError(f"Erreur 400: {msg}")
        if not r.ok:
            raise FiveSimError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    # ── Solde ───────────────────────────────────────────────
    def balance(self) -> float:
        d = self._get("/user/profile")
        return float(d.get("balance", 0))

    # ── Stock disponible pour Grab Thaïlande ────────────────
    def stock_grab_thailand(self) -> dict:
        """Retourne les opérateurs/stocks dispo pour grab en Thaïlande."""
        try:
            return self._get("/guest/products/thailand/any")
        except:
            return {}

    # ── Acheter un numéro ───────────────────────────────────
    def buy(self, country: str = "thailand", operator: str = "any",
            service: str = "grab") -> dict:
        """Achète un numéro virtuel. Retourne le dict order 5sim."""
        return self._get(f"/user/buy/activation/{country}/{operator}/{service}")

    # ── Vérifier statut d'un order ──────────────────────────
    def check(self, order_id: int) -> dict:
        return self._get(f"/user/check/{order_id}")

    # ── Annuler ─────────────────────────────────────────────
    def cancel(self, order_id: int):
        try:
            self._get(f"/user/cancel/{order_id}")
        except: pass

    # ── Terminer (confirmer réception) ──────────────────────
    def finish(self, order_id: int):
        try:
            self._get(f"/user/finish/{order_id}")
        except: pass

    # ── Poll jusqu'à réception du SMS ──────────────────────
    def wait_sms(self, order_id: int, timeout: int = 120, poll: int = 5) -> str:
        """
        Poll toutes les `poll` secondes.
        Retourne le CODE OTP (string) — interface compatible SMS-Activate.
        Lève FiveSimError si timeout ou annulation.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.check(order_id)
            status = d.get("status", "")

            if status == "RECEIVED":
                # Extraire le code depuis le champ "sms"
                sms_list = d.get("sms", [])
                if sms_list:
                    raw_text = sms_list[-1].get("text", "")
                    # Extraire les chiffres (code OTP)
                    code = re.search(r"\b(\d{4,8})\b", raw_text)
                    if code:
                        self.finish(order_id)
                        return code.group(1)
                    # Si pas de regex match, retourner le texte brut
                    self.finish(order_id)
                    return raw_text
                raise FiveSimError(f"SMS reçu mais vide pour order {order_id}")

            if status in ("CANCELED", "TIMEOUT", "BANNED"):
                raise FiveSimError(f"Order {order_id} terminé avec statut: {status}")

            time.sleep(poll)

        self.cancel(order_id)
        raise FiveSimError(f"Timeout ({timeout}s) — aucun SMS reçu pour order {order_id}")

    # ── Achat Grab avec fallback services ──────────────────
    def buy_for_grab(self, country: str = "thailand") -> dict:
        """
        Achète un numéro compatible Grab.
        Essaie "grab" puis "other" en fallback.
        Retourne un dict avec id, phone (format +66XXXXXXXXX).
        """
        services = ["grab", "grabfood", "other"]
        last_err = None

        for svc in services:
            try:
                order = self.buy(country=country, operator="any", service=svc)
                # Normaliser le format du numéro pour compatibilité avec le reste
                phone = order.get("phone", "")
                if not phone.startswith("+"):
                    phone = "+" + phone
                return {
                    "id":       order["id"],
                    "phone":    phone,
                    "service":  svc,
                    "country":  country,
                    "_provider": "5sim",
                    "_raw":     order,
                }
            except FiveSimError as e:
                last_err = e
                if "not found" in str(e).lower() or "no product" in str(e).lower():
                    continue
                raise

        raise FiveSimError(
            f"Aucun numéro Grab dispo en {country}: {last_err}"
        )


# ── Test standalone ────────────────────────────────────────
if __name__ == "__main__":
    import sys, json

    if len(sys.argv) < 2:
        print("Usage: python3 fivesim.py API_KEY [buy]")
        print()
        print("Inscription et recharge : https://5sim.net")
        print("→ Carte Visa/Mastercard européenne acceptée via Stripe ✅")
        sys.exit(1)

    key    = sys.argv[1]
    client = FiveSim(key)

    bal = client.balance()
    print(f"💰 Solde : {bal:.4f} $")

    print("\n📦 Stock Grab Thaïlande :")
    stock = client.stock_grab_thailand()
    grab  = stock.get("grab", {})
    if grab:
        qty = grab.get("Qty", "?")
        price = grab.get("Price", "?")
        print(f"   grab → {qty} numéros dispo @ {price}$")
    else:
        print("   (aucun stock 'grab' visible)")
        for k, v in list(stock.items())[:5]:
            print(f"   {k} → {v}")

    if len(sys.argv) > 2 and sys.argv[2] == "buy":
        if bal < 0.05:
            print("\n⚠️  Solde insuffisant — recharge sur https://5sim.net")
            sys.exit(1)
        print("\n🛒 Achat numéro Grab Thaïlande...")
        try:
            order = client.buy_for_grab("thailand")
            print(f"  ✅ Numéro  : {order['phone']}")
            print(f"  🆔 Order   : {order['id']}")
            print(f"\n⏳ Attente OTP (90s)...")
            code = client.wait_sms(order["id"], timeout=90)
            print(f"  ✅ OTP : {code}")
        except FiveSimError as e:
            print(f"  ❌ {e}")
