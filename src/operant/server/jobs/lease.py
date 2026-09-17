"""
A single-holder lease serialising runs that need the one driver session.

The macOS driver drives one live window at a time, so only one run may
hold it. Waiters queue in arrival order; a run reports
``waiting_driver`` until it acquires the lease. The holder also takes an
OS file lock, so a run in another process (a CLI replay, a second
server) waits too instead of driving the same screen.

Import as:

import operant.server.jobs.lease as jllease
"""

from __future__ import annotations

import pathlib
import threading
from typing import List, Optional

import filelock

# #############################################################################
# DriverLease
# #############################################################################


class DriverLease:
    """
    A fair, blocking, single-holder lease.
    """

    def __init__(self, screen_lock: Optional[pathlib.Path] = None) -> None:
        """
        Set up the lease.

        :param screen_lock: the lock file shared with other processes
            that drive the screen; ``None`` locks within this process
            only.
        """
        self._screen = (
            filelock.FileLock(str(screen_lock)) if screen_lock else None
        )
        self._lock = threading.Lock()
        self._holder: Optional[str] = None
        self._waiters: List[str] = []
        self._cond = threading.Condition(self._lock)

    def position(self, run_id: str) -> int:
        """
        Return queue place (0 = holding, -1 = not waiting).
        """
        with self._lock:
            if self._holder == run_id:
                # This run holds the lease: it sits at the head.
                place = 0
            elif run_id in self._waiters:
                # Waiting: report its one-based place in the queue.
                place = self._waiters.index(run_id) + 1
            else:
                # Neither holding nor queued.
                place = -1
            return place

    def acquire(self, run_id: str) -> None:
        """
        Block until ``run_id`` holds the lease.
        """
        with self._cond:
            self._waiters.append(run_id)
            while self._holder is not None or self._waiters[0] != run_id:
                self._cond.wait()
            self._waiters.pop(0)
            self._holder = run_id
        if self._screen is not None:
            # Wait for a run in another process to finish with the screen.
            self._screen.acquire()

    def release(self, run_id: str) -> None:
        """
        Release the lease if ``run_id`` holds it and wakes waiters.
        """
        with self._cond:
            if self._holder == run_id:
                if self._screen is not None:
                    self._screen.release()
                self._holder = None
                self._cond.notify_all()
