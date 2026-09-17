"""
Atomic JSON persistence for pydantic models and plain documents.

Every write goes to a sibling temporary file and is renamed into place,
so a crash never leaves a half-written document. Read-modify-write
sequences take ``locked`` to serialise concurrent processes.

Typical usage example:

  with files.locked(path):
      doc = files.read_model(path, Artifact)
      files.write_model(path, doc.model_copy(update={"status": "ok"}))

Import as:

import operant.helpers.files as files
"""

from __future__ import annotations

import collections.abc
import contextlib
import json
import os
import pathlib
from typing import Any

import filelock
import pydantic

_LOCK_TIMEOUT_S = 30.0


def read_json(path: pathlib.Path) -> Any:
    """
    Load a JSON document.

    :param path: file to read.
    :return: the decoded document.
    :raises FileNotFoundError: if ``path`` does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    return document


def write_json(path: pathlib.Path, document: Any, *, indent: int = 2) -> None:
    """
    Write a JSON document atomically.

    :param path: destination; parent directories are created.
    :param document: any JSON-serialisable value.
    :param indent: pretty-print indentation.
    """
    text = json.dumps(document, indent=indent, sort_keys=False) + "\n"
    write_text(path, text)


def write_text(path: pathlib.Path, text: str, *, mode: int = 0o644) -> None:
    """
    Write text atomically via a temporary sibling and ``os.replace``.

    :param path: destination; parent directories are created.
    :param text: content to write.
    :param mode: permissions the file is created with, so a private file
        is never readable by others, not even briefly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.unlink(missing_ok=True)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def read_model[ModelT: pydantic.BaseModel](
    path: pathlib.Path, model: type[ModelT]
) -> ModelT:
    """
    Load and validate a pydantic model from JSON.

    :param path: file to read.
    :param model: model class to validate against.
    :return: the validated model instance.
    :raises FileNotFoundError: if ``path`` does not exist.
        pydantic.ValidationError: If the document does not match.
    """
    instance = model.model_validate_json(path.read_text(encoding="utf-8"))
    return instance


def write_model(path: pathlib.Path, instance: pydantic.BaseModel) -> None:
    """
    Serialise a pydantic model to JSON atomically.

    Aliases are honoured so on-disk documents keep their external names.

    :param path: destination; parent directories are created.
    :param instance: model to write.
    """
    text = instance.model_dump_json(indent=2, by_alias=True) + "\n"
    write_text(path, text)


@contextlib.contextmanager
def locked(
    path: pathlib.Path, *, timeout_s: float = _LOCK_TIMEOUT_S
) -> collections.abc.Iterator[None]:
    """
    Hold an inter-process lock for a read-modify-write on ``path``.

    :param path: the document being updated; the lock file sits beside
        it.
    :param timeout_s: how long to wait before giving up.
    :yield: Nothing; the lock is held for the duration of the block.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = filelock.FileLock(str(path.with_name(f".{path.name}.lock")))
    with lock.acquire(timeout=timeout_s):
        yield
