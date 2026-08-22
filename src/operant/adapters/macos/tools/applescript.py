"""
System Events actuators: keystrokes, clipboard paste, press, select.

These carry their own accessibility trust, so they survive the host
process's write-trust going stale - observed live, our AX writes
silently dropped while System Events kept working.

Import as:

import operant.adapters.macos.tools.applescript as applescr
"""

from __future__ import annotations

import subprocess
import time
from typing import Dict, Final

import xa11y

import operant.adapters.macos.session as mssessio
import operant.domain.models.actions as actions
import operant.domain.models.tools as tools

_NO_TARGET: Final = "no resolved target element in context"
_KEY_CODES: Final[Dict[str, int]] = {
    "Enter": 36,
    "Return": 36,
    "Tab": 48,
    "Escape": 53,
    "Space": 49,
    "Delete": 51,
    "ArrowUp": 126,
    "ArrowDown": 125,
    "ArrowLeft": 123,
    "ArrowRight": 124,
}
_RETURN_KEY_CODE: Final = 36


def _system_events_health() -> tools.ToolHealth:
    """
    Report whether System Events is scriptable.
    """
    probe = subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to count processes',
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if probe.returncode == 0:
        # Scriptable.
        report = tools.ToolHealth("ok")
    else:
        # Not scriptable: report the reason.
        report = tools.ToolHealth(
            "unavailable",
            f"System Events not scriptable: {probe.stderr.strip()[:80]}",
        )
    return report


def _osascript(script: str) -> None:
    """
    Run an AppleScript snippet, raising on non-zero exit.
    """
    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        timeout=30,
        capture_output=True,
    )


def _keystroke(text: str) -> None:
    """
    Type ``text`` through System Events.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(f'tell application "System Events" to keystroke "{escaped}"')


def _select_all() -> None:
    """
    Send Cmd+A through System Events.
    """
    _osascript(
        'tell application "System Events" to keystroke "a" using command down'
    )


# #############################################################################
# AppleScriptKeysTool
# #############################################################################


class AppleScriptKeysTool:
    """
    Keystrokes via System Events, gated on our app holding the foreground.

    Physical keys land in the foreground app, so this refuses to type
    unless the target verifiably has focus.
    """

    spec = tools.ToolSpec(
        name="applescript-keys",
        version="1",
        serves=frozenset({"fill", "press"}),
        permissions=("macOS Accessibility", "Automation: System Events"),
        # The text rides in an osascript argv, visible in the process table.
        leaks_value=True,
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report whether System Events is scriptable.
        """
        report = _system_events_health()
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Press a named key, or focuses and types a value.
        """
        result = None
        try:
            self.session.ensure_foreground()
        except RuntimeError as err:
            result = tools.ToolResult(status="failed", reason=str(err))
        if result is None:
            try:
                if action.kind == "press":
                    # A named key press.
                    result = self._press(action.key or "Enter")
                else:
                    # Otherwise focus and type the value.
                    result = self._fill(action, ctx)
            except subprocess.SubprocessError as err:
                result = tools.ToolResult(
                    status="failed", reason=f"osascript: {err}"
                )
        return result

    def _press(self, key: str) -> tools.ToolResult:
        """
        Press a single named key by its key code.
        """
        code = _KEY_CODES.get(key)
        if code is None:
            # Pressing Enter for an unknown key lied to the model (observed
            # live: "Cmd+N" silently became Enter).
            result = tools.ToolResult(
                status="failed",
                reason=f"unsupported key {key!r} - single named keys only",
            )
        else:
            # Send the key by its code.
            _osascript(f'tell application "System Events" to key code {code}')
            result = tools.ToolResult(status="ok", verified=False)
        return result

    def _fill(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Focus the target and replace its contents by typing.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to type into.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Focus, clear, and type the value.
            element.focus()
            time.sleep(0.2)
            _select_all()
            _keystroke(action.value or "")
            result = tools.ToolResult(status="ok", verified=False)
        return result


# #############################################################################
# ClipboardPasteTool
# #############################################################################


class ClipboardPasteTool:
    """
    Fill via clipboard and one Cmd+V chord, restoring the clipboard after.

    A single paste often works where a typed stream does not.
    """

    spec = tools.ToolSpec(
        name="clipboard-paste",
        version="1",
        serves=frozenset({"fill"}),
        permissions=("macOS Accessibility", "Automation: System Events"),
        # The system pasteboard is readable by every app and clipboard
        # manager.
        leaks_value=True,
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report whether System Events is scriptable.
        """
        report = _system_events_health()
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Copy the value, pastes it, and restores the old clipboard.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to paste into.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Copy the value in, paste it, then restore the clipboard.
            previous = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            try:
                self.session.ensure_foreground()
                subprocess.run(
                    ["pbcopy"],
                    input=action.value or "",
                    text=True,
                    check=True,
                    timeout=5,
                )
                element.focus()
                time.sleep(0.2)
                _select_all()
                _osascript(
                    'tell application "System Events" to keystroke "v" '
                    "using command down"
                )
                time.sleep(0.3)
                result = tools.ToolResult(status="ok", verified=False)
            except (subprocess.SubprocessError, RuntimeError) as err:
                result = tools.ToolResult(status="failed", reason=str(err))
            finally:
                subprocess.run(
                    ["pbcopy"],
                    input=previous,
                    text=True,
                    timeout=5,
                    check=False,
                )
        return result


