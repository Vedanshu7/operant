"""
The observability port: record model calls as generations in a trace.

Import as:

import operant.ports.tracing as pttracin
"""

from __future__ import annotations

import contextlib
from typing import Any, Optional, Protocol, runtime_checkable

import operant.domain.models.llm as llm

# #############################################################################
# Generation
# #############################################################################


@runtime_checkable
class Generation(Protocol):
    """
    One in-flight model call being traced.
    """

    def finish(self, turn: llm.LlmTurn, *, output: Optional[str]) -> None:
        """
        Record the call's answer, model and token usage.

        :param turn: What the model answered.
        :param output: The answer as traced text, or ``None`` to omit
            it.
        """
        ...


# #############################################################################
# Tracer
# #############################################################################


@runtime_checkable
class Tracer(Protocol):
    """
    Send model calls and eval scores to an observability backend.
    """

    def generation(
        self, trace: llm.TraceContext, *, model: str, prompt: Optional[Any]
    ) -> contextlib.AbstractContextManager[Generation]:
        """
        Open a generation around one model call.

        :param trace: Where the call belongs.
        :param model: The model id being called.
        :param prompt: The already redacted prompt, or ``None`` to omit
            it.
        :return: A context manager yielding the open generation.
        """
        ...

    def score(
        self, *, trace_id: str, name: str, value: float, comment: str = ""
    ) -> None:
        """
        Attach a numeric score (1.0/0.0 for pass/fail) to a trace.

        :param trace_id: The trace to score.
        :param name: Score name, e.g. ``passed``.
        :param value: The score.
        :param comment: Optional explanation.
        """
        ...

    def flush(self) -> None:
        """
        Send everything buffered before the process moves on.
        """
        ...
