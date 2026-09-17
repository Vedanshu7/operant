"""
Small text utilities shared across layers.

Import as:

import operant.helpers.text as text
"""

from __future__ import annotations

import collections.abc
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def slugify(text: str, *, max_length: int = 40) -> str:
    """
    Lower-case text into a dash-separated identifier.

    :param text: free text such as a window title.
    :param max_length: hard cap on the result length.
    :return: a slug made of ``[a-z0-9-]``; ``"untitled"`` if nothing
        survives.
    """
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")[:max_length].strip("-")
    result = slug or "untitled"
    return result


def truncate(text: str, limit: int, *, marker: str = "…") -> str:
    """
    Cut text to ``limit`` characters, appending ``marker`` when cut.

    :param text: input text.
    :param limit: maximum length of the result including the marker.
    :param marker: suffix that signals truncation.
    :return: the original text when it fits, otherwise a truncated copy.
    """
    if len(text) <= limit:
        result = text
    else:
        result = text[: max(limit - len(marker), 0)] + marker
    return result


def substitute_placeholders(
    text: str, params: collections.abc.Mapping[str, str]
) -> str:
    """
    Replace ``{{name}}`` placeholders with values from ``params``.

    Unknown placeholders are left untouched so a missing input is
    visible rather than silently blank.

    :param text: template text.
    :param params: placeholder values.
    :return: the substituted text.
    """
    result = _PLACEHOLDER_RE.sub(
        lambda match: params.get(match.group(1), match.group(0)), text
    )
    return result


def safe_filename(label: str, *, max_length: int = 60) -> str:
    """
    Reduce a label to characters safe in a filename.

    :param label: free text.
    :param max_length: hard cap on the result length.
    :return: alphanumerics and dashes only.
    """
    result = re.sub(r"[^A-Za-z0-9-]+", "-", label).strip("-")[:max_length]
    return result
