"""MessagesStore — accès typé à messages.json.

Shape : `{"<user_id>": {"name": ..., "username": ..., "messages": [...], "unread": N}}`

Note : le champ `from` dans chaque message est un mot réservé Python. On le
stocke tel quel dans le JSON (`{"from": "admin"}`) mais les helpers exposent
`author` pour rester pythoniques.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from app.storage import paths
from app.storage.base import JSONStore
from app.storage.models import TS_FMT, ThreadRecord

Author = Literal["client", "admin"]


class MessagesStore:
    """Opérations métier sur messages.json."""

    __slots__ = ("_store",)

    def __init__(self, data_dir: Path) -> None:
        self._store: JSONStore[dict[str, ThreadRecord]] = JSONStore(data_dir / paths.MESSAGES, default=dict, indent=2)

    # ─── Lecture ──────────────────────────────────────────────────────

    def all_threads(self) -> dict[str, ThreadRecord]:
        return dict(self._store.read())

    def get_thread(self, user_id: int) -> ThreadRecord | None:
        return self._store.read().get(str(user_id))

    def list_messages(self, user_id: int) -> list[dict]:
        t = self.get_thread(user_id)
        return list(t.get("messages") or []) if t else []

    def unread_total(self) -> int:
        """Total des messages non-lus sur tous les threads."""
        return sum(int(t.get("unread") or 0) for t in self._store.read().values())

    def threads_with_unread(self) -> list[tuple[str, ThreadRecord]]:
        """Threads triés par volume de non-lus décroissant."""
        items = [(uid, t) for uid, t in self._store.read().items() if int(t.get("unread") or 0) > 0]
        items.sort(key=lambda kv: int(kv[1].get("unread") or 0), reverse=True)
        return items

    # ─── Écriture ─────────────────────────────────────────────────────

    def append(
        self,
        user_id: int,
        *,
        text: str,
        author: Author,
        name: str = "",
        username: str = "",
        read: bool | None = None,
    ) -> dict:
        """Ajoute un message au thread. Crée le thread s'il n'existe pas.

        - Message client → `unread += 1` (par défaut)
        - Message admin → n'incrémente pas (l'admin lit quand il écrit)
        - `read=True` force le message comme déjà lu.
        """
        now = datetime.now()
        ts = now.strftime(TS_FMT)
        heure = now.strftime("%d/%m/%Y à %H:%M")

        record = {
            "text": text,
            "ts": ts,
            "heure": heure,
            "from": author,
            "read": read if read is not None else (author == "admin"),
        }
        key = str(user_id)

        def _mutator(data: dict[str, ThreadRecord]) -> dict[str, ThreadRecord]:
            thread = data.get(key, {"name": name, "username": username, "messages": [], "unread": 0})
            if name and not thread.get("name"):
                thread["name"] = name
            if username and not thread.get("username"):
                thread["username"] = username
            messages = list(thread.get("messages") or [])
            messages.append(record)
            thread["messages"] = messages
            if author == "client" and not record["read"]:
                thread["unread"] = int(thread.get("unread") or 0) + 1
            data[key] = thread
            return data

        self._store.mutate(_mutator)
        return record

    def mark_thread_read(self, user_id: int) -> bool:
        """Passe unread à 0 + read=True sur tous les messages du thread."""
        key = str(user_id)
        found = {"v": False}

        def _mutator(data: dict[str, ThreadRecord]) -> dict[str, ThreadRecord]:
            if key not in data:
                return data
            thread = data[key]
            for m in thread.get("messages") or []:
                m["read"] = True
            thread["unread"] = 0
            found["v"] = True
            return data

        self._store.mutate(_mutator)
        return found["v"]

    def delete_thread(self, user_id: int) -> bool:
        """Supprime un thread complet. Retourne True si trouvé."""
        key = str(user_id)
        found = {"v": False}

        def _mutator(data: dict[str, ThreadRecord]) -> dict[str, ThreadRecord]:
            if key in data:
                del data[key]
                found["v"] = True
            return data

        self._store.mutate(_mutator)
        return found["v"]

    @property
    def store(self) -> JSONStore[dict[str, ThreadRecord]]:
        return self._store
