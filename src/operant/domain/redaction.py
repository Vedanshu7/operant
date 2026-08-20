"""Redaction of known secret values before anything is written.

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
_MASK: Final = "[REDACTED]"


# #############################################################################
# Redactor
# #############################################################################


class Redactor:
    """
    Replace every registered secret value in text with a mask.

    Longer secrets are replaced first so a short secret that is a
    substring of a longer one cannot leave fragments behind.
    """

    def __init__(self) -> None:
        self._secrets: List[str] = []

    def add_secret(self, value: Optional[str]) -> None:
        """
        Register a value to mask; ignores empty and very short ones.

        :param value: The secret value, or ``None``.
        """
        if value and len(value) >= 3 and value not in self._secrets:
            self._secrets.append(value)
            self._secrets.sort(key=len, reverse=True)

    def redact(self, text: str) -> str:
        """
        Masks every registered secret in the text.

        :param text: Text that may contain secret values.
        :return: The text with each secret replaced by ``[REDACTED]``.
        """
        for secret in self._secrets:
            text = text.replace(secret, _MASK)
        return text

    def redact_deep(self, value: Any) -> Any:
        """
        Masks secrets inside any JSON-serialisable structure.

        :param value: A structure of dicts, lists, and scalars; non-JSON
            values are stringified.
        :return: An equivalent structure with secrets masked.
        """
        restored = json.loads(self.redact(json.dumps(value, default=str)))
        return restored


def redactor_from_env(environ: collections.abc.Mapping[str, str]) -> Redactor:
    """
    Build a redactor seeded from secret-looking environment variables.

    The domain never reads the process environment itself; callers pass
    ``os.environ`` (or a test mapping).

    :param environ: Environment variables, typically ``os.environ``.
    :return: A redactor holding the value of every variable whose name
        looks like a password, secret, token, or API key.
    """
    redactor = Redactor()
    for key, value in environ.items():
        if _SECRET_ENV_RE.search(key):
            redactor.add_secret(value)
    return redactor
