"""
A store that consults several backends in order.

Import as:

import operant.adapters.secrets.chained as chained
"""

from __future__ import annotations

import collections.abc
from typing import Optional

import operant.domain.errors as errors
import operant.ports.secrets as secrets

# #############################################################################
# ChainedSecretStore
# #############################################################################


class ChainedSecretStore:
    """
    First store with a value wins; writes go to the first writable store.

    :ivar backend: Backends joined with ``+``, e.g. ``"keychain+env"``.
    """

    def __init__(
        self, stores: collections.abc.Sequence[secrets.SecretStore]
    ) -> None:
        if not stores:
            raise ValueError("ChainedSecretStore needs at least one store")
        self._stores = list(stores)
        self.backend = "+".join(store.backend for store in self._stores)

    def get(self, locator: str) -> Optional[str]:
        """
        Return the first non-missing value across the chain.
        """
        found = None
        for store in self._stores:
            value = store.get(locator)
            if value is not None:
                found = value
                break
        return found

    def exists(self, locator: str) -> bool:
        """
        Report whether any store holds the locator.
        """
        present = any(store.exists(locator) for store in self._stores)
        return present

    def set(self, locator: str, value: str) -> None:
        """
        Write to the first store that accepts writes.
        """
        wrote = False
        for store in self._stores:
            try:
                store.set(locator, value)
            except errors.SecretBackendUnavailableError:
                continue
            wrote = True
            break
        if not wrote:
            raise errors.SecretBackendUnavailableError(
                "no writable secret store in the chain"
            )
