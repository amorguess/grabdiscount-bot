"""RestaurantsStore — accès lecture seule à restaurants.json.

Le fichier est produit par `restaurant_scraper.py` et peut peser ~20 MB.
On garde un cache RAM invalidé via mtime pour éviter de re-parser à chaque
requête API. Thread-safe (lecture atomique + dict swap).

Contrairement aux autres stores (JSONStore), celui-ci est **read-only** :
le fichier est régénéré par un script externe, pas muté par l'app.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.storage import paths


class RestaurantsStore:
    """Cache mémoire du fichier restaurants.json, invalidé sur mtime."""

    __slots__ = ("_path", "_lock", "_cache", "_cache_mtime")

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / paths.RESTAURANTS
        self._lock = threading.Lock()
        self._cache: list[dict[str, Any]] | None = None
        self._cache_mtime: float = 0.0

    def all(self) -> list[dict[str, Any]]:
        """Renvoie la liste complète (références partagées — ne pas muter)."""
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return []

        with self._lock:
            if self._cache is None or self._cache_mtime != mtime:
                try:
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return []
                self._cache = list(data.get("restaurants") or [])
                self._cache_mtime = mtime
            return self._cache

    def raw_bytes(self) -> bytes | None:
        """Payload brut pour le legacy endpoint `/api/restaurants`."""
        try:
            return self._path.read_bytes()
        except FileNotFoundError:
            return None
