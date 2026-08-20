"""
The preference-store port for learned tool choices.

Import as:

import operant.ports.learning as learning
"""

from __future__ import annotations

from typing import Dict, Protocol, runtime_checkable

# #############################################################################
# PreferenceStore
# #############################################################################


@runtime_checkable
class PreferenceStore(Protocol):
    """
    Persist which tool won for a given surface signature.
    """

    def load(self) -> Dict[str, str]:
        """
        Return the stored ``{signature: tool_name}`` map.
        """
        ...

    def save(self, preferences: Dict[str, str]) -> None:
        """
        Replace the stored map with ``preferences``.
        """
        ...
