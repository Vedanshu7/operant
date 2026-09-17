"""
Run independent, screen-free work in parallel and keep results in order.

Only work that reads state the run already captured may fan out - never
an action, an approval, or a credential request: there is one screen and
one driver. Results come back in input order so evidence stays
deterministic, and a failed task becomes an error result instead of
failing the run.

Import as:

import operant.application.fanout as fanout
"""

from __future__ import annotations

import collections.abc
import concurrent.futures
import dataclasses
from typing import Generic, List, Optional, TypeVar

_T = TypeVar("_T")


# #############################################################################
# Outcome
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Outcome(Generic[_T]):
    """
    What one fanned-out task produced.

    :ivar value: the task's result, when it succeeded.
    :ivar error: why it failed, when it did.
    """

    value: Optional[_T] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """
        Whether the task succeeded.
        """
        return self.error is None


def run(
    tasks: collections.abc.Sequence[collections.abc.Callable[[], _T]],
    *,
    max_workers: int,
    timeout_s: Optional[float] = None,
) -> List[Outcome[_T]]:
    """
    Run ``tasks`` on a thread pool and return their outcomes in order.

    :param tasks: zero-argument callables; each must be screen-free.
    :param max_workers: upper bound on parallel tasks (1 runs serially).
    :param timeout_s: per-task wait bound; a task that exceeds it is
        reported as an error (it is not killed).
    :return: one outcome per task, in input order.
    """
    outcomes: List[Outcome[_T]] = []
    if tasks:
        workers = max(1, min(max_workers, len(tasks)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(task) for task in tasks]
            for future in futures:
                outcomes.append(_collect(future, timeout_s))
    return outcomes


def _collect(
    future: concurrent.futures.Future[_T], timeout_s: Optional[float]
) -> Outcome[_T]:
    """
    Wait for one future and wrap its result or failure.
    """
    try:
        outcome: Outcome[_T] = Outcome(value=future.result(timeout=timeout_s))
    except concurrent.futures.TimeoutError:
        outcome = Outcome(error=f"timed out after {timeout_s}s")
    # A failed task is reported, never raised: it must not fail the run.
    except Exception as err:
        outcome = Outcome(error=f"{type(err).__name__}: {err}")
    return outcome
