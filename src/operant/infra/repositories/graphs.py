"""
Per-application, versioned app-graph storage on disk.

Layout: ``graphs/<vendor>/v<N>.json`` (immutable) and
``graphs/<vendor>/HEAD``. Graphs are never mixed across applications and
every version is kept, so a capability that pins ``graph_version`` N
always replays against the exact graph it was compiled on.

Import as:

import operant.infra.repositories.graphs as rggraphs
"""

from __future__ import annotations

import pathlib
from typing import List, Optional

import operant.domain.models.graph as mggraph
import operant.helpers.time as time
import operant.infra.repositories.versioned as versione

# #############################################################################
# FileGraphRepository
# #############################################################################


class FileGraphRepository:
    """
    Implements ``operant.ports.repositories.GraphRepository`` on disk.
    """

    def __init__(self, root: pathlib.Path) -> None:
        self._docs = versione.VersionedDocuments(root, mggraph.AppGraph)

    def versions(self, vendor_id: str) -> List[int]:
        """
        List stored versions for ``vendor_id``.
        """
        numbers = self._docs.versions(vendor_id)
        return numbers

    def head(self, vendor_id: str) -> Optional[int]:
        """
        Return the current version for ``vendor_id``.
        """
        current = self._docs.head(vendor_id)
        return current

    def exists(self, vendor_id: str) -> bool:
        """
        Report whether ``vendor_id`` has a graph.
        """
        present = self._docs.exists(vendor_id)
        return present

    def vendors(self) -> List[str]:
        """
        List vendors that have at least one graph version.
        """
        found = self._docs.keys()
        return found

    def get(
        self, vendor_id: str, version: Optional[int] = None
    ) -> mggraph.AppGraph:
        """
        Load a graph version (``None`` means HEAD).
        """
        graph = self._docs.get(vendor_id, version)
        return graph

    def path(self, vendor_id: str, version: int) -> pathlib.Path:
        """
        Return the on-disk path of one version (for audit messages).
        """
        location = self._docs.path_for(vendor_id, version)
        return location

    def save_new_version(self, graph: mggraph.AppGraph) -> mggraph.AppGraph:
        """
        Persist ``graph`` as the next immutable version and advances HEAD.

        :param graph: The graph to store; its version fields are
            overwritten.
        :return: The stored graph with ``graph_version`` and timestamps
            set.
        """
        now = time.iso_now()
        with self._docs.allocate(graph.vendor_id) as next_version:
            stamped = graph.model_copy(
                update={
                    "graph_version": next_version,
                    "created_at": graph.created_at or now,
                    "updated_at": now,
                }
            )
            self._docs.write(graph.vendor_id, next_version, stamped)
        return stamped
