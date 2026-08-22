"""
Environment-variable secret store (read-only).

Import as:

import operant.adapters.secrets.env as env
"""

from __future__ import annotations

import collections.abc
import os
from typing import Optional

import operant.domain.errors as errors

# #############################################################################
# EnvSecretStore
# #############################################################################


class EnvSecretStore:
    """
    Resolve locators as environment variable names.

    :ivar backend: Always ``"env"``.
    """

    backend = "env"

    def __init__(
        self, environ: Optional[collections.abc.Mapping[str, str]] = None
    ) -> None:
        self._environ = os.environ if environ is None else environ

    def get(self, locator: str) -> Optional[str]:
        """
        Return the variable's value, or ``None`` when unset or empty.
        """
        value = self._environ.get(locator) or None
        return value

    def exists(self, locator: str) -> bool:
        """
        Report whether the variable is set to a non-empty value.
        """
        present = bool(self._environ.get(locator))
        return present

    def set(self, locator: str, value: str) -> None:
        """
        Refuse the write: the environment is not a writable store.
        """
        raise errors.SecretBackendUnavailableError(
            f"env backend is read-only; set {locator} in .env instead"
        )
