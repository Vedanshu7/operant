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

    :ivar x: left edge, 0..1 of the window width.
    :ivar y: top edge, 0..1 of the window height.
    :ivar w: width, 0..1 of the window width.
    :ivar h: height, 0..1 of the window height.
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

    :ivar ref: ephemeral handle, valid for this snapshot only.
    :ivar role: accessibility role, e.g. ``button`` or ``textfield``.
    :ivar name: accessible name of the element.
    :ivar label: nearby anchoring text (legacy layouts).
    :ivar path: a11y tree path, e.g.
        ``window>group:1>table>row:3>link``.
    :ivar box: window-normalised bounds.
    :ivar value: current value, when the element carries one.
    :ivar enabled: whether the element accepts interaction.
    :ivar actions: accessibility actions the element supports.
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

    :ivar app: name of the frontmost application.
    :ivar window_title: title of the observed window.
    :ivar text: concatenated visible text of the tree.
    :ivar controls: actionable elements found in the tree.
    :ivar dialog: text of a modal dialog, if one is up.
    :ivar url: the page address, in a browser that reports it.
    """

    app: str
    window_title: str
    text: str
    controls: Tuple[Control, ...] = ()
    dialog: Optional[str] = None
    url: Optional[str] = None
