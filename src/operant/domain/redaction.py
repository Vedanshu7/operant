"""
Redaction of known secret values before anything is written.

The evidence logger and the recorder both pass through a ``Redactor``
seeded with every secret value known at runtime (environment secrets
plus values of inputs marked sensitive).

Typical usage example:

  redactor = redactor_from_env(os.environ)
  redactor.add_secret(password)
  safe = redactor.redact_deep(event_payload)

Import as:

import operant.domain.redaction as redact
"""

from __future__ import annotations

import collections.abc
import json
import re
from typing import Any, Final, List, Optional

_SECRET_ENV_RE: Final = re.compile(
    r"PASSWORD|SECRET|TOKEN|API_KEY", re.IGNORECASE
)
MASK: Final = "[REDACTED]"
# Shorter values would mask ordinary words.
MIN_SECRET_LENGTH: Final = 3


# #############################################################################
# Redactor
# #############################################################################


class Redactor:
    """
    Replace every registered secret value in text with a mask.

    Longer secrets are replaced first so a short secret that is a
    substring of a longer one cannot leave fragments behind.
    """

    def __init__(
        self, scrub: Optional[collections.abc.Callable[[str], str]] = None
    ) -> None:
        """
        Start with no secrets registered.

        :param scrub: Optional PII scrubber applied to every string leaf
            by ``redact_deep``, after exact masking.
        """
        self._secrets: List[str] = []
        self._scrub = scrub

    def add_secret(self, value: Optional[str]) -> None:
        """
        Register a value to mask; ignores empty and very short ones.

        :param value: The secret value, or ``None``.
        """
        if (
            value
            and len(value) >= MIN_SECRET_LENGTH
            and value not in self._secrets
        ):
            self._secrets.append(value)
            self._secrets.sort(key=len, reverse=True)

    def redact(self, text: str) -> str:
        """
        Mask every registered secret in the text.

        :param text: Text that may contain secret values.
        :return: The text with each secret replaced by ``[REDACTED]``.
        """
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text

    def redact_deep(self, value: Any) -> Any:
        """
        Mask secrets inside any JSON-serialisable structure.

        :param value: A structure of dicts, lists, and scalars; non-JSON
            values are stringified.
        :return: An equivalent structure with secrets masked.
        """
        restored = json.loads(self.redact(json.dumps(value, default=str)))
        if self._scrub is not None:
            # Scrub string leaves, never the JSON text, so a match can not
            # straddle a quote and break the structure.
            restored = _scrub_leaves(restored, self._scrub)
        return restored


def _scrub_leaves(value: Any, scrub: collections.abc.Callable[[str], str]) -> Any:
    """
    Apply ``scrub`` to every string inside a JSON structure.
    """
    if isinstance(value, str):
        # A leaf: scrub it.
        scrubbed: Any = scrub(value)
    elif isinstance(value, dict):
        # Keys stay as they are; only values carry screen text.
        scrubbed = {k: _scrub_leaves(v, scrub) for k, v in value.items()}
    elif isinstance(value, list):
        # Scrub each element in order.
        scrubbed = [_scrub_leaves(v, scrub) for v in value]
    else:
        # Numbers, booleans, and null carry no text.
        scrubbed = value
    return scrubbed


def redactor_from_env(
    environ: collections.abc.Mapping[str, str],
    *,
    scrub: Optional[collections.abc.Callable[[str], str]] = None,
) -> Redactor:
    """
    Build a redactor seeded from secret-looking environment variables.

    The domain never reads the process environment itself; callers pass
    ``os.environ`` (or a test mapping).

    :param environ: Environment variables, typically ``os.environ``.
    :param scrub: Optional PII scrubber for ``redact_deep``.
    :return: A redactor holding the value of every variable whose name
        looks like a password, secret, token, or API key.
    """
    redactor = Redactor(scrub)
    for key, value in environ.items():
        if _SECRET_ENV_RE.search(key):
            redactor.add_secret(value)
    return redactor
