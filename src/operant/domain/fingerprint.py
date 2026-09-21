"""
Value-free structural fingerprint of a screen for content localization.

A screen's identity is its content, not its title or URL (which repeat
across states - a bank's index page looks the same in the title bar
logged in or out). We project the accessibility control inventory into a
bag of normalized, value-free signatures ``role|name|label|coarse_path``:
digit runs become ``#`` and per-control values and row indices are
dropped, so the same screen fingerprints identically across runs even as
balances, dates, and row counts change.

Import as:

import operant.domain.fingerprint as odfinger
"""

from __future__ import annotations

import collections.abc
import dataclasses
import re
import urllib.parse
from typing import FrozenSet, List, Optional

import operant.domain.models.digest as digest

# A number is one value token: collapse digit runs with their internal
# separators (thousands, decimals, dates, times) so "$2,550.00" and
# "$1.00" - or "08/23/2026" and "01/01/2000" - fingerprint identically.
_DIGITS = re.compile(r"\d[\d.,:/]*\d|\d")
_ROW_INDEX = re.compile(r":\d+")
_WS = re.compile(r"\s+")
# Coverage of a node's fingerprint at which a screen counts as that node.
SAME_SCREEN_COVERAGE = 0.6


def normalize(value: str) -> str:
    """
    Value-free normal form of a label: digits to ``#``, lower-cased.
    """
    collapsed = _WS.sub(" ", _DIGITS.sub("#", value)).strip().lower()
    trimmed = collapsed[:60]
    return trimmed


_norm = normalize


def _coarse_path(path: str) -> str:
    """
    Drop row indices so a path matches across table rows.
    """
    coarse = _ROW_INDEX.sub("", path)
    return coarse


def _signature(control: digest.Control) -> str:
    """
    Build one control's value-free content signature.
    """
    signature = "|".join(
        (
            control.role.lower(),
            _norm(control.name),
            _norm(control.label),
            _coarse_path(control.path),
        )
    )
    return signature


def of(screen: digest.ScreenDigest) -> List[str]:
    """
    Return the screen's value-free content signatures, sorted and unique.
    """
    signatures = sorted({_signature(control) for control in screen.controls})
    return signatures


def coverage(
    node_fp: collections.abc.Sequence[str],
    screen_fp: collections.abc.Collection[str],
) -> float:
    """
    Fraction of the node's fingerprint present on the live screen.

    Recall, not Jaccard: the live screen may carry extra dynamic
    controls (e.g. table rows), which must not lower a genuine match.
    """
    if not node_fp:
        fraction = 0.0
    else:
        present = sum(1 for signature in node_fp if signature in screen_fp)
        fraction = present / len(node_fp)
    return fraction


# #############################################################################
# ScreenViews
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ScreenViews:
    """
    Two independent descriptions of a screen.

    A UI change rarely breaks both: translation rewrites the names and
    keeps the layout, a redesign moves the layout and keeps the names.

    :ivar text: ``role|name`` of every named control.
    :ivar structure: ``role|coarse_path`` of every control.
    """

    text: FrozenSet[str]
    structure: FrozenSet[str]


def views(signatures: collections.abc.Iterable[str]) -> ScreenViews:
    """
    Split ``role|name|label|path`` signatures into the two views.

    The label is left out: it is only the text seen before the control, so
    it changes with the layout around it.

    :param signatures: signatures, stored on a node or from ``of``.
    :return: both views.
    """
    text = set()
    structure = set()
    for signature in signatures:
        parts = signature.split("|")
        role, name, path = parts[0], parts[1], parts[-1]
        structure.add(f"{role}|{path}")
        if name:
            text.add(f"{role}|{name}")
    return ScreenViews(text=frozenset(text), structure=frozenset(structure))


def url_path(url: Optional[str]) -> str:
    """
    Reduce a URL to a value-free page identity.

    Keeps the path and a route fragment. Drops the host, because tenants
    differ, plus query values and session ids, and masks digits.

    :param url: the full URL.
    :return: the normalised path, or ``""`` without one.
    """
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    path = parts.path.split(";", 1)[0].rstrip("/") or "/"
    route = parts.fragment if parts.fragment.startswith(("/", "!")) else ""
    masked = _DIGITS.sub("#", f"{path}#{route}" if route else path).lower()
    return masked
