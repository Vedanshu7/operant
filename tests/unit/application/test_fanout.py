"""
Fan-out tests: results keep input order, failures become error results.
"""

from __future__ import annotations

import functools
import threading
import time

import operant.application.fanout as fanout


def test_results_come_back_in_input_order() -> None:
    def slow(value: int) -> int:
        time.sleep(0.01 * (3 - value))
        return value

    outcomes = fanout.run(
        [functools.partial(slow, v) for v in range(3)], max_workers=3
    )
    assert [o.value for o in outcomes] == [0, 1, 2]


def test_a_failing_task_is_an_error_not_a_crash() -> None:
    def boom() -> int:
        raise RuntimeError("nope")

    outcomes = fanout.run([boom, lambda: 7], max_workers=2)
    assert not outcomes[0].ok and "nope" in (outcomes[0].error or "")
    assert outcomes[1].ok and outcomes[1].value == 7


def test_tasks_run_in_parallel() -> None:
    barrier = threading.Barrier(3, timeout=2)
    outcomes = fanout.run([barrier.wait] * 3, max_workers=3)
    assert all(o.ok for o in outcomes)


def test_no_tasks_means_no_outcomes() -> None:
    assert fanout.run([], max_workers=4) == []
