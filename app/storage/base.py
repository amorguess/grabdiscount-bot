"""JSONStore — accès atomique et thread-safe à un fichier JSON.

Design :

1. **Lecture** : cache en RAM invalidé sur `mtime` — tant que le fichier n'a
   pas changé sur disque, on sert la valeur cachée.
2. **Écriture** : write-to-tmp + `os.replace` (atomic rename POSIX) + `fsync`
   pour garantir la durabilité. Le verrou `fcntl.flock` évite les écritures
   concurrentes entre processus (dashboard + bot).
3. **Transaction** : `mutate()` lit → applique une fonction → écrit, le tout
   sous verrou. Garantie qu'aucun autre writer ne s'intercale.
4. **Corruption** : si le JSON est illisible, lève `StorageCorruptError` —
   jamais un silent `{}` qui effacerait des données.
5. **Thread-safety** : un lock `threading.RLock` en plus du flock protège
   contre les accès concurrents dans le même processus.

Usage :

    store = JSONStore[dict](path, default=dict)
    data = store.read()
    store.write({"foo": "bar"})
    store.mutate(lambda d: {**d, "counter": d.get("counter", 0) + 1})
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.core.exceptions import StorageCorruptError, StorageError, StorageLockTimeout
from app.core.logging import get_logger

T = TypeVar("T")

_LOG = get_logger(__name__)

_LOCK_POLL_INTERVAL = 0.05


class JSONStore(Generic[T]):
    """Accès atomique à un fichier JSON typé.

    Args:
        path: chemin absolu du fichier.
        default: factory appelée si le fichier n'existe pas encore.
        lock_timeout: délai max (secondes) pour acquérir le verrou fichier.
        indent: indentation du JSON écrit (None = compact, meilleure perf).
    """

    __slots__ = ("_path", "_default", "_lock_timeout", "_indent", "_thread_lock", "_cache", "_cache_mtime")

    def __init__(
        self,
        path: Path | str,
        *,
        default: Callable[[], T],
        lock_timeout: float = 5.0,
        indent: int | None = None,
    ) -> None:
        self._path = Path(path)
        self._default = default
        self._lock_timeout = lock_timeout
        self._indent = indent
        self._thread_lock = threading.RLock()
        self._cache: T | None = None
        self._cache_mtime: float | None = None

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> T:
        """Lit le fichier (ou retourne `default()` si absent).

        Utilise un cache mtime : pas de re-parse si le fichier n'a pas bougé.
        Jamais de modification directe du retour — copiez avant de muter, ou
        utilisez `mutate()`.
        """
        with self._thread_lock:
            try:
                mtime = self._path.stat().st_mtime
            except FileNotFoundError:
                if self._cache is None:
                    self._cache = self._default()
                    self._cache_mtime = None
                return self._cache

            if self._cache is not None and self._cache_mtime == mtime:
                return self._cache

            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                raise StorageCorruptError(f"{self._path} contient du JSON invalide: {e}") from e
            except OSError as e:
                raise StorageError(f"Lecture {self._path} impossible: {e}") from e

            self._cache = data  # type: ignore[assignment]
            self._cache_mtime = mtime
            return self._cache  # type: ignore[return-value]

    def write(self, data: T) -> None:
        """Écrit atomiquement `data` dans le fichier.

        Séquence :
        1. Acquiert le flock (inter-processus).
        2. Écrit dans un fichier temporaire du même répertoire.
        3. `fsync` puis `os.replace` atomique.
        4. Invalide le cache.
        """
        with self._thread_lock, self._file_lock():
            self._write_locked(data)

    def mutate(self, fn: Callable[[T], T]) -> T:
        """Lit → transforme via `fn` → écrit, sous verrou.

        Garantit qu'aucun autre writer ne s'intercale entre read et write.
        Retourne la nouvelle valeur.
        """
        with self._thread_lock, self._file_lock():
            current = self._read_locked()
            new = fn(current)
            self._write_locked(new)
            return new

    def invalidate_cache(self) -> None:
        """Vide le cache RAM (usage: tests, ou après modif externe connue)."""
        with self._thread_lock:
            self._cache = None
            self._cache_mtime = None

    # ─── internes ─────────────────────────────────────────────────────

    def _read_locked(self) -> T:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return self._default()
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise StorageCorruptError(f"{self._path} contient du JSON invalide: {e}") from e
        self._cache = data  # type: ignore[assignment]
        self._cache_mtime = mtime
        return data  # type: ignore[return-value]

    def _write_locked(self, data: T) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=self._indent)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self._path)
        except Exception:
            # Nettoie le tmp si quelque chose a foiré avant le replace
            with _suppress(OSError):
                os.unlink(tmp_name)
            raise
        try:
            self._cache = data
            self._cache_mtime = self._path.stat().st_mtime
        except OSError as e:
            _LOG.warning("stat après write échoué: %s", e)
            self.invalidate_cache()

    def _file_lock(self) -> _FileLock:
        return _FileLock(self._path, self._lock_timeout)


class _FileLock:
    """Verrou fichier exclusif via fcntl.flock, avec timeout."""

    __slots__ = ("_path", "_timeout", "_fd", "_lock_path")

    def __init__(self, target: Path, timeout: float) -> None:
        self._path = target
        self._timeout = timeout
        self._fd: int | None = None
        self._lock_path = target.parent / f".{target.name}.lock"

    def __enter__(self) -> _FileLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise StorageLockTimeout(f"Verrou {self._lock_path} indisponible après {self._timeout}s") from None
                time.sleep(_LOCK_POLL_INTERVAL)

    def __exit__(self, *exc: Any) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class _suppress:
    """Minimal contextlib.suppress pour éviter l'import."""

    __slots__ = ("_exc",)

    def __init__(self, exc: type[BaseException]) -> None:
        self._exc = exc

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, self._exc)
