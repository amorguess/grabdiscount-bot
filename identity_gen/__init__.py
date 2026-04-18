"""
identity_gen — Générateur d'identités françaises + adresses Bangkok
"""
from .bangkok_addresses import get_bangkok_address, get_all_addresses, BANGKOK_ADDRESSES
from .identities import generate_identity, generate_batch

__all__ = [
    "get_bangkok_address",
    "get_all_addresses",
    "BANGKOK_ADDRESSES",
    "generate_identity",
    "generate_batch",
]
