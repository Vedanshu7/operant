"""
A one-shot answer a worker thread blocks on and a route fulfils.

Import as:

import operant.server.jobs.pending as pending
"""

from __future__ import annotations

import collections.abc
import threading
from typing import Optional

# #############################################################################
# PendingAnswer
# #############################################################################


class PendingAnswer[T]:
    """
    A value delivered across the thread/async boundary exactly once.

    The worker thread calls ``wait``; the HTTP route calls ``set``. Only
    the first ``set`` takes effect, and none after the wait timed out.

    :ivar id: The question id this answer is registered under.
    """

    def __init__(
        self,
        answer_id: str,
        on_timeout: Optional[collections.abc.Callable[[], None]] = None,
    ) -> None:
        self.id = answer_id
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closed = False
        self._value: Optional[T] = None
        self._on_timeout = on_timeout

    def set(self, value: T) -> bool:
        """
        Deliver ``value`` and wake the waiter.

        :return: Whether the value was taken; ``False`` after an earlier
            answer or after the wait timed out.
        """
        with self._lock:
            accepted = not self._closed and not self._event.is_set()
            if accepted:
                self._value = value
                self._event.set()
        return accepted

    def wait(self, timeout_s: Optional[float]) -> Optional[T]:
        """
        Block until the answer arrives or the timeout lapses.

        :return: The delivered value, or ``None`` on timeout.
        """
        self._event.wait(timeout_s)
        with self._lock:
            # Close under the lock so a late ``set`` cannot slip in.
            answered = self._event.is_set()
            self._closed = not answered
        if answered:
            # Answer arrived: hand back the delivered value.
            value = self._value
        else:
            # Timed out: no answer, and stop holding the registration.
            value = None
            if self._on_timeout is not None:
                self._on_timeout()
        return value