# #############################################################################
# SeSelectTool
# #############################################################################


class SeSelectTool:
    """
    Select fallback via type-ahead: open the popup, type, confirm.
    """

    spec = tools.ToolSpec(
        name="se-select",
        version="1",
        serves=frozenset({"select"}),
        permissions=("macOS Accessibility", "Automation: System Events"),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report whether System Events is scriptable.
        """
        report = _system_events_health()
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Open the popup, types the option text, and presses Return.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target popup to select in.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Type-ahead: open the popup, type the option, confirm.
            try:
                self.session.ensure_foreground()
                element.focus()
                time.sleep(0.2)
                element.press()
                time.sleep(0.5)
                _keystroke(action.option or "")
                time.sleep(0.3)
                _osascript(
                    f'tell application "System Events" to key code '
                    f"{_RETURN_KEY_CODE}"
                )
                time.sleep(0.3)
                result = tools.ToolResult(status="ok", verified=False)
            except (
                subprocess.SubprocessError,
                RuntimeError,
                xa11y.XA11yError,
            ) as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result


# #############################################################################
# SystemEventsPressTool
# #############################################################################


class SystemEventsPressTool:
    """
    Click via System Events performing AXPress on the focused element.
    """

    spec = tools.ToolSpec(
        name="se-press",
        version="1",
        serves=frozenset({"click"}),
        permissions=("Automation: System Events",),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report whether System Events is scriptable.
        """
        report = _system_events_health()
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Focus the target and performs AXPress through System Events.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to press.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Focus, then AXPress the focused element.
            try:
                element.focus()
                time.sleep(0.25)
                if not element.focused:
                    # Never took focus: cannot AXPress safely.
                    result = tools.ToolResult(
                        status="failed",
                        reason="target did not take focus for AXPress",
                    )
                else:
                    # Focused: perform AXPress via System Events.
                    script = (
                        f'tell application "System Events" to tell process '
                        f'"{self.session.app_name}" to perform action '
                        '"AXPress" of '
                        '(value of attribute "AXFocusedUIElement")'
                    )
                    done = subprocess.run(
                        ["osascript", "-e", script],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    if done.returncode != 0:
                        # osascript failed.
                        result = tools.ToolResult(
                            status="failed",
                            reason=f"osascript: {done.stderr.strip()[:120]}",
                        )
                    else:
                        # Pressed.
                        time.sleep(0.3)
                        result = tools.ToolResult(status="ok", verified=False)
            except xa11y.XA11yError as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result
