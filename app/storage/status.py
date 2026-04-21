"""StatusStore — `status.json` (disponibilité admin + pause).

Shape :
    `{"dispo": bool, "pause_until": str | None}`

- `dispo` : l'admin accepte-t-il des commandes ?
- `pause_until` : ISO timestamp de fin de pause (ou `None`).

Utilisé par le bot (refuse `/start` si !dispo ou pause en cours) et le
dashboard (toggle UI). `JSONStore` suffit — aucune logique métier complexe
au-delà du typage.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.storage import paths
from app.storage.base import JSONStore


class StatusRecord(TypedDict, total=False):
    dispo: bool
    pause_until: str | None


_DEFAULT: StatusRecord = {"dispo": True, "pause_until": None}


class StatusStore:
    """Accès typé à `status.json`."""

    __slots__ = ("_store",)

    def __init__(self, data_dir: Path) -> None:
        self._store: JSONStore[StatusRecord] = JSONStore(
            data_dir / paths.STATUS,
            default=lambda: dict(_DEFAULT),
            indent=2,
        )

    def read(self) -> StatusRecord:
        data = self._store.read()
        # Normalise : les anciens fichiers peuvent manquer `pause_until`.
        return {
            "dispo": bool(data.get("dispo", True)),
            "pause_until": data.get("pause_until"),
        }

    def is_dispo(self) -> bool:
        return bool(self.read().get("dispo", True))

    def set_dispo(self, dispo: bool) -> StatusRecord:
        def _m(d: StatusRecord) -> StatusRecord:
            d["dispo"] = bool(dispo)
            return d

        self._store.mutate(_m)
        return self.read()

    def set_pause(self, pause_until: str | None) -> StatusRecord:
        def _m(d: StatusRecord) -> StatusRecord:
            d["pause_until"] = pause_until
            return d

        self._store.mutate(_m)
        return self.read()

    @property
    def store(self) -> JSONStore[StatusRecord]:
        return self._store
