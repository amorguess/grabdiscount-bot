"""
icloud_hme.py — Générateur d'emails iCloud Hide My Email (HME)
==============================================================
Fichier autonome. Dépendances: aiohttp, certifi (pip install aiohttp certifi).
Réutilisable dans n'importe quel projet Python 3.8+.

Apple HME = adresses alias @icloud.com qui redirigent vers votre Apple ID.
Chaque alias reçoit les emails séparément (OTP par alias possible).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBTENIR LES COOKIES APPLE (requis)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Ouvrir Chrome et aller sur https://www.icloud.com
2. Se connecter avec son Apple ID
3. F12 → Application → Cookies → https://www.icloud.com
4. Cliquer "Copy all as header value" (clic droit sur les cookies)
   OU: ouvrir l'onglet Network, recharger la page,
       chercher une requête vers icloud.com,
       dans Request Headers, copier la ligne "cookie: ..."
5. Coller dans COOKIE_FILE ou passer en paramètre

Limite Apple : ~5 emails par session, ~25/jour par compte.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Usage en bibliothèque :
    from icloud_hme import ICloudHME
    hme = ICloudHME("cookie.txt")   # fichier contenant les cookies
    emails = hme.generate(5)         # liste de strings @icloud.com

Usage CLI :
    python3 icloud_hme.py 5                    # génère 5 emails (lit cookie.txt)
    python3 icloud_hme.py 10 --cookie=mon_cookie.txt
    python3 icloud_hme.py list                 # liste les HME existants
"""
import asyncio
import ssl
import os
import sys
import json
import datetime

try:
    import aiohttp
    import certifi
except ImportError:
    print("Dépendances manquantes. Installer avec:")
    print("  pip install aiohttp certifi")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
#  FICHIER COOKIE PAR DÉFAUT
# ─────────────────────────────────────────────────────────────────
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icloud_cookie.txt")


class ICloudHMEError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────
#  CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────
class ICloudHME:
    """
    Générateur d'emails iCloud Hide My Email via l'API iCloud officielle.

    Attributs:
        cookies (str): Chaîne de cookies Apple (depuis le navigateur).
        label   (str): Label attribué aux emails générés.

    Exemple:
        hme    = ICloudHME.from_file("cookie.txt")
        emails = hme.generate(5)
        print(emails)  # ['abc.def1a@icloud.com', ...]
    """

    BASE_V1 = "https://p68-maildomainws.icloud.com/v1/hme"
    BASE_V2 = "https://p68-maildomainws.icloud.com/v2/hme"
    PARAMS  = {
        "clientBuildNumber":   "2413Project28",
        "clientMasteringNumber": "2413B20",
        "clientId": "",
        "dsid": "",
    }

    def __init__(self, cookies: str, label: str = "Generated"):
        """
        Args:
            cookies: Chaîne de cookies complète (depuis Chrome DevTools).
            label:   Label Apple pour les emails générés.
        """
        self.cookies = cookies.strip()
        self.label   = label

    @classmethod
    def from_file(cls, path: str = COOKIE_FILE, label: str = "Generated") -> "ICloudHME":
        """
        Crée une instance depuis un fichier contenant les cookies.

        Args:
            path:  Chemin vers le fichier cookie (une ligne, texte brut).
            label: Label Apple pour les emails.

        Returns:
            Instance ICloudHME.

        Raises:
            ICloudHMEError: Si le fichier est introuvable ou vide.
        """
        if not os.path.exists(path):
            raise ICloudHMEError(
                f"Fichier cookie introuvable: {path}\n"
                "Copier les cookies depuis Chrome DevTools (icloud.com) et les coller dans ce fichier."
            )
        with open(path, encoding="utf-8") as f:
            cookies = f.read().strip()
        if not cookies:
            raise ICloudHMEError(f"Fichier cookie vide: {path}")
        return cls(cookies, label)

    def _make_session(self) -> aiohttp.ClientSession:
        ssl_ctx   = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl_context=ssl_ctx)
        return aiohttp.ClientSession(
            headers={
                "Connection":      "keep-alive",
                "Cache-Control":   "no-cache",
                "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/123.0.0.0 Safari/537.36",
                "Content-Type":    "text/plain",
                "Accept":          "*/*",
                "Origin":          "https://www.icloud.com",
                "Referer":         "https://www.icloud.com/",
                "Accept-Language": "en-US,en-GB;q=0.9,en;q=0.8",
                "Cookie":          self.cookies,
            },
            timeout=aiohttp.ClientTimeout(total=15),
            connector=connector,
        )

    async def _generate_one(self, session: aiohttp.ClientSession) -> str | None:
        """Génère et réserve un email HME. Retourne l'adresse ou None."""
        # 1. Générer
        try:
            async with session.post(
                f"{self.BASE_V1}/generate",
                params=self.PARAMS,
                json={"langCode": "en-us"},
            ) as resp:
                gen = await resp.json()
        except Exception as e:
            raise ICloudHMEError(f"Erreur génération: {e}")

        if not gen.get("success"):
            err = gen.get("error", {})
            msg = err.get("errorMessage") if isinstance(err, dict) else gen.get("reason", str(gen))
            raise ICloudHMEError(f"Génération échouée: {msg}")

        email = gen["result"]["hme"]

        # 2. Réserver (active l'alias + configure le label)
        try:
            async with session.post(
                f"{self.BASE_V1}/reserve",
                params=self.PARAMS,
                json={"hme": email, "label": self.label, "note": ""},
            ) as resp:
                res = await resp.json()
        except Exception as e:
            raise ICloudHMEError(f"Erreur réservation: {e}")

        if not res.get("success"):
            err = res.get("error", {})
            msg = err.get("errorMessage") if isinstance(err, dict) else res.get("reason", str(res))
            raise ICloudHMEError(f"Réservation échouée pour {email}: {msg}")

        return email

    async def _generate_many(self, n: int, verbose: bool = True) -> list:
        """Génère n emails en parallèle (max 5 à la fois)."""
        results = []
        errors  = []

        async with self._make_session() as session:
            # Apple rate-limite — on fait des batches de 3 max
            batch_size = min(3, n)
            for i in range(0, n, batch_size):
                batch = range(i, min(i + batch_size, n))
                tasks = [self._generate_one(session) for _ in batch]
                for task in asyncio.as_completed(tasks):
                    try:
                        email = await task
                        results.append(email)
                        if verbose:
                            print(f"  ✅ {email}")
                    except ICloudHMEError as e:
                        errors.append(str(e))
                        if verbose:
                            print(f"  ❌ {e}")
                if i + batch_size < n:
                    await asyncio.sleep(1)   # petit délai entre batches

        if errors and not results:
            raise ICloudHMEError(f"Tous les emails ont échoué: {errors[0]}")

        return results

    def generate(self, n: int = 5, verbose: bool = True) -> list:
        """
        Génère n emails iCloud HME.

        Args:
            n:       Nombre d'emails à générer (recommandé: 1-5 par session).
            verbose: Affiche la progression.

        Returns:
            Liste de strings (adresses @icloud.com).

        Raises:
            ICloudHMEError: Si les cookies sont expirés ou Apple refuse.
        """
        return asyncio.run(self._generate_many(n, verbose))

    async def _list_emails(self, session: aiohttp.ClientSession) -> list:
        async with session.get(f"{self.BASE_V2}/list", params=self.PARAMS) as resp:
            d = await resp.json()
        if not d.get("success"):
            raise ICloudHMEError("Impossible de lister les HME — cookies expirés ?")
        return d.get("result", {}).get("hmeEmails", [])

    def list_emails(self) -> list:
        """
        Liste tous les emails HME du compte Apple.

        Returns:
            Liste de dicts {"hme": str, "label": str, "isActive": bool, ...}
        """
        async def _run():
            async with self._make_session() as s:
                return await self._list_emails(s)
        return asyncio.run(_run())

    def save_to_file(self, emails: list, path: str = "emails_generated.txt"):
        """Sauvegarde les emails générés dans un fichier texte."""
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n# {datetime.datetime.now():%Y-%m-%d %H:%M:%S} — {len(emails)} emails\n")
            for e in emails:
                f.write(e + "\n")
        print(f"  💾 {len(emails)} emails sauvegardés dans {path}")


