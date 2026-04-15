#!/usr/bin/env python3
"""
Générateur d'emails prêts à l'emploi
======================================
Génère N adresses email aléatoires sur des domaines jetables.
Pour chaque email, l'inbox est accessible sans inscription.

Usage :
  python3 generate_emails.py          → génère 10 emails (défaut)
  python3 generate_emails.py 25       → génère 25 emails
"""

import random, string, sys, os, datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
EMAILS_OUT = os.path.join(BASE_DIR, "emails.txt")

# Domaines jetables avec inbox accessible en ligne
DOMAINS = [
    ("yopmail.com",      "https://yopmail.com/en/?login={user}"),
    ("guerrillamail.com","https://www.guerrillamail.com/inbox?email={user}@guerrillamail.com"),
    ("mailnesia.com",    "https://mailnesia.com/mailbox/{user}"),
    ("sharklasers.com",  "https://www.guerrillamail.com/inbox?email={user}@sharklasers.com"),
    ("spam4.me",         "https://www.guerrillamail.com/inbox?email={user}@spam4.me"),
    ("trashmail.me",     "https://trashmail.me/?email={user}@trashmail.me"),
]

def random_user(length: int = 12) -> str:
    chars = string.ascii_lowercase + string.digits
    # Start with a letter
    return random.choice(string.ascii_lowercase) + "".join(random.choices(chars, k=length - 1))

def generate(n: int) -> list[tuple[str, str]]:
    """Returns list of (email, inbox_url)."""
    results = []
    for _ in range(n):
        domain, url_tpl = random.choice(DOMAINS)
        user  = random_user()
        email = f"{user}@{domain}"
        url   = url_tpl.format(user=user)
        results.append((email, url))
    return results

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    print(f"\n📧  Génération de {n} emails…\n")
    emails = generate(n)

    # Display
    print(f"  {'EMAIL':<38} INBOX (pour voir le code de vérif)")
    print("  " + "─" * 90)
    for email, url in emails:
        print(f"  {email:<38} {url}")
    print("  " + "─" * 90)

    # Save to emails.txt (append)
    with open(EMAILS_OUT, "a", encoding="utf-8") as f:
        f.write(f"\n# Batch {datetime.datetime.now():%d/%m/%Y %H:%M} — {n} emails\n")
        for email, url in emails:
            f.write(f"{email}\n")

    print(f"\n✅  {n} emails sauvegardés dans emails.txt")
    print(f"    Pour voir un inbox : copiez l'URL correspondante dans le navigateur\n")

if __name__ == "__main__":
    main()
