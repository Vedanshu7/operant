"""
Browser-tab housekeeping in the macOS window session, with fake a11y
elements - no browser needed.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

pytest.importorskip("xa11y")

# Imported after the skip: the session needs the optional macos extra.
# pylint: disable-next=wrong-import-position
import operant.adapters.macos.session as amsessio  # noqa: E402

pytestmark = pytest.mark.macos


# #############################################################################
# _Element
# #############################################################################


class _Element:

    def __init__(
        self,
        role: str,
        name: str,
        *,
        selected: bool = False,
        children: Optional[List["_Element"]] = None,
    ) -> None:
        self.role = role
        self.name = name
        self.selected = selected
        self._children = children or []
        self.pressed = False

    def children(self) -> List["_Element"]:
        return self._children

    def press(self) -> None:
        self.pressed = True


# #############################################################################
# _App
# #############################################################################


class _App:

    def __init__(self, tabs: List[_Element]) -> None:
        self._tabs = tabs

    def locator(self, selector: str) -> "_App":
        assert selector == "tab"
        return self

    def elements(self) -> List[_Element]:
        return self._tabs


def _tab(name: str, *, selected: bool = False) -> _Element:
    return _Element(
        "tab", name, selected=selected, children=[_Element("button", "Close")]
    )


def test_only_this_apps_background_tabs_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = _tab("Bank | Overview - Memory usage", selected=True)
    stale = _tab("Bank | Welcome - Memory usage")
    other = _tab("CRM | Deals - Memory usage")
    session = amsessio.WindowSession("Google Chrome", "Bank")
    monkeypatch.setattr(
        session, "app", lambda timeout=10.0: _App([active, stale, other])
    )
    assert session.close_stale_tabs() == 1
    closes = [t.children()[0].pressed for t in (active, stale, other)]
    assert closes == [False, True, False]
