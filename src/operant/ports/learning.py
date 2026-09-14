"""
The preference-store port for learned tool choices.

Import as:

import operant.ports.learning as learning
"""

from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable

# #############################################################################
# PreferenceStore
# #############################################################################


@runtime_checkable
class PreferenceStore(Protocol):
    """
    Persist how often each tool worked and failed per surface signature.
    """

    def load(self) -> Dict[str, Dict[str, List[int]]]:
        """
        Return ``{signature: {tool_name: [worked, failed]}}``.
        """
        ...

    def save(self, counts: Dict[str, Dict[str, List[int]]]) -> None:
        """
        Replace the stored counts with ``counts``.
        """
        ...
