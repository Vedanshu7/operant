# 1. Eval harness and repeated trials

Status: Accepted (implemented)

## Context

The evals in `tests/evals/` run discovery against the real model over
synthetic screens. They check whether the model follows the rules in the
system prompt. A review of the harness found it cannot be trusted yet:

- A `give_up` hangs the eval forever. It raises a human intervention, and
  `ControlBroker.raise_intervention` waits with no timeout. Nothing in the
  harness answers it.
- The fake surface skips the policy and approval gate. The gate lives in
  `Surface.perform`, so the eval approver is never asked. Approval and
  denial rules cannot be tested.
- In profile mode the entry launch moves the fake to the next screen. A
  multi-screen scenario would start one screen late.
- "Never invent URLs" cannot be tested in profile mode. The entry launch is
  automatic, so the model never picks a URL.
- Some checks pass on bad behaviour. The logged-in check accepts any `act`,
  even a click on "Log Out". The recognized-state test never checks that
  the hint reached the model.
- The credential check does not prove the key rule. It never checks that
  the password was filled with `$secret:<name>`, or that the value never
  reached the model.
- Only 3 of about 11 prompt rules are covered.
- Each eval runs once. The model is not deterministic, so one pass or fail
  says little.
- No results are kept, so prompt changes cannot be compared.

## Decision

Rewrite the harness and grow the scenario set.

- Surface: `EvalSurface` extends `GatedFakeSurface`, so every action passes
  the real policy and approval protocol.
- Screens: a `Scene` names its screens, a start screen, and transitions
  keyed by control ref or action kind. The entry launch stays on the start
  screen. In bootstrap mode the surface has no window until the first
  launch.
- Broker: an eval broker answers any intervention with "abandoned" at
  once. A `give_up` ends the run instead of hanging.
- Fakes: reuse `FakeApprover` (approve or deny per scenario),
  `FakeClarifier`, and the screen builders in `tests/support/`.
- Checks return a list of failure strings instead of asserting. This lets
  trials be counted.
- Trials: each scenario runs N times (`OPERANT_EVAL_TRIALS`, default 3) and
  must reach a pass rate (`OPERANT_EVAL_PASS_RATE`, default 0.67).
- Results: each trial writes one JSONL row to `state/evals/`. The row holds
  the scenario, mode, pass or fail, failures, tool trace, turns, tokens,
  model, and a hash of the prompt.
- Skins: each scenario runs over three app skins (bank, CRM, HR portal) so
  a rule is not only proven on ParaBank wording.
- Self-tests: the harness itself is tested in CI with a scripted model. A
  good trace must pass and a bad trace must fail.

Scenarios:

- Auth: already logged in, recognized state, login uses `request_secret`.
- Grounding (bootstrap mode): ask for a missing URL, launch with the URL
  only.
- Inputs and outputs: a read value is an output, a typed value is an input,
  a dropdown uses `select`.
- Safety: a mutating step asks for approval, a denied step is not retried.
- Multi-step: a full transfer flow, and a premature `goal_complete` that
  must not succeed.
- Global, on every trial: one tool call per turn, and no secret value in
  any message sent to the model.

## Consequences

- Eval results become a number with a history, not a single pass or fail.
- A full eval run costs more model calls (scenarios × skins × trials).
  Evals stay opt-in and never run in CI.
- The harness now shares fakes with the unit tests, so a change to the
  gate is tested in both places.

## Alternatives considered

- Keep single runs and loosen nothing. Rejected: one run of a
  non-deterministic model cannot catch a regression reliably.
- Record and replay model responses. Rejected for evals: it tests the
  recording, not the current prompt. It is still useful for unit tests.

## Implementation notes

- Code: `tests/evals/` (`harness.py`, `scenes.py`, `catalog.py`, one test
  file per family). Self-tests: `tests/unit/evals/`.
- Every scenario also runs in both agent modes (`OPERANT_EVAL_MODES`,
  default `single,multi`), so the multi-agent decision gate (ADR 3) reads
  straight from the summary table.
- A global check fails any trial whose traced text holds a person's name
  while a PII scrubber is configured (ADR 7).
- The read-only scenarios also require `goal_complete`: an early live run
  looped on `extract` until the turn budget and still passed.
- The first live run showed the model batching several tool calls in one
  turn; `one_call_per_turn` catches it.
- Trajectory metrics (`tests/evals/trajectory.py`) score how a run got
  there, not only whether it passed. Each scenario has a minimal reference
  trajectory; every trial records in-order recall, precision, efficiency
  (reference steps / steps taken) and whether all reference steps came in
  order. In multi-agent mode, each verifier verdict on a `goal_complete`
  claim is labelled a true or false accept or reject against the window it
  was made on. These are metrics, not checks, so pass rates stay
  comparable across runs. They are also sent to Langfuse as `traj:*`
  scores.
- `scripts/eval_report.py` turns result files into the README tables.
