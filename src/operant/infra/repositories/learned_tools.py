"""
Persistence for learned tool preferences (``state/learned-tools.json``).

Import as:

import operant.infra.repositories.learned_tools as learned_
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict, List

import operant.helpers.files as files

_VERSION = 2


# #############################################################################
# LearnedToolsStore
# #############################################################################


class LearnedToolsStore:
    """
    ``{"version": 2, "signatures": {sig: {tool: [worked, failed]}}}``.

    A corrupt or missing file, or the old flat ``{signature: tool}``
    format (keyed by the model's wording and record values), reads as
    empty so learning starts over rather than failing a run.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def load(self) -> Dict[str, Dict[str, List[int]]]:
        """
        Return the stored counts, or ``{}`` when unreadable or old.
        """
        result: Dict[str, Dict[str, List[int]]] = {}
        if self._path.exists():
            try:
                document = files.read_json(self._path)
            except (json.JSONDecodeError, OSError):
                document = None
            if isinstance(document, dict) and document.get("version") == _VERSION:
                result = {
                    str(sig): {
                        str(tool): [int(counts[0]), int(counts[1])]
                        for tool, counts in tools.items()
                    }
                    for sig, tools in document.get("signatures", {}).items()
                }
        return result

    def save(self, counts: Dict[str, Dict[str, List[int]]]) -> None:
        """
        Write all counts atomically.
        """
        document = {"version": _VERSION, "signatures": counts}
        with files.locked(self._path):
            files.write_text(
                self._path, json.dumps(document, indent=2, sort_keys=True) + "\n"
            )
