"""
Identifier generation for runs and records.

Import as:

import operant.helpers.ids as ids
"""

from __future__ import annotations

import re
import secrets
from typing import Final

import operant.domain.errors as errors
import operant.helpers.time as time

# A record id names a file or directory, so it is one plain path segment.
KEY_PATTERN: Final[str] = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_KEY_RE: Final[re.Pattern[str]] = re.compile(KEY_PATTERN)


def run_id(kind: str) -> str:
    """
    Build a sortable run identifier such as ``replay-20260823-041118``.

    A short random suffix keeps two runs started in the same second
    apart.

    :param kind: the run kind, e.g. ``"discovery"`` or ``"replay"``.
    :return: the identifier.
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


def checked_key(key: str) -> str:
    """
    Return ``key`` when it is safe to use as one file-name segment.

    :param key: a capability, graph or profile id.
    :return: the same key.
    :raises errors.InvalidIdError: when it holds a path separator,
        starts with a dot, or uses other characters.
    """
    if not _KEY_RE.fullmatch(key):
        raise errors.InvalidIdError(
            f"Id '{key}' must be letters, digits, '.', '_' or '-'"
        )
    return key
