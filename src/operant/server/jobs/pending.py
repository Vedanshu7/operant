"""
A one-shot answer a worker thread blocks on and a route fulfils.

Import as:

import operant.server.jobs.pending as pending
"""

from __future__ import annotations

import threading
from typing import Optional

# #############################################################################
# PendingAnswer
# #############################################################################


class PendingAnswer[T]:
    """
    A value delivered across the thread/async boundary exactly once.

    The worker thread calls ``wait``; the HTTP route calls ``set``. Only
    the first ``set`` takes effect.

    :ivar id: The question id this answer is registered under.
    """

    def __init__(self, answer_id: str) -> None:
        self.id = answer_id
        self._event = threading.Event()
        self._value: Optional[T] = None

    def set(self, value: T) -> None:
        """
        Deliver ``value`` and wakes the waiter; later calls are ignored.
        """
        if not self._event.is_set():
            self._value = value
            self._event.set()

    def wait(self, timeout_s: Optional[float]) -> Optional[T]:
        """
        Block until the answer arrives or the timeout lapses.

        :return: The delivered value, or ``None`` on timeout.
        """
        if self._event.wait(timeout_s):
            # Answer arrived: hand back the delivered value.
            value = self._value
        else:
            # Timed out: no answer.
            value = None
        return value
