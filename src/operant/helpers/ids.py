"""
Identifier generation for runs and records.

Import as:

import operant.helpers.ids as ids
"""

from __future__ import annotations

import secrets

import operant.helpers.time as time


def run_id(kind: str) -> str:
    """
    Build a sortable run identifier such as ``replay-20260823-041118``.

    A short random suffix keeps two runs started in the same second
    apart.

    :param kind: The run kind, e.g. ``"discovery"`` or ``"replay"``.
    :return: The identifier.
    """
    identifier = f"{kind}-{time.timestamp_slug()}-{secrets.token_hex(2)}"
    return identifier


def nonce(num_bytes: int = 16) -> str:
    """
    Return a URL-safe single-use token.
    """
    token = secrets.token_urlsafe(num_bytes)
    return token


def short_id(prefix: str, num_bytes: int = 4) -> str:
    """
    Return ``prefix-<hex>`` for records that need a compact unique id.
    """
    identifier = f"{prefix}-{secrets.token_hex(num_bytes)}"
    return identifier
