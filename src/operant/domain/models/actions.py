"""
The runtime surface action.

A ``SurfaceAction`` is the fully resolved instruction sent to a surface
(driver, accessibility tool) for one step: the control handle, the text
to type, the key to press. It is built at replay or discovery time from
a graph edge and never persisted.

Import as:

import operant.domain.models.actions as actions
"""

from __future__ import annotations

import dataclasses
from typing import Final, Literal, Optional

# The app a goal that names only a URL opens.
DEFAULT_BROWSER: Final = "Google Chrome"
# Wheel notches a scroll moves when the action names no amount.
DEFAULT_SCROLL_NOTCHES: Final = 5


# #############################################################################
# SurfaceAction
# #############################################################################


@dataclasses.dataclass(frozen=True)
class SurfaceAction:
    """
    One resolved instruction for the actuation surface.

    :ivar kind: what to do on the surface.
    :ivar ref: control handle from the current digest, for click/fill.
    :ivar value: text to type, for fill.
    :ivar app: application to launch.
    :ivar url: location to open on launch.
    :ivar key: key chord to press.
    :ivar option: resolved option text, for select.
    :ivar direction: scroll direction, ``up`` or ``down``.
    :ivar amount: scroll notches.
    :ivar x: window-normalised click x (0..1); the vision-grounded
        fallback for elements the accessibility inventory lacks.
    :ivar y: window-normalised click y (0..1); see ``x``.
    :ivar target_text: text describing the target, for policy/risk
        checks; excluded from equality.
    :ivar data_class: sensitivity tag set by the caller (the guard re-
        classifies on its own too).
    :ivar export_from: vendor the typed value was extracted in, when not
        this one.
    :ivar secret_ref: name of the policy-held secret the value was
        resolved from (never the value). A system-held credential typed
        into an allowlisted app is the operator's own login, not a model
        decision; it replays unattended.
    :ivar step: edge id at replay; names the approval question. Excluded
        from equality.
    :ivar gate_unknown: the caller wants a person to approve this action
        if it is an unknown step. It can only tighten the policy.
    """

    kind: Literal[
        "observe", "launch", "click", "fill", "press", "select", "scroll"
    ]
    ref: Optional[str] = None
    value: Optional[str] = None
    app: Optional[str] = None
    url: Optional[str] = None
    key: Optional[str] = None
    option: Optional[str] = None
    direction: Optional[str] = None
    amount: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    target_text: str = dataclasses.field(default="", compare=False)
    data_class: str = "none"
    export_from: Optional[str] = None
    secret_ref: Optional[str] = None
    step: str = dataclasses.field(default="", compare=False)
    gate_unknown: bool = False
