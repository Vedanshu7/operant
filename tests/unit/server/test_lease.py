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


def test_a_lease_in_another_process_holds_the_screen(tmp_path) -> None:
    lock_file = tmp_path / "screen.lock"
    other_process = jllease.DriverLease(lock_file)
    other_process.acquire("cli-run")
    lease = jllease.DriverLease(lock_file)
    acquired = threading.Event()

    def take() -> None:
        lease.acquire("server-run")
        acquired.set()

    worker = threading.Thread(target=take)
    worker.start()
    assert not acquired.wait(0.3)
    other_process.release("cli-run")
    assert acquired.wait(2.0)
    lease.release("server-run")
    worker.join()
