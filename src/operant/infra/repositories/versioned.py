"""
Shared layout for immutable, versioned JSON documents.

Layout: ``<root>/<key>/v<N>.json`` plus ``<root>/<key>/HEAD`` naming the
current version. Versions are never overwritten; a new save writes
``v<N+1>`` under a file lock and then advances ``HEAD`` atomically.

Import as:

import operant.infra.repositories.versioned as versione
"""

from __future__ import annotations

import collections.abc
import contextlib
import pathlib
from typing import List, Optional

import pydantic

import operant.domain.errors as errors
import operant.helpers.files as files

# #############################################################################
# VersionedDocuments
# #############################################################################


class VersionedDocuments[ModelT: pydantic.BaseModel]:
    """
    Versioned document store for one model type.

    :ivar root: Directory holding one sub-directory per key.
    """

    def __init__(self, root: pathlib.Path, model: type[ModelT]) -> None:
        self.root = root
        self._model = model

    def directory(self, key: str) -> pathlib.Path:
        """
        Return the directory for ``key`` (may not exist yet).
        """
        directory = self.root / key
        return directory

    def versions(self, key: str) -> List[int]:
        """
        List stored version numbers for ``key`` in ascending order.
        """
        directory = self.directory(key)
        numbers = []
        if directory.exists():
            for path in directory.glob("v*.json"):
                suffix = path.stem[1:]
                if suffix.isdigit():
                    numbers.append(int(suffix))
        ordered = sorted(numbers)
        return ordered

    def head(self, key: str) -> Optional[int]:
        """
        Return the current version, falling back to the highest stored.
        """
        head = self.directory(key) / "HEAD"
        current: Optional[int] = None
        if head.exists():
            text = head.read_text(encoding="utf-8").strip()
            if text.isdigit():
                current = int(text)
        if current is None:
            versions = self.versions(key)
            current = versions[-1] if versions else None
        return current

    def exists(self, key: str) -> bool:
        """
        Report whether any version exists for ``key``.
        """
        present = self.head(key) is not None
        return present

    def keys(self) -> List[str]:
        """
        List keys that have at least one version.
        """
        if self.root.exists():
            found = sorted(
                path.name
                for path in self.root.iterdir()
                if path.is_dir() and self.exists(path.name)
            )
        else:
            found = []
        return found

    def path_for(self, key: str, version: int) -> pathlib.Path:
        """
        Return the file path of one version.
        """
        path = self.directory(key) / f"v{version}.json"
        return path

    def get(self, key: str, version: Optional[int] = None) -> ModelT:
        """
        Load one version (``None`` means HEAD).
        """
        resolved = self.head(key) if version is None else version
        if resolved is None:
            raise errors.NotFoundError(f"no document for {key!r}")
        path = self.path_for(key, resolved)
        if not path.exists():
            raise errors.NotFoundError(f"no version {resolved} for {key!r}")
        document = files.read_model(path, self._model)
        return document

    @contextlib.contextmanager
    def allocate(
        self, key: str, *, floor: int = 0
    ) -> collections.abc.Iterator[int]:
        """
        Reserve the next version number under the key's lock.

        :param key: The document key.
        :param floor: A version number the result must exceed (used when
            an older layout already reached that version).
        :yield: The version number to write; ``HEAD`` advances on exit.
        """
        directory = self.directory(key)
        directory.mkdir(parents=True, exist_ok=True)
        with files.locked(directory / "HEAD"):
            next_version = max(self.head(key) or 0, floor) + 1
            yield next_version
            files.write_text(directory / "HEAD", f"{next_version}\n")

    def write(self, key: str, version: int, document: ModelT) -> None:
        """
        Write ``document`` as ``version`` without touching ``HEAD``.
        """
        files.write_model(self.path_for(key, version), document)
