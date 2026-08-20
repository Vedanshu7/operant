"""
Secret store port.

Import as:

import operant.ports.secrets as secrets
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

# #############################################################################
# SecretStore
# #############################################################################


@runtime_checkable
class SecretStore(Protocol):
    """
    Resolve backend-specific locators to secret values.

    Implementations never log, cache to disk, or return values through
    any channel other than ``get``.
    """

    backend: str

    def get(self, locator: str) -> Optional[str]:
        """
        Return the value for ``locator`` or ``None`` when absent.
        """
        ...

    def exists(self, locator: str) -> bool:
        """
        Report whether ``locator`` has a value without returning it.
        """
        ...

    def set(self, locator: str, value: str) -> None:
        """
        Store ``value`` under ``locator``.
        """
        ...
