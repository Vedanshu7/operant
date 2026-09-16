"""
Fast replay timings and bounded waits for tests.

Import as:

import tests.support.timing as timing
"""

from __future__ import annotations

import collections.abc
import time
from typing import Any

import operant.application.replay.options as options


def fast_replay_options(**fields: Any) -> options.ReplayOptions:
    """
    Build replay options whose polls and retries finish at once.

    A scripted surface answers immediately, so the live defaults would
    only make the tests wait.
    """
    timings: dict[str, Any] = {
        "poll_interval_s": 0.01,
        "retry_delay_s": 0.0,
        "goal_poll_s": 0.05,
        "settle_ms": 0,
        "settle_short_ms": 0,
    }
    built = options.ReplayOptions(**{**timings, **fields})
    return built


def wait_until(
    predicate: collections.abc.Callable[[], object], timeout_s: float = 2.0
) -> None:
    """
    Poll ``predicate`` until it is truthy, failing the test on timeout.
    """
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout_s}s")
        time.sleep(0.005)
