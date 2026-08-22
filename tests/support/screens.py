"""
Builders for screen digests and controls used by pure domain tests.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

import operant.domain.models.digest as mddigest


def control(
    ref: str = "c0",
    role: str = "button",
    name: str = "",
    label: str = "",
    value: Optional[str] = None,
    enabled: bool = True,
    path: str = "window>form>input",
    box: Optional[mddigest.Box] = None,
) -> mddigest.Control:
    """
    Build a control with sensible defaults for every field.

    :param ref: Ephemeral handle.
    :param role: Accessibility role.
    :param name: Accessible name.
    :param label: Anchoring label text.
    :param value: Current value.
    :param enabled: Whether the control accepts interaction.
    :param path: A11y tree path.
    :param box: Window-normalised bounds; a small box near the top-left
        when omitted.
    :return: The control.
    """
    return mddigest.Control(
        ref=ref,
        role=role,
        name=name,
        label=label,
        path=path,
        box=box or mddigest.Box(0.1, 0.1, 0.1, 0.05),
        value=value,
        enabled=enabled,
    )


def digest(
    controls: Union[Tuple[mddigest.Control, ...], List[mddigest.Control]] = (),
    *,
    app: str = "Chrome",
    window_title: str = "ParaBank | Accounts Overview",
    text: str = "",
    dialog: Optional[str] = None,
) -> mddigest.ScreenDigest:
    """
    Build a digest with sensible defaults for every field.

    :param controls: Controls on screen.
    :param app: Frontmost application name.
    :param window_title: Window title.
    :param text: Visible text.
    :param dialog: Modal dialog text, if one is up.
    :return: The digest.
    """
    return mddigest.ScreenDigest(
        app=app,
        window_title=window_title,
        text=text,
        controls=tuple(controls),
        dialog=dialog,
    )
