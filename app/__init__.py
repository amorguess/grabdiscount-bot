"""GrabDiscount — package principal.

Structure cible (Phase 2+):
- app.core        → config, logging, models, exceptions
- app.storage     → JSON/SQLite stores (accounts, orders, subscribers, messages)
- app.dashboard   → Flask blueprints (admin, employee, api)
- app.bot         → handlers Telegram (client, admin, shared)
- app.integrations → iCloud, SMSPool, Grab scraper, Wise

Phase 1: package vide, code legacy à la racine (bot.py, dashboard.py, subscribers.py).
"""

__version__ = "0.1.0"
