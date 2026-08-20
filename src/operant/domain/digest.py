"""
Rendering of a screen digest as text.

The one implementation behind both the model's turn context and the
human drive REPL.

Import as:

import operant.domain.digest as digest
"""

from __future__ import annotations

import operant.domain.models.digest as digest


def _render_control(control: digest.Control) -> str:
    """
    Render one control as a single indented line.
    """
    bits = [f"{control.ref} {control.role}"]
    if control.name:
        bits.append(f'name="{control.name}"')
    if control.label and control.label != control.name:
        bits.append(f'label="{control.label}"')
    if control.value:
        bits.append(f'value="{control.value}"')
    if not control.enabled:
        bits.append("(disabled)")
    line = "  " + " ".join(bits)
    return line


def render_digest(
    screen: digest.ScreenDigest,
    max_controls: int = 60,
    include_text: bool = True,
) -> str:
    """
    Render the window title, controls, and visible text as lines.

    :param screen: The digest to render.
    :param max_controls: Controls listed before an ``... N more``
        marker.
    :param include_text: Whether to append the (trimmed) visible text.
    :return: The multi-line rendering.
    """
    lines = [_render_control(c) for c in screen.controls[:max_controls]]
    if len(screen.controls) > max_controls:
        lines.append(f"  ... {len(screen.controls) - max_controls} more")
    out = [
        f"WINDOW: {screen.window_title}",
        f"CONTROLS ({len(screen.controls)}):",
        *lines,
    ]
    if include_text:
        out += ["VISIBLE TEXT (trimmed):", screen.text[:2500]]
    rendered = "\n".join(out)
    return rendered
