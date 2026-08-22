"""
The accessibility-tree digest observer.

Import as:

import operant.adapters.macos.tools.observe as observe
"""

from __future__ import annotations

import re
from typing import Dict, Final, FrozenSet, List, Optional, Set, Tuple

import xa11y

import operant.adapters.macos.session as mssessio
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.tools as tools

INTERACTIVE_ROLES: Final[FrozenSet[str]] = frozenset(
    {
        "button",
        "link",
        "text_field",
        "password_field",
        "combo_box",
        "check_box",
        "radio_button",
        "menu_item",
        "pop_up_button",
        "tab",
        "slider",
        # Native rich-text editors (Notes body, TextEdit) are AXTextArea -
        # without this the app's main writing surface is invisible as a
        # fill target.
        "text_area",
    }
)
TEXT_ROLES: Final[FrozenSet[str]] = frozenset({"static_text", "text", "heading"})
MAX_NODES: Final = 4000
_NOISE: Final = re.compile(r"missing image descriptions", re.IGNORECASE)


def _is_secure(element: xa11y.Element) -> bool:
    """
    Report whether the element is a secure (password) field.
    """
    secure = "secure" in str(element.raw.get("ax_role", "")).lower()
    return secure


# #############################################################################
# Xa11yDigestObserver
# #############################################################################


class Xa11yDigestObserver:
    """
    Window-scoped digest from the OS accessibility tree.
    """

    spec = tools.ToolSpec(
        name="xa11y-digest",
        version="1",
        serves=frozenset({"observe"}),
        permissions=("macOS Accessibility",),
    )

    def __init__(self, session: mssessio.WindowSession) -> None:
        self.session = session

    def health(self) -> tools.ToolHealth:
        """
        Report ``unavailable`` when the Accessibility grant is missing.
        """
        try:
            xa11y.App.list()
            report = tools.ToolHealth("ok")
        except xa11y.XA11yError as err:
            report = tools.ToolHealth(
                "unavailable", f"accessibility permission: {err}"
            )
        return report

    def execute(
        self, action: actions.SurfaceAction, ctx: tools.ExecutionContext
    ) -> tools.ToolResult:
        """
        Walk the content root into a screen digest.
        """
        window = self.session.window()
        walker = _Walker(self.session, _window_box(window))
        walker.walk(_content_root(window), "content", 0)
        screen = digest.ScreenDigest(
            app=self.session.app_name,
            window_title=window.name or "",
            text=" ".join(walker.texts)[:12000],
            controls=tuple(walker.controls),
        )
        result = tools.ToolResult(status="ok", verified=True, digest=screen)
        return result


def _window_box(window: xa11y.Element) -> Tuple[float, float, float, float]:
    """
    Return the window's ``(x, y, width, height)`` in screen pixels.
    """
    bounds = window.bounds
    box = (
        float(bounds.x if bounds else 0),
        float(bounds.y if bounds else 0),
        float(bounds.width) if bounds and bounds.width else 1.0,
        float(bounds.height) if bounds and bounds.height else 1.0,
    )
    return box


def _content_root(window: xa11y.Element) -> xa11y.Element:
    """
    Prefer the web/content area over browser chrome.

    Native apps (no web area) fall back to the window itself.
    """

    def find(element: xa11y.Element, depth: int) -> Optional[xa11y.Element]:
        if element.role == "web_area":
            return element
        if depth > 8:
            return None
        for child in element.children():
            got = find(child, depth + 1)
            if got is not None:
                return got
        return None

    # Use the web area when present, else the window itself.
    root = find(window, 0) or window
    return root


# #############################################################################
# _Walker
# #############################################################################


