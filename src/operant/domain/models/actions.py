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
from typing import Literal, Optional

# #############################################################################
# SurfaceAction
# #############################################################################


@dataclasses.dataclass(frozen=True)
class SurfaceAction:
    """
    One resolved instruction for the actuation surface.

    :ivar kind: What to do on the surface.
    :ivar ref: Control handle from the current digest, for click/fill.
    :ivar value: Text to type, for fill.
    :ivar app: Application to launch.
    :ivar url: Location to open on launch.
    :ivar key: Key chord to press.
    :ivar option: Resolved option text, for select.
    :ivar direction: Scroll direction, ``up`` or ``down``.
    :ivar amount: Scroll notches.
    :ivar x: Window-normalised click x (0..1); the vision-grounded
        fallback for elements the accessibility inventory lacks.
    :ivar y: Window-normalised click y (0..1); see ``x``.
    :ivar target_text: Text describing the target, for policy/risk
        checks; excluded from equality.
    :ivar data_class: Sensitivity tag set by the caller (the guard re-
        classifies on its own too).
    :ivar export_from: Vendor the typed value was extracted in, when not
        this one.
    :ivar secret_ref: Name of the policy-held secret the value was
        resolved from (never the value). A system-held credential typed
        into an allowlisted app is the operator's own login, not a model
        decision; it replays unattended.
    :ivar step: Edge id at replay; names the approval question. Excluded
        from equality.
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
