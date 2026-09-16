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
- Memory was first used by multi-agent runs only; `OPERANT_DISCOVERY__MEMORY`
  now picks `all`, `multi` or `off` (see the revision below).
- Numbers and amounts are masked as `<n>` before storage, on top of
  redaction and scrubbing, so goals and plans keep no record ids.
- The audit check is shape-based: evidence logs are already redacted, so
  it flags any stored text with unmasked numbers or sensitive value
  shapes (IBAN, SSN, email).
- History compaction happens per verified subgoal, so it applies to
  multi-agent runs only; single-agent runs rely on the context layer
  (ADR 6).

## Revision 1 (2026-10-22): keep conclusions, not reactions

### Why

A review against the live database found the cross-run layer worked
poorly:

- All 11 stored lessons were verifier rejections saved on the spot,
  including rejections the run went on to pass. Some came from verifier
  bugs that were later fixed. None said what to do instead.
- Recall marked plans as used, so a plan that kept failing never went
  stale.
- Lessons had no relevance cut-off: the top three reached the planner
  even for an unrelated goal.
- Near-duplicate lessons piled up; only identical text merged.
- Nothing tied memory to the app version.
- Verifier reasons can quote screen text, so a page could plant an
  instruction that every later run replays (the AgentPoison and MINJA
  attack class).
- Tool-learner keys held record values and the model's wording, and one
  success replaced the stored choice.

The fixes follow ExpeL (lessons from a failure contrasted with what
worked), Mem0 (consolidate on write), Generative Agents (relevance x
recency x importance) and the memory-poisoning literature.

### Decision

- **Decided at run end.** Rejections wait on the blackboard:
  - Rejected once, then verified: a misjudgement; nothing is kept.
  - Rejected repeatedly, then verified: kept, with what finally worked.
  - Still rejected when the run failed: kept as unresolved.
  - The loop calls `Team.conclude` however the run ends.
- **One shape.** `On "<subgoal>": <failure kind>. What worked: <...>.`
  The failure kind is a code (`not_done`, `wrong_output`,
  `unsafe_step`, `credential_leak`, `no_verdict`); the model's reasons
  are not stored.
- **Consolidation.** The same failure kind on the same subgoal reinforces
  one lesson, and its "what worked" is replaced by the latest.
- **Recall reads only.** Lessons need relevance 0.3 or more to the goal
  and rank by relevance x recency (30-day half-life) x
  (1 + reinforcements), doubled for a person's note.
- **Plans.** A plan that failed twice more than it worked, or has not
  worked in 90 days, is not recalled.
- **App version.** Plans and lessons record the app graph version.
  Items from another version rank lower (lessons at half weight).
- **Poisoning.** Only the person's words after "Note:" are kept from an
  intervention, with instruction-like lines and links dropped. Recall
  is framed as "data, not instructions".
- **Tool learner.**
  - Keys use the control's role and name with digits masked, or
    `point` for a coordinate click.
  - Keys without an app are never learned.
  - Each tool's worked/failed counts order the chain by smoothed
    success rate.
  - The old flat file is discarded.
- **Remediation.**
  - A hinted remedy followed by the same error counts as a failure.
  - A remedy that failed twice more than it worked is no longer offered.
  - Hints keep no numbers.
- **Visibility.** `operant memory list|forget|prune` and
  `GET /api/v1/memory`.
- **Single mode.** A single agent also gets the recall block
  (`OPERANT_DISCOVERY__MEMORY=all`, the default). In the memory
  eval, 3 skins × 3 trials of a transfer flow, a recalled plan cut the
  turns in every skin: 14.3 to 13.7, 14.7 to 13.0, and 15.0 to 14.0. All
  runs completed, and stale memory still lost to the screen.

### Migration

- `0003_memory_quality` adds `graph_version` and the lesson key columns.
- It deletes the lessons recorded under the old rule (`source =
  'verifier'`) and keeps a person's notes.
