# 5. Agent memory layer

Status: Accepted (implemented)

## Context

Operant already has some memory:

- Chat history (`DiscoveryState.messages`): the full conversation, sent in
  full every turn and never compacted.
- App map (`known_graph`): screens and steps already mapped, shown to the
  model as a "recognized state" hint.
- Remediation memory: situation plus error mapped to a fix, given as a hint
  after an error.
- Learned tools: which tool worked best for each kind of screen, used by
  code only.
- The evidence log: kept, but never fed back to the model.

Multi-agent discovery (ADR 3) needs each role to see the right state, and
needs runs to learn from earlier runs.

## Decision

Two layers: a blackboard for each run and a store that lasts across runs.

### Per-run blackboard

- The coordinator owns it: plan, subgoal status, verdicts, inputs, outputs,
  and a short step log.
- Each role gets its own view, never another role's chat:
  - Planner: goal, redacted screen, app map, recalled plans.
  - Executor: active subgoal, remaining subgoals, recalled lessons,
    remediation hints.
  - Verifier: criteria, screen after the step, outputs, last few steps.
- When a subgoal passes, its turns collapse into one summary line in the
  executor's history.

### Cross-run memory

- Storage: two new tables in the existing SQLite database, added through
  Alembic.
  - Plan memory: a plan that worked, keyed by app and normalized goal.
  - Lessons: mistakes the verifier rejected, or a note from a person after
    an intervention.
- Retrieval: exact key first, then keyword overlap, always within the same
  app. At most 2 plans and 3 lessons per call.
- Ranking: successes minus failures, then recency. Stale entries are
  skipped.
- Everything recalled is advisory. The live screen always wins.
- Remediation memory stays as it is. Lessons cover semantic mistakes;
  remediation covers step errors.

### Safety

- Every text field passes the redactor and the PII scrubber (ADR 7) before
  it is written.
- Plans keep input and credential names, never values.
- Memory is scoped per app. There is no recall across apps.
- `operant audit` checks that no stored text matches a value the redactor
  knows.

## Consequences

- Repeat goals on the same app should need fewer turns.
- Stale or wrong memory is a risk. An eval checks that stale memory loses
  to the live screen.
- Memory stays local, deterministic, and easy to audit.

## Alternatives considered

- Embeddings with sqlite-vec. Rejected for now: adds a dependency, a cost
  per write, and less predictable recall. Can be added later behind the
  same port.
- A managed memory service such as Mem0. Rejected: memory would leave the
  process, and redaction and scoping become hard to prove.

## Implementation notes

- Code: `application/memory.py`, `ports/memory.py`,
  `infra/repositories/memory.py`, migration `0002_agent_memory`.
- Memory is used by multi-agent runs only (`OPERANT_DISCOVERY__MEMORY`).
- Numbers and amounts are masked as `<n>` before storage, on top of
  redaction and scrubbing, so goals and plans keep no record ids.
- The audit check is shape-based: evidence logs are already redacted, so
  it flags any stored text with unmasked numbers or sensitive value
  shapes (IBAN, SSN, email).
- History compaction happens per verified subgoal, so it applies to
  multi-agent runs only; single-agent runs rely on the context layer
  (ADR 6).
