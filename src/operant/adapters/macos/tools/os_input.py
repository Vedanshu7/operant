"""
Synthesized-input actuators: keystrokes, scroll, and coordinate clicks.

These use xa11y's input simulator, which needs Input Monitoring; key
events are dropped silently without it, so ``OsInputTool`` is honest
about being unproven until a fill verifies through it.

Import as:

import operant.adapters.macos.tools.os_input as os_input
"""

from __future__ import annotations

import time
from typing import Final

import xa11y

import operant.adapters.macos.session as mssessio
import operant.domain.models.actions as actions
import operant.domain.models.tools as tools

_NO_TARGET: Final = "no resolved target element in context"
_NO_BOUNDS: Final = "window reports no bounds"


# #############################################################################
# OsInputTool
# #############################################################################


class OsInputTool:
    """
    Raw synthesized input via xa11y's input simulator.
    """

    spec = tools.ToolSpec(
        name="os-input",
        version="1",
        serves=frozenset({"click", "fill", "press"}),
        permissions=("macOS Accessibility", "Input Monitoring"),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Degraded until a fill proves keystrokes are delivered.
        """
        report = tools.ToolHealth(
            "degraded",
            "keystroke delivery unproven (requires Input Monitoring)",
        )
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Press, clicks, or focuses-and-types via synthesized input.
        """
        try:
            self.session.ensure_foreground()
        except RuntimeError as err:
            return tools.ToolResult(status="failed", reason=str(err))
        sim = xa11y.input_sim()
        try:
            if action.kind == "press":
                sim.press(action.key or "Enter")
                return tools.ToolResult(status="ok", verified=False)
            element: xa11y.Element = ctx.target
            if element is None:
                return tools.ToolResult(status="failed", reason=_NO_TARGET)
            if action.kind == "click":
                sim.click(element)
                time.sleep(0.3)
                return tools.ToolResult(status="ok", verified=False)
            sim.click(element)
            time.sleep(0.3)
            sim.chord("a", held=["Meta"])
            time.sleep(0.15)
            sim.type_text(action.value or "")
            return tools.ToolResult(status="ok", verified=False)
        except xa11y.XA11yError as err:
            return tools.ToolResult(status="failed", reason=str(err))


# #############################################################################
# OsInputScrollTool
# #############################################################################


class OsInputScrollTool:
    """
    Scroll the window content with a synthesized wheel at its center.
    """

    spec = tools.ToolSpec(
        name="os-input-scroll",
        version="1",
        serves=frozenset({"scroll"}),
        permissions=("macOS Accessibility", "Input Monitoring"),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report always-available health.
        """
        report = tools.ToolHealth("ok")
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Scroll at the window centre by the requested notches.
        """
        try:
            self.session.ensure_foreground()
            bounds = self.session.window(timeout=5.0).bounds
            if bounds is None:
                # No window bounds to aim at.
                result = tools.ToolResult(status="failed", reason=_NO_BOUNDS)
            else:
                # Scroll at the window centre.
                centre = (
                    round(float(bounds.x) + float(bounds.width) / 2),
                    round(float(bounds.y) + float(bounds.height) / 2),
                )
                sign = 1 if (action.direction or "down") == "down" else -1
                xa11y.input_sim().scroll(centre, dy=(action.amount or 5) * sign)
                time.sleep(0.4)
                result = tools.ToolResult(status="ok", verified=False)
        except (xa11y.XA11yError, RuntimeError) as err:
            result = tools.ToolResult(status="failed", reason=str(err))
        return result


# #############################################################################
# CoordinateClickTool
# #############################################################################


class CoordinateClickTool:
    """
    Vision-grounded click at a window-normalised point.

    Last in the click chain: it runs only when the action carries
    coordinates - the model saw an element on the screenshot that the
    accessibility inventory lacked.
    """

    spec = tools.ToolSpec(
        name="coordinate-click",
        version="1",
        serves=frozenset({"click"}),
        permissions=("macOS Accessibility", "Input Monitoring"),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report always-available health.
        """
        report = tools.ToolHealth("ok")
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Click the window-relative point carried on the action.
        """
        if action.x is None or action.y is None:
            # No coordinates to click.
            result = tools.ToolResult(
                status="failed", reason="no coordinates on the action"
            )
        else:
            # Click the window-relative point.
            try:
                self.session.ensure_foreground()
                bounds = self.session.window(timeout=5.0).bounds
                if bounds is None:
                    # No window bounds to map against.
                    result = tools.ToolResult(status="failed", reason=_NO_BOUNDS)
                else:
                    # Map the normalised point to screen pixels and click.
                    point = (
                        round(float(bounds.x) + action.x * float(bounds.width)),
                        round(float(bounds.y) + action.y * float(bounds.height)),
                    )
                    xa11y.input_sim().click(point)
                    time.sleep(0.4)
                    result = tools.ToolResult(status="ok", verified=False)
            except (xa11y.XA11yError, RuntimeError) as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result
