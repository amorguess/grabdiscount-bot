"""AccountsStore — accès typé à accounts.json.

Les comptes sont stockés en liste (ordre chronologique d'ajout conservé).
La clef d'unicité est `email`.

Business rules encapsulées ici :
- `claim_next_full()` : assignation atomique d'un compte à une commande.
  L'utilisation de `JSONStore.mutate()` garantit qu'aucun autre process ne
  peut réserver le même compte en simultané.
- `mark_used()` : passage en état terminal (used), trace `used_at`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.exceptions import NotFoundError
from app.storage import paths
from app.storage.base import JSONStore
from app.storage.models import TS_FMT, AccountRecord, AccountStatus


class AccountsStore:
    """Opérations métier sur accounts.json."""

    __slots__ = ("_store",)

    def __init__(self, data_dir: Path) -> None:
        self._store: JSONStore[list[AccountRecord]] = JSONStore(data_dir / paths.ACCOUNTS, default=list, indent=2)

    # ─── Lecture ──────────────────────────────────────────────────────

    def all(self) -> list[AccountRecord]:
        """Tous les comptes (copie défensive)."""
        return list(self._store.read())

    def get(self, email: str) -> AccountRecord | None:
        for a in self._store.read():
            if a.get("email") == email:
                return a
        return None

    def by_status(self, status: AccountStatus | str) -> list[AccountRecord]:
        wanted = str(status)
        return [a for a in self._store.read() if a.get("status") == wanted]

    def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self._store.read():
            s = a.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return counts

    # ─── Écriture ─────────────────────────────────────────────────────

    def add(self, record: AccountRecord) -> AccountRecord:
        """Ajoute un compte. Lève si email déjà présent."""
        email = record.get("email")
        if not email:
            raise ValueError("record sans email")

        def _mutator(data: list[AccountRecord]) -> list[AccountRecord]:
            if any(a.get("email") == email for a in data):
                raise ValueError(f"compte {email} déjà présent")
            new = [*data, record]
            return new

        self._store.mutate(_mutator)
        return record

    def update(self, email: str, **fields: object) -> AccountRecord:
        """Met à jour les champs d'un compte. Retourne l'enregistrement modifié."""

        def _mutator(data: list[AccountRecord]) -> list[AccountRecord]:
            for a in data:
                if a.get("email") == email:
                    a.update(fields)  # type: ignore[typeddict-item]
                    return data
            raise NotFoundError(f"compte {email} introuvable")

        self._store.mutate(_mutator)
        found = self.get(email)
        assert found is not None
        return found

    def claim_next_full(self) -> AccountRecord | None:
        """Assigne atomiquement le prochain compte `full` à une commande.

        Passe `full → en_cours` en une seule transaction. Renvoie le compte
        assigné ou None si aucun disponible.
        """
        claimed: dict[str, AccountRecord] = {}

        def _mutator(data: list[AccountRecord]) -> list[AccountRecord]:
            for a in data:
                if a.get("status") == AccountStatus.FULL.value:
                    a["status"] = AccountStatus.EN_COURS.value
                    a["_locked_at"] = datetime.now().strftime(TS_FMT)
                    claimed["rec"] = a
                    return data
            return data

        self._store.mutate(_mutator)
        return claimed.get("rec")

    def mark_used(self, email: str) -> AccountRecord:
        """Passe un compte de `en_cours` à `used` (état terminal)."""
        now = datetime.now().strftime(TS_FMT)
        return self.update(email, status=AccountStatus.USED.value, used_at=now)

    def release(self, email: str, to_status: AccountStatus = AccountStatus.FULL) -> AccountRecord:
        """Relâche un compte (erreur commande → remet en `full`)."""
        return self.update(email, status=to_status.value, _locked_at=None)

    def remove(self, email: str) -> bool:
        """Supprime un compte définitivement. Retourne True si trouvé."""
        found = {"v": False}

        def _mutator(data: list[AccountRecord]) -> list[AccountRecord]:
            filtered = [a for a in data if a.get("email") != email]
            if len(filtered) != len(data):
                found["v"] = True
            return filtered

        self._store.mutate(_mutator)
        return found["v"]

    @property
    def store(self) -> JSONStore[list[AccountRecord]]:
        """Accès bas niveau — usage restreint (tests, debug)."""
        return self._store
