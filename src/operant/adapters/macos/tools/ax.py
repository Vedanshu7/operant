"""
Pure accessibility actuators: click, fill, select, and scroll via AX.

Import as:

import operant.adapters.macos.tools.ax as ax
"""

from __future__ import annotations

import time
from typing import Final, FrozenSet, List, Optional

import xa11y

import operant.adapters.macos.session as mssessio
import operant.domain.models.actions as actions
import operant.domain.models.tools as tools

_NO_TARGET: Final = "no resolved target element in context"


# #############################################################################
# AxActionTool
# #############################################################################


class AxActionTool:
    """
    Press for clicks, focus+set_value for fills.

    Writes commit asynchronously on web views, so this tool is never
    self-verified; the dispatcher's fill verifier confirms the effect.
    """

    spec = tools.ToolSpec(
        name="ax-action",
        version="1",
        serves=frozenset({"click", "fill"}),
        permissions=("macOS Accessibility",),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report always-available health; failures surface at execute time.
        """
        report = tools.ToolHealth("ok")
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Press or fills the resolved target element.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to act on.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Press for a click, focus+set for a fill.
            try:
                if action.kind == "click":
                    # Click: press the element.
                    element.press()
                    time.sleep(0.3)
                else:
                    # Fill: focus and set the value.
                    element.focus()
                    time.sleep(0.1)
                    element.set_value(action.value or "")
                result = tools.ToolResult(status="ok", verified=False)
            except xa11y.XA11yError as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result


# #############################################################################
# AxSelectTool
# #############################################################################


class AxSelectTool:
    """
    Choose an option in a combo box or pop-up.

    ``set_value`` first (HTML selects accept it); else open the popup
    and press the matching option. Selection is its own action kind
    because all fill tools fail on combo boxes.
    """

    spec = tools.ToolSpec(
        name="ax-select",
        version="1",
        serves=frozenset({"select"}),
        permissions=("macOS Accessibility",),
    )

    _OPTION_ROLES: Final[FrozenSet[str]] = frozenset(
        {"menu_item", "option", "list_item", "cell", "radio_button"}
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
        Set the value directly, else opens the popup and picks it.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to select in.
            result = tools.ToolResult(status="failed", reason=_NO_TARGET)
        else:
            # Try a direct set, else fall back to the popup.
            option = action.option or ""
            try:
                if self._set_value(element, option):
                    # Direct set_value took.
                    result = tools.ToolResult(status="ok", verified=False)
                else:
                    # Otherwise open the popup and pick the option.
                    result = self._pick_from_popup(element, option)
            except xa11y.XA11yError as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result

    def _set_value(self, element: xa11y.Element, option: str) -> bool:
        """
        Set the value and report whether it took.
        """
        try:
            element.set_value(option)
            time.sleep(0.4)
            matched = (element.value or "").strip() == option
        except xa11y.XA11yError:
            matched = False
        return matched

    def _pick_from_popup(
        self, element: xa11y.Element, option: str
    ) -> tools.ToolResult:
        """
        Open the popup and press the matching option.
        """
        try:
            element.expand()
        except xa11y.XA11yError:
            element.press()
        time.sleep(0.6)
        item = self._find_option(option)
        if item is None:
            # Option not present in the open popup.
            result = tools.ToolResult(
                status="failed",
                reason=f"option {option!r} not found in the open popup",
            )
        else:
            # Press the matching option.
            try:
                item.press()
            except xa11y.XA11yError:
                item.select()
            time.sleep(0.3)
            result = tools.ToolResult(status="ok", verified=False)
        return result

    def _find_option(self, option: str) -> Optional[xa11y.Element]:
        """
        Return the option matching ``option`` across the app's windows.
        """
        want = option.strip().lower()
        contains: List[Optional[xa11y.Element]] = [None]

        # Depth-first search for the matching option element.
        def walk(element: xa11y.Element, depth: int) -> Optional[xa11y.Element]:
            if depth > 14:
                return None
            if element.role in self._OPTION_ROLES:
                name = (element.name or "").strip().lower()
                if name == want:
                    return element
                if want and want in name and contains[0] is None:
                    contains[0] = element
            for child in element.children():
                got = walk(child, depth + 1)
                if got is not None:
                    return got
            return None

        # Popup menus can attach to the app (a transient window), not the
        # window that owns the combo - search every window of the app.
        found = None
        try:
            for window in self.session.app().children():
                got = walk(window, 0)
                if got is not None:
                    found = got
                    break
            else:
                found = contains[0]
        except xa11y.XA11yError:
            found = None
        return found


# #############################################################################
# AxScrollTool
# #############################################################################


class AxScrollTool:
    """
    Scroll a targeted element into view via the accessibility API.
    """

    spec = tools.ToolSpec(
        name="ax-scroll",
        version="1",
        serves=frozenset({"scroll"}),
        permissions=("macOS Accessibility",),
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
        Scroll the target into view; window scroll falls through.
        """
        element: xa11y.Element = ctx.target
        if element is None:
            # No target to scroll into view.
            result = tools.ToolResult(
                status="failed",
                reason="no target to scroll into view (window scroll "
                "falls through)",
            )
        else:
            # Scroll the target into view.
            try:
                element.scroll_into_view()
                time.sleep(0.3)
                result = tools.ToolResult(status="ok", verified=True)
            except xa11y.XA11yError as err:
                result = tools.ToolResult(status="failed", reason=str(err))
        return result
