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
    Lower-cases text into a dash-separated identifier.

    :param text: Free text such as a window title.
    :param max_length: Hard cap on the result length.
    :return: A slug made of ``[a-z0-9-]``; ``"untitled"`` if nothing
        survives.
    """
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")[:max_length].strip("-")
    result = slug or "untitled"
    return result


def truncate(text: str, limit: int, *, marker: str = "…") -> str:
    """
    Cuts text to ``limit`` characters, appending ``marker`` when cut.

    :param text: Input text.
    :param limit: Maximum length of the result including the marker.
    :param marker: Suffix that signals truncation.
    :return: The original text when it fits, otherwise a truncated copy.
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

    :param text: Template text.
    :param params: Placeholder values.
    :return: The substituted text.
    """
    result = _PLACEHOLDER_RE.sub(
        lambda match: params.get(match.group(1), match.group(0)), text
    )
    return result


def safe_filename(label: str, *, max_length: int = 60) -> str:
    """
    Reduces a label to characters safe in a filename.

    :param label: Free text.
    :param max_length: Hard cap on the result length.
    :return: Alphanumerics and dashes only.
    """
    result = re.sub(r"[^A-Za-z0-9-]+", "-", label).strip("-")[:max_length]
    return result
