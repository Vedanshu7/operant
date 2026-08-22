"""
Versioned capability-artifact storage on disk.

Layout: ``artifacts/<id>/v<N>.json`` (immutable) and
``artifacts/<id>/HEAD``. A flat ``artifacts/<id>.json`` from the
previous layout is still readable until ``operant migrate`` moves it;
stability counters live in SQLite, so artifact files never change after
they are written.

Import as:

import operant.infra.repositories.artifacts as raartifa
"""

from __future__ import annotations

import pathlib
from typing import List, Optional

import operant.domain.errors as errors
import operant.domain.models.artifact as maartifa
import operant.helpers.files as files
import operant.infra.repositories.versioned as versione

# #############################################################################
# FileArtifactRepository
# #############################################################################


class FileArtifactRepository:
    """
    Implements ``operant.ports.repositories.ArtifactRepository`` on disk.
    """

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self._docs = versione.VersionedDocuments(
            root, maartifa.CapabilityArtifact
        )

    def versions(self, artifact_id: str) -> List[int]:
        """
        List stored versions for ``artifact_id``.
        """
        numbers = self._docs.versions(artifact_id)
        return numbers

    def head(self, artifact_id: str) -> Optional[int]:
        """
        Return the current version, or the legacy file's version.
        """
        current = self._docs.head(artifact_id)
        if current is None:
            legacy = self._legacy_path(artifact_id)
            if legacy.exists():
                current = files.read_model(
                    legacy, maartifa.CapabilityArtifact
                ).version
        return current

    def exists(self, artifact_id: str) -> bool:
        """
        Report whether the artifact exists in either layout.
        """
        present = self.head(artifact_id) is not None
        return present

    def ids(self) -> List[str]:
        """
        List artifact ids across both layouts.
        """
        found = set(self._docs.keys())
        if self.root.exists():
            found.update(
                path.stem for path in self.root.glob("*.json") if path.is_file()
            )
        ordered = sorted(found)
        return ordered

    def get(
        self, artifact_id: str, version: Optional[int] = None
    ) -> maartifa.CapabilityArtifact:
        """
        Load a version (``None`` means HEAD), with legacy fallback.
        """
        legacy = self._legacy_path(artifact_id)
        if self._docs.exists(artifact_id):
            # Versioned layout: load the requested version.
            artifact = self._docs.get(artifact_id, version)
        elif legacy.exists() and version is None:
            # Legacy flat file: only its single version can be served.
            artifact = files.read_model(legacy, maartifa.CapabilityArtifact)
        else:
            # Neither layout has it.
            raise errors.NotFoundError(f"no artifact {artifact_id!r}")
        return artifact

    def list(self) -> List[maartifa.CapabilityArtifact]:
        """
        Load the HEAD of every artifact.
        """
        artifacts = [self.get(artifact_id) for artifact_id in self.ids()]
        return artifacts

    def path(self, artifact_id: str, version: int) -> pathlib.Path:
        """
        Return the on-disk path of one version (for audit messages).
        """
        location = self._docs.path_for(artifact_id, version)
        return location

    def save_new_version(
        self, artifact: maartifa.CapabilityArtifact
    ) -> maartifa.CapabilityArtifact:
        """
        Persist ``artifact`` as the next version and advances HEAD.

        The previous flat file, if any, counts toward the version number
        so a migrated artifact continues from where it left off.

        :param artifact: The artifact to store; ``version`` is
            overwritten.
        :return: The stored artifact with its version set.
        """
        legacy_version = 0
        legacy = self._legacy_path(artifact.id)
        if legacy.exists() and not self._docs.exists(artifact.id):
            legacy_version = files.read_model(
                legacy, maartifa.CapabilityArtifact
            ).version
        with self._docs.allocate(
            artifact.id, floor=legacy_version
        ) as next_version:
            stamped = artifact.model_copy(update={"version": next_version})
            self._docs.write(artifact.id, next_version, stamped)
        return stamped

    def approve(self, artifact_id: str) -> maartifa.CapabilityArtifact:
        """
        Write a new version with ``status="approved"``.

        The stability gate is the caller's job (see
        ``operant.domain.governance``); this method only records the
        decision.
        """
        current = self.get(artifact_id)
        approved = self.save_new_version(
            current.model_copy(update={"status": "approved"})
        )
        return approved

    def _legacy_path(self, artifact_id: str) -> pathlib.Path:
        """
        Return the flat pre-versioning path for ``artifact_id``.
        """
        path = self.root / f"{artifact_id}.json"
        return path