class _Walker:
    """
    Accumulate controls and text while walking the accessibility tree.

    Chrome exposes some tables twice (as ``table_row`` structure and as
    flattened groups), so two interactive nodes with the same role,
    name, and pixel bounds are one control - the first wins.
    """

    def __init__(
        self,
        session: mssessio.WindowSession,
        window_box: Tuple[float, float, float, float],
    ) -> None:
        self.session = session
        self._wx, self._wy, self._ww, self._wh = window_box
        self.controls: List[digest.Control] = []
        self.texts: List[str] = []
        self._last_text = ""
        self._count = 0
        self._seen: Set[Tuple[str, str, int, int]] = set()
        session.refs.clear()

    def walk(self, element: xa11y.Element, path: str, depth: int) -> None:
        """
        Recursively record interactive controls and visible text.
        """
        if self._count >= MAX_NODES or depth > 25:
            return
        self._count += 1
        role = element.role
        if role in TEXT_ROLES:
            # Text node: record its text.
            self._record_text(element)
        elif role in INTERACTIVE_ROLES and self._record_control(
            element, role, path
        ):
            # Interactive node recorded: do not descend into it.
            return
        self._walk_children(element, path, depth)

    @staticmethod
    def _shown_value(secure: bool, value: object) -> Optional[str]:
        """
        Return the display value, masking secure fields.
        """
        if secure and value:
            # Mask a secure field's value.
            shown = "********"
        elif isinstance(value, str):
            # Truncate a plain string value.
            shown = value[:200]
        else:
            # No displayable value.
            shown = None
        return shown

    def _walk_children(
        self, element: xa11y.Element, path: str, depth: int
    ) -> None:
        """
        Walk each child with an indexed path segment.
        """
        counts: Dict[str, int] = {}
        for child in element.children():
            index = counts.get(child.role, 0)
            counts[child.role] = index + 1
            self.walk(child, f"{path}>{child.role}:{index}", depth + 1)

    def _record_text(self, element: xa11y.Element) -> None:
        """
        Record an element's text value when non-empty.
        """
        value = (element.value or "").strip() or _name_of(element)
        if value:
            self.texts.append(value)
            self._last_text = value

    def _record_control(
        self, element: xa11y.Element, role: str, path: str
    ) -> bool:
        """
        Record an interactive control unless it is a geometric duplicate.
        """
        text = _name_of(element)
        bounds = element.bounds
        key = (
            role,
            text,
            round(bounds.x if bounds else 0),
            round(bounds.y if bounds else 0),
        )
        # A duplicate (same role, name, pixel bounds) is skipped; walking
        # its children continues either way.
        if bounds is None or key not in self._seen:
            self._seen.add(key)
            ref = f"c{len(self.session.refs)}"
            secure = _is_secure(element)
            value = element.value
            self.controls.append(
                digest.Control(
                    ref=ref,
                    role="password_field" if secure else role,
                    name=text,
                    label=self._last_text[:80],
                    path=path,
                    box=self._box(bounds),
                    value=self._shown_value(secure, value),
                    enabled=element.enabled,
                    actions=tuple(element.actions),
                )
            )
            self.session.refs[ref] = element
            if text:
                self.texts.append(text)
            if role == "text_area" and value and not secure:
                # A text area's content is on-screen text: extraction and
                # effect verification must be able to see it.
                self.texts.append(str(value)[:1000])
        return False

    def _box(self, bounds: object) -> digest.Box:
        """
        Return the control's window-normalised box.
        """
        if bounds is None:
            # No bounds: a zero box.
            box = digest.Box(0.0, 0.0, 0.0, 0.0)
        else:
            # Normalise the pixel bounds against the window.
            box = digest.Box(
                x=(float(bounds.x) - self._wx) / self._ww,
                y=(float(bounds.y) - self._wy) / self._wh,
                w=float(bounds.width) / self._ww,
                h=float(bounds.height) / self._wh,
            )
        return box


def _name_of(element: xa11y.Element) -> str:
    """
    Return the element's name or description, dropping noise.
    """
    raw = (element.name or element.description or "").strip()
    name = "" if _NOISE.search(raw) else raw
    return name
