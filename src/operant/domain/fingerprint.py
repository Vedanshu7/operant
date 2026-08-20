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
import re
from typing import List

import operant.domain.models.digest as digest

# A number is one value token: collapse digit runs with their internal
# separators (thousands, decimals, dates, times) so "$2,550.00" and
# "$1.00" - or "08/23/2026" and "01/01/2000" - fingerprint identically.
_DIGITS = re.compile(r"\d[\d.,:/]*\d|\d")
_ROW_INDEX = re.compile(r":\d+")
_WS = re.compile(r"\s+")


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
