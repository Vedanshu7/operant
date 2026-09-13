"""
Browser-tab housekeeping in the macOS window session, with fake a11y
elements - no browser needed.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

import operant.domain.models.actions as actions
import operant.domain.models.tools as tools
import operant.infra.settings as settings

pytest.importorskip("xa11y")

# Imported after the skip: the session needs the optional macos extra.
# pylint: disable-next=wrong-import-position
import operant.adapters.macos.session as amsessio  # noqa: E402

# pylint: disable-next=wrong-import-position
import operant.adapters.macos.tools.launcher as launcher  # noqa: E402

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


def test_a_locked_screen_fails_the_window_lookup_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = amsessio.WindowSession("Google Chrome", "Bank")
    monkeypatch.setattr(amsessio, "screen_locked", lambda: True)
    # Resolving the app at all would mean a search had started.
    monkeypatch.setattr(session, "app", pytest.fail)
    with pytest.raises(TimeoutError, match="screen is locked"):
        session.window(timeout=30.0)


def test_screen_lock_reads_the_console_session() -> None:
    assert isinstance(amsessio.screen_locked(), bool)


def test_a_locked_screen_refuses_a_launch_without_opening_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(amsessio, "screen_locked", lambda: True)
    monkeypatch.setattr(launcher.subprocess, "run", pytest.fail)
    monkeypatch.setattr(launcher.subprocess, "Popen", pytest.fail)
    tool = launcher.AppLauncher(
        amsessio.WindowSession("Google Chrome", "Bank"),
        settings.BrowserSettings(),
        tmp_path,
    )
    result = tool.execute(
        actions.SurfaceAction(
            kind="launch", app="Google Chrome", url="http://localhost/"
        ),
        tools.ExecutionContext(session=None),
    )
    assert result.status == "failed"
    assert "screen is locked" in (result.reason or "")


def test_an_action_waits_while_a_person_uses_the_mac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idle = iter([0.5, 1.0, 4.0])
    monkeypatch.setattr(
        amsessio, "seconds_since_person_input", lambda: next(idle)
    )
    monkeypatch.setattr(amsessio.time, "sleep", lambda s: None)
    amsessio.WindowSession("Google Chrome", "Bank").wait_for_person_idle()
    assert next(idle, None) is None


def test_a_person_who_keeps_working_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter(range(0, 10_000, 60))
    monkeypatch.setattr(amsessio, "seconds_since_person_input", lambda: 0.1)
    monkeypatch.setattr(amsessio.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(amsessio.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="person kept using"):
        amsessio.WindowSession("Google Chrome", "Bank").wait_for_person_idle()


def test_person_input_time_is_read_from_the_os() -> None:
    assert amsessio.seconds_since_person_input() >= 0
