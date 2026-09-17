"""
What discovery sends to the observability backend, and the null tracer.

A traced prompt is the windowed conversation with screenshots dropped,
known sensitive values masked by the run's redactor, and personal data
masked by the PII scrubber - in that order.

Import as:

import operant.application.discovery.observe as dsobserv
"""

from __future__ import annotations

import collections.abc
import contextlib
from typing import Any, Dict, List, Optional

import operant.domain.models.llm as llm
import operant.ports.privacy as ppprivac

# #############################################################################
# NoopGeneration
# #############################################################################


class NoopGeneration:
    """
    Implement ``operant.ports.tracing.Generation`` by recording nothing.
    """

    def finish(self, turn: llm.LlmTurn, *, output: Optional[str]) -> None:
        """
        Discard the answer.
        """


# #############################################################################
# NoopTracer
# #############################################################################


class NoopTracer:
    """
    Implement ``operant.ports.tracing.Tracer`` with tracing turned off.
    """

    def generation(
        self, trace: llm.TraceContext, *, model: str, prompt: Optional[Any]
    ) -> contextlib.AbstractContextManager[NoopGeneration]:
        """
        Return a context that traces nothing.
        """
        return contextlib.nullcontext(NoopGeneration())

    def score(
        self, *, trace_id: str, name: str, value: float, comment: str = ""
    ) -> None:
        """
        Discard the score.
        """

    def flush(self) -> None:
        """
        Do nothing: nothing is buffered.
        """


def traced_prompt(
    messages: collections.abc.Sequence[llm.ChatMessage],
    *,
    redact: collections.abc.Callable[[str], str],
    scrubber: Optional[ppprivac.TextScrubber],
) -> List[Dict[str, str]]:
    """
    Render a call's messages as role/content pairs safe to trace.

    :param messages: the messages sent to the model.
    :param redact: masks the run's known secret and sensitive values.
    :param scrubber: masks personal data, when one is configured.
    :return: one ``{"role", "content"}`` dict per message.
    """
    rendered: List[Dict[str, str]] = []
    for message in messages:
        if isinstance(message.content, str):
            # Plain text: system prompt or a tool reply.
            text = message.content
        else:
            # Screen turn: keep the text, never the screenshot bytes.
            text = "\n".join(
                part.text if part.type == "text" else "[screenshot]"
                for part in message.content
            )
        calls = "\n".join(
            f"{call.name}({call.arguments})" for call in message.tool_calls
        )
        joined = "\n".join(chunk for chunk in (text, calls) if chunk)
        safe = redact(joined)
        if scrubber is not None and message.role != "system":
            safe = scrubber.scrub(safe)
        rendered.append({"role": message.role, "content": safe})
    return rendered


def turn_output(turn: llm.LlmTurn) -> str:
    """
    Render a model turn's tool calls (and any text) as traced output.

    :param turn: the model's answer.
    :return: the answer as one string.
    """
    calls = [f"{call.name}({call.arguments})" for call in turn.tool_calls]
    output = "\n".join(chunk for chunk in (turn.content, *calls) if chunk)
    return output
