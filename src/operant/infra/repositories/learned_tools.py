"""
Persistence for learned tool preferences (``state/learned-tools.json``).

Import as:

import operant.infra.repositories.learned_tools as learned_
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict

import operant.helpers.files as files

# #############################################################################
# LearnedToolsStore
# #############################################################################


class LearnedToolsStore:
    """
    A flat ``{signature: tool_name}`` document.

    A corrupt or missing file reads as empty so learning degrades to
    "nothing learned yet" rather than failing a run.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def load(self) -> Dict[str, str]:
        """
        Return the stored preferences, or ``{}`` when unreadable.
        """
        result: Dict[str, str] = {}
        if self._path.exists():
            try:
                document = files.read_json(self._path)
            except (json.JSONDecodeError, OSError):
                pass
            else:
                if isinstance(document, dict):
                    result = {
                        str(key): str(value) for key, value in document.items()
                    }
        return result

    def save(self, preferences: Dict[str, str]) -> None:
        """
        Write the full preference map atomically.
        """
        with files.locked(self._path):
            files.write_text(
                self._path,
                json.dumps(preferences, indent=2, sort_keys=True) + "\n",
            )
