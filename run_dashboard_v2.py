"""Entry point pour le dashboard v2 (nouvelle archi `app/dashboard`).

Tourne en parallèle du `dashboard.py` legacy, sur un port distinct, pour
validation zéro-risque. Une fois stable, on remplacera l'ancien.

Usage :
    python run_dashboard_v2.py
    PORT=5002 python run_dashboard_v2.py
"""

from __future__ import annotations

import os

from app.core.logging import configure_logging
from app.dashboard.app import create_app


def main() -> None:
    configure_logging()
    app = create_app()
    port = int(os.environ.get("PORT", "5002"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
