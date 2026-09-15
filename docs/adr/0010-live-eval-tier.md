# 10. A live eval tier

Status: Proposed

## Context

The evals (ADR 1) run on synthetic screens: 7 families, 3 app skins, both
agent modes, and a perturbation suite for replay. They measure prompt
rules and safety behaviour cheaply and repeatably. They do not measure
task competence on a real app, and the live ParaBank runs so far are
demos, not scored runs.

Evidence:

- OSWorld scores each task with an initial-state config and a script that
  checks the final state of the real app.
- AndroidWorld parameterises tasks and adds init and teardown; it finds
  task variations change results significantly.
- macOSWorld has 202 macOS tasks over 30 apps, including a deception
  subset. It is the closest public benchmark for an AX-driven macOS agent.

## Decision

Add a third tier, run on demand and never in CI:

- **Tasks.** About 10 ParaBank tasks in Docker, plus 2 or 3 native apps
  (Notes, System Settings). Each task has:
  - parameters (an account, an amount, a note title)
  - an init script that sets the app state through its API or files
    (ParaBank's REST API, a Notes folder)
  - a check script that reads the final state the same way, never the
    agent's own report
- **Runner.** `scripts/live_demo.py` already drives runs over the
  operator API. A `--task-file` mode runs a task list, calls init and
  check, and writes rows in the eval JSONL format, so `eval_report.py`
  scores them, including pass^k, cost and latency.
- **Replay.** Each discovered capability is replayed with a second
  parameter set, scored by the same check. This measures the core claim
  that a capability generalises beyond its discovery inputs.
- **External benchmark.** A macOSWorld subset (the tasks on apps
  installed here) runs later, once the tier exists.

## Consequences

- Real competence numbers next to the synthetic ones, with the same
  report.
- The tier needs an unlocked, idle Mac. The screen lock and person-idle
  checks already pause runs, so it suits an overnight run on a
  dedicated machine (see ADR 11).
- Cost is bounded by the task count; a full pass is roughly 20 to 40
  discoveries.
