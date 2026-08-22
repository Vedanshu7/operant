"""
The driver lease serialises runs and reports queue position.
"""

from __future__ import annotations

import threading

import operant.server.jobs.lease as jllease


def test_single_holder_blocks_until_release() -> None:
    lease = jllease.DriverLease()
    lease.acquire("a")
    assert lease.position("a") == 0
    acquired = threading.Event()

    def take_b() -> None:
        lease.acquire("b")
        acquired.set()

    worker = threading.Thread(target=take_b)
    worker.start()
    assert not acquired.wait(0.2)
    assert lease.position("b") == 1

    lease.release("a")
    assert acquired.wait(1.0)
    assert lease.position("b") == 0
    lease.release("b")
    worker.join()


def test_not_waiting_returns_minus_one() -> None:
    lease = jllease.DriverLease()
    assert lease.position("ghost") == -1
