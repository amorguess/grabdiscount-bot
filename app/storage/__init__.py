"""Storage: accès aux données (JSON actuellement, SQLite à terme).

Phase 2 extraira ici:
- JSONStore (atomic write + flock + mtime cache)
- AccountsStore, OrdersStore, SubscribersStore, MessagesStore
"""
