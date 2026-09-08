"""
Langfuse tracer tests against an in-memory span exporter - no server.
"""

from __future__ import annotations

import pytest

import operant.domain.models.llm as llm

langfuse = pytest.importorskip("langfuse")
export = pytest.importorskip(
    "opentelemetry.sdk.trace.export.in_memory_span_exporter"
)

# Imported after the skips: the module needs the optional langfuse extra.
# pylint: disable-next=wrong-import-position
import operant.adapters.observability.langfuse_tracer as aolangtr  # noqa: E402


def _tracer(content: str) -> tuple:
    exporter = export.InMemorySpanExporter()
    client = langfuse.Langfuse(
        # The SDK keeps one client per public key; isolate each test.
        public_key=f"pk-{content}",
        secret_key="sk-test",
        host="http://localhost:9",
        span_exporter=exporter,
    )
    return aolangtr.LangfuseTracer(client, content=content), exporter


_TRACE = llm.TraceContext(
    trace_id="0" * 31 + "1",
    session_id="run-1",
    trace_name="discovery:cap",
    generation_name="executor-turn-1",
    tags=("evalapp",),
)
_TURN = llm.LlmTurn(model="m", input_tokens=11, output_tokens=3)


def test_a_generation_is_exported_under_the_run_trace() -> None:
    tracer, exporter = _tracer("scrubbed")
    with tracer.generation(_TRACE, model="m", prompt=[{"role": "user"}]) as gen:
        gen.finish(_TURN, output="act({})")
    tracer.flush()
    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["executor-turn-1"]
    assert format(spans[0].context.trace_id, "032x") == _TRACE.trace_id
    attributes = dict(spans[0].attributes or {})
    assert any("act({})" in str(v) for v in attributes.values())


def test_metadata_mode_sends_no_prompt_or_output() -> None:
    tracer, exporter = _tracer("metadata")
    with tracer.generation(_TRACE, model="m", prompt=[{"secret": "x"}]) as gen:
        gen.finish(_TURN, output="act({})")
    tracer.flush()
    attributes = dict(exporter.get_finished_spans()[0].attributes or {})
    assert not any("act({})" in str(v) for v in attributes.values())
    assert not any('"secret"' in str(v) for v in attributes.values())
