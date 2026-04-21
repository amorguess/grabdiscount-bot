"""Entry point pour le dashboard v2 (nouvelle archi `app/dashboard`).

Tourne en parallèle du `dashboard.py` legacy. L'app bind **127.0.0.1
uniquement** — nginx (avec le domaine `passfooddelivery.online`) est le
seul frontier exposé au net. UFW ferme déjà tout sauf 22/80/443 ; ce
binding local est la 2e couche de défense.

Usage :
    python run_dashboard_v2.py            # → 127.0.0.1:5002
    PORT=5003 python run_dashboard_v2.py  # port custom, toujours local

⚠ `HOST=0.0.0.0` est explicitement refusé — si tu en as besoin (debug
local depuis un autre device), utilise `HOST=127.0.0.1` via tunnel SSH
(`ssh -L 5002:localhost:5002 vps`).
"""

from __future__ import annotations

import os
import sys

from app.core.logging import configure_logging
from app.dashboard.app import create_app


def main() -> None:
    configure_logging()

    # `DASHBOARD_V2_HOST` / `DASHBOARD_V2_PORT` en priorité — évite les
    # collisions avec le legacy qui utilise `PORT` dans le même `.env`.
    host = os.environ.get("DASHBOARD_V2_HOST") or os.environ.get("HOST") or "127.0.0.1"
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"error: HOST={host!r} refusé — bind localhost only (nginx gère l'exposition).",
            file=sys.stderr,
        )
        sys.exit(2)

    raw_port = os.environ.get("DASHBOARD_V2_PORT") or "5002"
    port = int(raw_port)
    app = create_app()
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
