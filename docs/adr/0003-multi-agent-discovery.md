# 3. Multi-agent discovery with fan-out

Status: Proposed

## Context

Discovery is one agent today: one loop, one prompt, one tool call per
turn. Successful runs took 8 to 14 turns for only 3 to 6 UI actions. Most
turns are bookkeeping, and nothing checks that the goal is really met
before the capability is saved.

Two facts limit any design:

- There is one screen. The control broker allows one driver at a time.
- Replay must stay model-free and deterministic.

## Decision

Split discovery into three roles, run by a deterministic coordinator.

```
coordinator (plain Python, not a model)
  ├─ planner   goal + first screen + app map  → plan of subgoals
  ├─ executor  today's loop, one subgoal at a time  → UI actions
  └─ verifier  subgoal criteria + screen + outputs  → pass or fail
```

- Planner: no UI tools. It returns subgoals, each with success criteria and
  expected outputs, plus the names of inputs and credentials it needs.
  Credential entries are names only.
- Executor: the current prompt and tools. It works on the active subgoal and
  calls `subgoal_done` when it thinks the subgoal is met.
- Verifier: no UI tools and no secrets. It returns a verdict. A fail sends
  the reason back to the executor.
- Replan when the verifier rejects the same subgoal twice, when the
  executor gives up, or when no subgoal makes progress for a set number of
  turns. Escalate to a human when the replan budget runs out.
- Only the executor touches the screen and the secrets channel. The planner
  and verifier see redacted views (ADR 5, ADR 7).
- Only executor actions are recorded. The plan is evidence, not part of the
  artifact. Replay and the artifact schema do not change.
- A setting picks the mode: `OPERANT_DISCOVERY__AGENTS` is `single`
  (default) or `multi`.

### Fan-out rule

Anything that touches the screen runs one at a time. Anything that only
reads state the run already captured can run in parallel.

| Where | Runs in parallel | How results combine |
|---|---|---|
| Subgoal check | A verifier panel: outputs vs criteria, a safety auditor, a leak auditor | All must pass |
| Planning (optional) | K plan candidates | A fixed rule picks one |
| Extract | N candidate regexes | Code checks each against the screen text |
| After goal_complete | One locator critic per recorded step, plus a schema reviewer | Advisory events only |
| Evals and GEPA | Scenario × skin × mode × trial | A worker pool |

Never fanned out: executor actions, approvals, credential requests.

One helper, `application/fanout.py`, runs parallel work on a thread pool.
Results come back in input order, so evidence stays deterministic. A failed
worker becomes an error result, not a crash. Fan-out width and the model
for each panel are settings.

### Decision gate

Every eval scenario runs in both modes (ADR 1). The default switches to
`multi` only if its pass rate is at least as good on every scenario family
and better on multi-step tasks. The cost difference is reported with it.

## Consequences

- Each subgoal is checked before the run moves on, so a premature
  `goal_complete` no longer saves a wrong capability.
- More model calls per run. The verifier panel and critics use the cheap
  model to keep cost bounded.
- More prompts to keep in line. Each has its own evals and can be tuned by
  GEPA (ADR 4).

## Alternatives considered

- An LLM supervisor that routes between agents. Rejected: it adds
  non-determinism to the control flow and is harder to test.
- Parallel executors. Rejected: there is one screen and one driver.
- Stay single-agent and add only a verifier call. Still possible: the
  `single` mode stays, and the evals decide.