# ─────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Générateur d'emails iCloud HME (Hide My Email)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("action", nargs="?", default="generate",
                        choices=["generate", "list"],
                        help="generate (défaut) ou list")
    parser.add_argument("count", nargs="?", type=int, default=5,
                        help="Nombre d'emails à générer (défaut: 5)")
    parser.add_argument("--cookie", default=COOKIE_FILE,
                        help=f"Fichier cookie (défaut: {COOKIE_FILE})")
    parser.add_argument("--label", default="Generated",
                        help="Label Apple (défaut: 'Generated')")
    parser.add_argument("--save", default="",
                        help="Sauvegarder les emails dans ce fichier")
    parser.add_argument("--quiet", action="store_true",
                        help="Mode silencieux")

    args = parser.parse_args()

    try:
        hme = ICloudHME.from_file(args.cookie, label=args.label)
    except ICloudHMEError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if args.action == "list":
        print("Liste des emails HME du compte...\n")
        try:
            emails_list = hme.list_emails()
            active   = [e for e in emails_list if e.get("isActive")]
            inactive = [e for e in emails_list if not e.get("isActive")]
            print(f"Total: {len(emails_list)} ({len(active)} actifs, {len(inactive)} inactifs)\n")
            for e in active[:50]:
                label = e.get("label", "—")
                addr  = e.get("hme", "?")
                print(f"  ✅ {addr:<40} [{label}]")
        except ICloudHMEError as err:
            print(f"❌ {err}")
            sys.exit(1)

    else:  # generate
        n = args.count
        print(f"\n🍎 Génération de {n} email(s) iCloud HME...\n")
        try:
            emails = hme.generate(n, verbose=not args.quiet)
            print(f"\n✅ {len(emails)}/{n} email(s) générés:")
            for e in emails:
                print(f"   {e}")
            if args.save:
                hme.save_to_file(emails, args.save)
        except ICloudHMEError as err:
            print(f"❌ {err}")
            print("\nSolution: renouveler les cookies dans le fichier cookie.")
            sys.exit(1)
