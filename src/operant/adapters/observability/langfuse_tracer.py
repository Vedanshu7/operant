"""
Trace model calls to Langfuse as generations, one trace per run.

The prompt arrives already redacted and scrubbed by the caller; with the
``metadata`` content mode it is not sent at all.

Import as:

import operant.adapters.observability.langfuse_tracer as aolangtr
"""

from __future__ import annotations

import collections.abc
import contextlib
from typing import Any, Optional

import langfuse

import operant.domain.models.llm as llm

# #############################################################################
# LangfuseGeneration
# #############################################################################


class LangfuseGeneration:
    """
    Implement ``operant.ports.tracing.Generation`` over a Langfuse span.
    """

    def __init__(self, span: Any, *, content: str) -> None:
        self._span = span
        self._content = content

    def finish(self, turn: llm.LlmTurn, *, output: Optional[str]) -> None:
        """
        Record the answer, model and usage on the generation.
        """
        self._span.update(
            output=output if self._content == "scrubbed" else None,
            model=turn.model or None,
            usage_details={
                "input": turn.input_tokens,
                "output": turn.output_tokens,
            },
        )


# #############################################################################
# LangfuseTracer
# #############################################################################


class LangfuseTracer:
    """
    Implement ``operant.ports.tracing.Tracer`` with the Langfuse SDK.
    """

    def __init__(self, client: langfuse.Langfuse, *, content: str) -> None:
        """
        Wrap a configured client.

        :param client: the Langfuse client.
        :param content: ``"scrubbed"`` or ``"metadata"``.
        """
        self._client = client
        self._content = content

    @contextlib.contextmanager
    def generation(
        self, trace: llm.TraceContext, *, model: str, prompt: Optional[Any]
    ) -> collections.abc.Iterator[LangfuseGeneration]:
        """
        Open a generation under the run's trace and session.
        """
        # The SDK returns an OpenTelemetry context manager pylint can't see.
        # pylint: disable-next=not-context-manager
        with langfuse.propagate_attributes(
            session_id=trace.session_id,
            tags=list(trace.tags),
            trace_name=trace.trace_name,
            metadata={"agent": trace.agent},
        ):
            with self._client.start_as_current_observation(
                trace_context={"trace_id": trace.trace_id},
                name=trace.generation_name,
                as_type="generation",
                input=prompt if self._content == "scrubbed" else None,
                model=model,
                metadata={"agent": trace.agent},
            ) as span:
                yield LangfuseGeneration(span, content=self._content)

    def score(
        self, *, trace_id: str, name: str, value: float, comment: str = ""
    ) -> None:
        """
        Attach a numeric score to a trace.
        """
        self._client.create_score(
            name=name,
            value=value,
            trace_id=trace_id,
            data_type="NUMERIC",
            comment=comment or None,
        )

    def flush(self) -> None:
        """
        Send buffered spans and scores.
        """
        self._client.flush()
