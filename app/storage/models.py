"""Types canoniques des enregistrements stockés.

On utilise `TypedDict` plutôt que `@dataclass` pour deux raisons :
1. Les JSON existants (accounts.json, messages.json) sont déjà des dicts —
   pas de sérialisation / désérialisation à gérer.
2. Les records legacy peuvent avoir des champs manquants ; `TypedDict`
   (`total=False`) documente la forme sans imposer la présence.

Les enums fournissent des constantes sans tomber dans la string-magic.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, TypedDict


class AccountStatus(StrEnum):
    """Cycle de vie d'un compte Grab."""

    AVAILABLE = "available"  # email HME + identité, pas encore de tél
    GRAB_READY = "grab_ready"  # tél ajouté, signup Grab fait
    FULL = "full"  # compte prêt à commander
    EN_COURS = "en_cours"  # assigné à une commande en cours
    USED = "used"  # commande faite, compte brûlé
    FAILED = "failed"  # signup Grab échoué


class Plan(StrEnum):
    """Plans d'abonnement (legacy starter conservé pour anciens comptes)."""

    STARTER = "starter"  # legacy — cap 20/mois
    PRO = "pro"  # VIP 20€/mois illimité (plan actuel)


class SubscriberStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    BLOCKED = "blocked"


# Timestamp format utilisé partout dans les JSON (ISO sans timezone).
TS_FMT = "%Y-%m-%dT%H:%M:%S"


class AccountRecord(TypedDict, total=False):
    """Compte Grab en stock dans accounts.json."""

    email: str
    status: str  # AccountStatus.value
    created: str
    used_at: str | None
    grab_notes: str
    grab_password: str
    grab_prenom: str
    grab_nom: str
    grab_name: str
    grab_phone: str
    grab_bangkok_addr: str
    phone_bought_at: str
    _locked_at: str | None
    _fail_count: int


class OrderRecord(TypedDict, total=False):
    """Commande client dans orders.json."""

    order_id: str
    user_id: int
    user_name: str
    user_username: str
    screenshot_path: str
    address: str
    account_email: str
    status: Literal["pending", "in_progress", "delivered", "cancelled"]
    created_at: str
    updated_at: str
    admin_note: str


class SubscriberRecord(TypedDict, total=False):
    """Abonné GrabDiscount dans subscribers.json.

    Forme documentée dans subscribers.py legacy — conservée à l'identique
    pour compat, mais typée ici.
    """

    user_id: int
    username: str
    name: str
    status: str  # SubscriberStatus.value
    plan: str  # Plan.value
    subscribed_at: str
    expires_at: str
    expired_at: str
    paused_until: str | None
    invite_link: str
    orders_count: int
    monthly_orders: int
    monthly_orders_month: str
    parrain_id: int | None
    filleuls: list[int]
    referral_credit_eur: int
    had_referral_discount: bool
    district: str | None
    source: str | None
    frequency_stated: str | None
    onboarded_at: str | None


class MessageRecord(TypedDict, total=False):
    """Un message individuel dans un thread."""

    text: str
    ts: str
    heure: str
    from_: str  # noqa: A003 -- "from" est un mot réservé Python
    read: bool


class ThreadRecord(TypedDict, total=False):
    """Thread de conversation avec un client (clef = user_id en str)."""

    name: str
    username: str
    messages: list[dict]  # list[MessageRecord] mais with "from" reserved keyword
    unread: int
