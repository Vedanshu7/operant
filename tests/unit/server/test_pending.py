"""
The pending answer bridges a blocked worker to an async route.
"""

from __future__ import annotations

import threading

import operant.server.jobs.pending as pending


def test_set_then_wait_returns_value() -> None:
    answer: pending.PendingAnswer[str] = pending.PendingAnswer("id")
    answer.set("yes")
    assert answer.wait(0.1) == "yes"


def test_first_set_wins() -> None:
    answer: pending.PendingAnswer[str] = pending.PendingAnswer("id")
    answer.set("first")
    answer.set("second")
    assert answer.wait(0.1) == "first"


def test_timeout_returns_none() -> None:
    answer: pending.PendingAnswer[str] = pending.PendingAnswer("id")
    assert answer.wait(0.05) is None


def test_wait_unblocks_when_set_from_another_thread() -> None:
    answer: pending.PendingAnswer[str] = pending.PendingAnswer("id")

    def deliver() -> None:
        answer.set("later")

    threading.Timer(0.05, deliver).start()
    assert answer.wait(1.0) == "later"
