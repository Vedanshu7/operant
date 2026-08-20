"""
The remediation-store port: remembered fixes keyed by situation+error.

Import as:

import operant.ports.remediation as psremed
"""

from __future__ import annotations

from typing import Dict, Protocol, runtime_checkable

# #############################################################################
# RemediationStore
# #############################################################################


@runtime_checkable
class RemediationStore(Protocol):
    """
    Persist ``{key: remedy-mapping}`` for repeated step errors.
    """

    def load(self) -> Dict[str, Dict[str, object]]:
        """
        Return the stored ``{key: remedy}`` map.
        """
        ...

    def save(self, remedies: Dict[str, Dict[str, object]]) -> None:
        """
        Replace the stored map with ``remedies``.
        """
        ...
