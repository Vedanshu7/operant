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

    :param ref: ephemeral handle.
    :param role: accessibility role.
    :param name: accessible name.
    :param label: anchoring label text.
    :param value: current value.
    :param enabled: whether the control accepts interaction.
    :param path: a11y tree path.
    :param box: window-normalised bounds; a small box near the top-left
        when omitted.
    :return: the control.
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

    :param controls: controls on screen.
    :param app: frontmost application name.
    :param window_title: window title.
    :param text: visible text.
    :param dialog: modal dialog text, if one is up.
    :return: the digest.
    """
    return mddigest.ScreenDigest(
        app=app,
        window_title=window_title,
        text=text,
        controls=tuple(controls),
        dialog=dialog,
    )
