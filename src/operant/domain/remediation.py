"""
Cross-run memory of how a repeated step-error was fixed.

An error signature is a coarse, stable fingerprint of a failure - the
volatile parts (control refs, coordinates, numeric ids, quoted values,
timestamps) stripped so the same class of failure on the same kind of
step matches across runs. Paired with the surface situation signature it
keys a remedy the discovery loop surfaces the next time the error recurs.

Import as:

import operant.domain.remediation as odremed
"""

from __future__ import annotations

import dataclasses
import re
from typing import Dict

_REF = re.compile(r"\bc\d+\b")
_HEX = re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE)
_NUM = re.compile(r"\d+")
_QUOTED = re.compile(r"([\"'])(?:\\.|[^\\])*?\1")
_WS = re.compile(r"\s+")
_MAX_LEN = 160


# #############################################################################
# Remedy
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Remedy:
    """
    A remembered fix for a step error.

    :ivar kind: How the fix was found (``alternate_action``,
        ``human_steps``, ...).
    :ivar hint: A short human-readable description replayed to the
        model.
    :ivar applied: How many times this remedy was recorded/reinforced.
    :ivar success: How many of those reinforced a working outcome.
    """

    kind: str
    hint: str
    applied: int = 1
    success: int = 1

    def as_dict(self) -> Dict[str, object]:
        """
        Render the remedy for the flat JSON store.
        """
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Remedy":
        """
        Rebuild a remedy from its stored mapping.
        """
        return cls(
            kind=str(data.get("kind", "")),
            hint=str(data.get("hint", "")),
            applied=int(data.get("applied", 1)),  # type: ignore[call-overload]
            success=int(data.get("success", 1)),  # type: ignore[call-overload]
        )


def error_signature(text: str) -> str:
    """
    Normalise an error message to a stable, value-free fingerprint.

    :param text: The raw error text.
    :return: The normalised signature (lower-cased, bounded length).
    """
    out = _QUOTED.sub("'x'", text)
    out = _HEX.sub("#", out)
    out = _REF.sub("c#", out)
    out = _NUM.sub("#", out)
    out = _WS.sub(" ", out).strip().lower()
    return out[:_MAX_LEN]
