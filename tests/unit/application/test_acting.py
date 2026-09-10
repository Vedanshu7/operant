"""
Settle tests: after a navigating action the recorded screen is the page that
loaded, not the one still showing while it loaded.
"""

from __future__ import annotations

import time
from typing import List

import operant.application.acting as acting
import operant.domain.models.digest as digest

_FAST = acting.SettlePolicy(poll_s=0.01, change_window_s=0.1, max_s=1.0)


def _screen(title: str) -> digest.ScreenDigest:
    return digest.ScreenDigest(app="App", window_title=title, text=title)


# #############################################################################
# _SequenceSurface
# #############################################################################


class _SequenceSurface:
    """
    Return scripted screens in order, repeating the last one.
    """

    def __init__(self, screens: List[digest.ScreenDigest]) -> None:
        self._screens = list(screens)
        self.reads = 0

    def snapshot(self) -> digest.ScreenDigest:
        self.reads += 1
        shown = (
            self._screens[0] if len(self._screens) == 1 else self._screens.pop(0)
        )
        return shown


def test_a_slow_page_load_is_read_once_it_has_loaded() -> None:
    old, new = _screen("Login"), _screen("Overview")
    surface = _SequenceSurface([old, old, old, new, new])
    assert acting.settled_snapshot(surface, old, _FAST).window_title == "Overview"


def test_an_action_that_does_not_navigate_stops_waiting() -> None:
    page = _screen("Form")
    surface = _SequenceSurface([page])
    started = time.monotonic()
    assert acting.settled_snapshot(surface, page, _FAST) == page
    assert time.monotonic() - started < 0.5


def test_an_immediate_change_returns_after_one_steady_read() -> None:
    old, new = _screen("A"), _screen("B")
    surface = _SequenceSurface([new, new])
    assert acting.settled_snapshot(surface, old, _FAST) == new
    assert surface.reads == 2
