# 2. Langfuse for model observability

Status: Accepted (implemented)

## Context

Today the JSONL evidence log is the only record of a run. It shows what the
agent did, but not the model calls behind it: the exact prompt, tokens,
cost, and latency per turn. A Jaeger service exists in compose under the
`tracing` profile, but nothing exports to it.

Evals (ADR 1), multi-agent discovery (ADR 3), and prompt optimization
(ADR 4) all need to compare model behaviour across runs, models, and
prompt versions.

## Decision

Use Langfuse, self-hosted, as the model observability backend.

- Setting: `OPERANT_OBSERVABILITY__BACKEND` is `none` (default) or
  `langfuse`. Keys come from `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
- Content: `OPERANT_OBSERVABILITY__CONTENT` is `scrubbed` (default) or
  `metadata`. `metadata` sends model, usage, and tags only.
- The litellm adapter wraps each completion in a Langfuse SDK generation.
  The input and output pass through the redactor and the PII scrubber
  (ADR 7) before they are sent.
- A new `TraceContext` travels with each model call: trace id, session id,
  trace name, generation name, tags, and agent role.
- One trace per discovery run. The session id is the run id. The trace id
  is written to the `discovery_started` evidence event, so the evidence log
  links to Langfuse.
- `LlmTurn` gains input and output token counts.
- Evals tag traces with the scenario, mode, model, and prompt hash, and
  attach a `passed` score plus one score per check.
- Compose: the Langfuse stack (web, worker, Postgres, ClickHouse, Redis,
  MinIO) replaces the unused Jaeger service under a new `observability`
  profile. Only port 3000 is exposed. `LANGFUSE_INIT_*` variables create the
  org, project, user, and API keys on first boot.

## What leaves the process

- Secret values: never. The model only ever sees `$secret:<name>`.
- Screen text: yes, after exact redaction and PII scrubbing, unless the
  content mode is `metadata`.
- Self-hosting keeps all of it on your own machine.

## Consequences

- Each model call becomes visible with its cost and latency.
- Single-agent and multi-agent runs can be compared side by side.
- The compose stack is heavy. It is opt-in behind a profile.
- The adapter owns a little more code than a one-line callback.

## Alternatives considered

- The litellm `langfuse_otel` callback. Rejected: it ships messages before
  we can scrub them.
- Langfuse Cloud. Rejected for now: screen text from bank apps should stay
  local.
- Wire OpenTelemetry to the existing Jaeger stub. Rejected: Jaeger shows
  spans, not prompts, tokens, cost, or eval scores.

## Implementation notes

- The `LlmClient` port is unchanged. A separate `Tracer` port
  (`ports/tracing.py`) wraps each model call in the loop, which owns the
  run's redactor, so it can redact and scrub before anything is traced.
  Adapter: `adapters/observability/langfuse_tracer.py` (Langfuse SDK v5).
- Settings: `OPERANT_OBSERVABILITY__BACKEND` (`none`/`langfuse`),
  `__HOST`, `__CONTENT` (`scrubbed`/`metadata`).
- Optional extra: `observability`.
