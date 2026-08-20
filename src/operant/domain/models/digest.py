"""
The runtime screen digest.

A digest is what the surface observed in one snapshot: the front app,
its window title, the visible text, and the controls with ephemeral
handles. It is never persisted; target strategies and conditions are
resolved against it purely.

Import as:

import operant.domain.models.digest as digest
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Tuple

# #############################################################################
# Box
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Box:
    """
    A rectangle normalised to the window.

    :ivar x: Left edge, 0..1 of the window width.
    :ivar y: Top edge, 0..1 of the window height.
    :ivar w: Width, 0..1 of the window width.
    :ivar h: Height, 0..1 of the window height.
    """

    x: float
    y: float
    w: float
    h: float


# #############################################################################
# Control
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Control:
    """
    One actionable element in the accessibility inventory.

    :ivar ref: Ephemeral handle, valid for this snapshot only.
    :ivar role: Accessibility role, e.g. ``button`` or ``textfield``.
    :ivar name: Accessible name of the element.
    :ivar label: Nearby anchoring text (legacy layouts).
    :ivar path: A11y tree path, e.g.
        ``window>group:1>table>row:3>link``.
    :ivar box: Window-normalised bounds.
    :ivar value: Current value, when the element carries one.
    :ivar enabled: Whether the element accepts interaction.
    :ivar actions: Accessibility actions the element supports.
    """

    ref: str
    role: str
    name: str
    label: str
    path: str
    box: Box
    value: Optional[str] = None
    enabled: bool = True
    actions: Tuple[str, ...] = ()


# #############################################################################
# ScreenDigest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ScreenDigest:
    """
    What the surface observed in one snapshot.

    :ivar app: Name of the frontmost application.
    :ivar window_title: Title of the observed window.
    :ivar text: Concatenated visible text of the tree.
    :ivar controls: Actionable elements found in the tree.
    :ivar dialog: Text of a modal dialog, if one is up.
    """

    app: str
    window_title: str
    text: str
    controls: Tuple[Control, ...] = ()
    dialog: Optional[str] = None
