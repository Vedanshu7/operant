"""
Persistence for remembered step remedies (``state/remediations.json``).

Import as:

import operant.infra.repositories.remediations as rgremed
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict

import operant.helpers.files as files

# #############################################################################
# RemediationsStore
# #############################################################################


class RemediationsStore:
    """
    A flat ``{key: remedy-mapping}`` document.

    A corrupt or missing file reads as empty so the memory degrades to
    "nothing remembered yet" rather than failing a run.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def load(self) -> Dict[str, Dict[str, object]]:
        """
        Return the stored remedies, or ``{}`` when unreadable.
        """
        result: Dict[str, Dict[str, object]] = {}
        if self._path.exists():
            try:
                document = files.read_json(self._path)
            except (json.JSONDecodeError, OSError):
                pass
            else:
                if isinstance(document, dict):
                    result = {
                        str(key): value
                        for key, value in document.items()
                        if isinstance(value, dict)
                    }
        return result

    def save(self, remedies: Dict[str, Dict[str, object]]) -> None:
        """
        Write the full remedy map atomically.
        """
        with files.locked(self._path):
            files.write_text(
                self._path,
                json.dumps(remedies, indent=2, sort_keys=True) + "\n",
            )
