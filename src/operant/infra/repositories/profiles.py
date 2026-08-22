"""
App profiles (policy + tenants) as ``policies/<id>.json`` documents.

Import as:

import operant.infra.repositories.profiles as rpprofil
"""

from __future__ import annotations

import pathlib
from typing import List

import operant.domain.errors as errors
import operant.domain.profile as profile
import operant.helpers.files as files

# #############################################################################
# FileProfileRepository
# #############################################################################


class FileProfileRepository:
    """
    Implements ``operant.ports.repositories.ProfileRepository`` on disk.

    :ivar root: The policies directory.
    """

    def __init__(self, root: pathlib.Path, discovery_base: pathlib.Path) -> None:
        self.root = root
        self._discovery_base = discovery_base

    def path(self, profile_id: str) -> pathlib.Path:
        """
        Return the file path for ``profile_id``.
        """
        path = self.root / f"{profile_id}.json"
        return path

    def exists(self, profile_id: str) -> bool:
        """
        Report whether the profile file exists.
        """
        present = self.path(profile_id).exists()
        return present

    def get(self, profile_id: str) -> profile.AppProfile:
        """
        Load and validates one profile.
        """
        path = self.path(profile_id)
        if not path.exists():
            raise errors.NotFoundError(f"no profile {profile_id!r}")
        document = files.read_model(path, profile.AppProfile)
        return document

    def ids(self) -> List[str]:
        """
        List profile ids (file stems) excluding gateway configuration.
        """
        if self.root.exists():
            found = sorted(
                path.stem
                for path in self.root.glob("*.json")
                if path.stem not in {"gateway", self._discovery_base.stem}
            )
        else:
            found = []
        return found

    def list(self) -> List[profile.AppProfile]:
        """
        Load every profile.
        """
        profiles = [self.get(profile_id) for profile_id in self.ids()]
        return profiles

    def save(self, document: profile.AppProfile) -> pathlib.Path:
        """
        Write the profile atomically under a lock and returns its path.
        """
        path = self.path(document.vendor_id)
        with files.locked(path):
            files.write_model(path, document)
        return path

    def discovery_base(self) -> profile.AppProfile:
        """
        Load the deny-by-default profile used by bootstrap discovery.
        """
        document = files.read_model(self._discovery_base, profile.AppProfile)
        return document
