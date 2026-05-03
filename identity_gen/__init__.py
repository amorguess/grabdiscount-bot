"""
identity_gen — Identités françaises + adresses Bangkok / Australie / France
"""
from .bangkok_addresses import get_bangkok_address, get_all_addresses, BANGKOK_ADDRESSES
from .australia_addresses import (
    get_australia_address,
    get_all_australia_addresses,
    AUSTRALIA_ADDRESSES,
)
from .france_addresses import (
    get_france_address,
    get_all_france_addresses,
    FRANCE_ADDRESSES,
)
from .identities import generate_identity, generate_batch

__all__ = [
    "get_bangkok_address",
    "get_all_addresses",
    "BANGKOK_ADDRESSES",
    "get_australia_address",
    "get_all_australia_addresses",
    "AUSTRALIA_ADDRESSES",
    "get_france_address",
    "get_all_france_addresses",
    "FRANCE_ADDRESSES",
    "generate_identity",
    "generate_batch",
]
