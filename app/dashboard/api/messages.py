"""Endpoints messages client admin.

Routes :
- `GET /api/messages` : tous les threads
- `GET /api/messages/unread` : threads avec non-lus triés par volume
- `GET /api/messages/<user_id>` : messages d'un thread
- `POST /api/messages/<user_id>/read` : marque le thread comme lu
- `POST /api/messages/<user_id>/reply` : admin répond au client
  (ne pousse pas au bot Telegram — c'est le job d'un second service.
   Ici on ne fait qu'archiver dans messages.json.)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.dashboard.security import api_login_required
from app.dashboard.stores import get_stores

bp = Blueprint("messages", __name__, url_prefix="/api/messages")


@bp.get("")
@api_login_required
def list_threads() -> object:
    store = get_stores().messages
    return jsonify({"threads": store.all_threads(), "unread_total": store.unread_total()})


@bp.get("/unread")
@api_login_required
def unread_threads() -> object:
    threads = get_stores().messages.threads_with_unread()
    return jsonify(
        {
            "threads": [{"user_id": uid, **thread} for uid, thread in threads],
            "total": sum(int(t.get("unread") or 0) for _, t in threads),
        }
    )


@bp.get("/<int:user_id>")
@api_login_required
def get_thread(user_id: int) -> object:
    thread = get_stores().messages.get_thread(user_id)
    if thread is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"user_id": user_id, **thread})


@bp.post("/<int:user_id>/read")
@api_login_required
def mark_read(user_id: int) -> object:
    found = get_stores().messages.mark_thread_read(user_id)
    if not found:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True})


@bp.post("/<int:user_id>/reply")
@api_login_required
def reply(user_id: int) -> object:
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "missing_text"}), 400

    record = get_stores().messages.append(user_id, text=text, author="admin")
    return jsonify({"ok": True, "message": record})
