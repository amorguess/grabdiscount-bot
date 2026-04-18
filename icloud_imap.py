"""
icloud_imap.py — Lecture OTP Grab via IMAP iCloud
=================================================
Grab envoie parfois un code de vérification par email après l'OTP SMS.
Ce module poll la boîte iCloud HME via IMAP pour extraire ce code.

Configuration requise dans .env :
  ICLOUD_EMAIL=votreid@icloud.com   (Apple ID)
  ICLOUD_APPPASS=xxxx-xxxx-xxxx-xxxx  (mot de passe spécifique app)

Comment générer un app password :
  1. appleid.apple.com → Connexion
  2. Sécurité → Mots de passe spécifiques aux apps → Générer
  3. Copier dans .env → ICLOUD_APPPASS

Les emails HME (hide-my-email) sont transférés vers la boîte principale Apple ID.
"""
import imaplib, email, re, time, os
from email.header import decode_header

IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT   = 993

class ICloudIMAPError(Exception):
    pass

class ICloudIMAP:
    def __init__(self, apple_id: str = "", app_password: str = ""):
        self.user = apple_id    or os.environ.get("ICLOUD_EMAIL", "")
        self.pwd  = app_password or os.environ.get("ICLOUD_APPPASS", "")
        if not self.user or not self.pwd:
            raise ICloudIMAPError(
                "ICLOUD_EMAIL et ICLOUD_APPPASS requis dans .env\n"
                "Générer sur appleid.apple.com → Sécurité → Mots de passe spécifiques"
            )
        self._imap: imaplib.IMAP4_SSL | None = None

    def connect(self):
        self._imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        self._imap.login(self.user, self.pwd)
        return self

    def disconnect(self):
        try:
            if self._imap:
                self._imap.logout()
        except: pass
        self._imap = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.disconnect()

    def _decode_str(self, s) -> str:
        if isinstance(s, bytes):
            return s.decode("utf-8", errors="replace")
        parts = decode_header(s)
        return "".join(
            p.decode(enc or "utf-8") if isinstance(p, bytes) else p
            for p, enc in parts
        )

    def get_body(self, msg) -> str:
        """Extrait le corps texte d'un message email."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    try:
                        body += part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except: pass
        else:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
            except: pass
        return body

    def search_grab_otp(self, hme_email: str, timeout: int = 120, poll: int = 8) -> str:
        """
        Poll la boîte iCloud pendant `timeout` secondes.
        Cherche un email de Grab adressé à `hme_email` contenant un OTP.
        Retourne le code OTP (string).
        """
        if not self._imap:
            raise ICloudIMAPError("Non connecté — utiliser with ICloudIMAP() as imap:")

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._imap.select("INBOX")
                # Chercher emails non-lus de Grab
                _, data = self._imap.search(None,
                    '(UNSEEN FROM "grab")'
                )
                uids = data[0].split() if data[0] else []

                for uid in reversed(uids):  # plus récents en premier
                    _, msg_data = self._imap.fetch(uid, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    # Vérifier que le mail est pour notre HME
                    to_addr = self._decode_str(msg.get("To", "")).lower()
                    if hme_email.lower() not in to_addr:
                        continue

                    subject = self._decode_str(msg.get("Subject", "")).lower()
                    body    = self.get_body(msg)

                    # Chercher le code OTP (4-8 chiffres)
                    code = re.search(r"\b(\d{4,8})\b", subject + " " + body)
                    if code:
                        # Marquer comme lu
                        self._imap.store(uid, "+FLAGS", "\\Seen")
                        return code.group(1)

            except Exception as e:
                pass  # connexion IMAP peut être temporairement perdue

            time.sleep(poll)

        raise ICloudIMAPError(
            f"Timeout {timeout}s — OTP email non reçu pour {hme_email}\n"
            "Vérifier ICLOUD_EMAIL et ICLOUD_APPPASS dans .env"
        )


def wait_grab_email_otp(hme_email: str, timeout: int = 120) -> str:
    """
    Interface simple : attend l'OTP email Grab pour `hme_email`.
    Nécessite ICLOUD_EMAIL + ICLOUD_APPPASS dans .env
    """
    with ICloudIMAP() as imap:
        return imap.search_grab_otp(hme_email, timeout=timeout)


if __name__ == "__main__":
    # Test rapide
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 icloud_imap.py email@icloud.com")
        print("\nConfig requise dans .env :")
        print("  ICLOUD_EMAIL=votreid@icloud.com")
        print("  ICLOUD_APPPASS=xxxx-xxxx-xxxx-xxxx")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()
    target = sys.argv[1]
    print(f"🔍 Attente OTP email pour {target}…")
    try:
        code = wait_grab_email_otp(target, timeout=60)
        print(f"✅ OTP : {code}")
    except ICloudIMAPError as e:
        print(f"❌ {e}")
