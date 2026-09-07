# 4. GEPA for prompt optimization

Status: Proposed

## Context

Prompt changes are made by hand today, with no measure of whether they help.
Once the eval harness (ADR 1) scores each scenario, the same scores can
drive an optimizer.

GEPA (`pip install gepa`) improves text prompts using a reflection model.
It needs an adapter with two methods:

- `evaluate`: run a candidate prompt on a batch and return a score per
  example.
- `make_reflective_dataset`: return, per example, the inputs, the model's
  outputs, and written feedback.

## Decision

Add an opt-in GEPA runner on top of the eval harness.

- Candidate: `executor_prompt`, plus `planner_prompt` and `verifier_prompt`
  in multi mode (ADR 3).
- A `prompt_overrides` field on the discovery config lets a run use a
  candidate prompt. Production defaults do not change.
- Score: the fraction of checks a scenario passed.
- Feedback: the check failure strings, for example "filled the password
  without a secret reference".
- Guard: a candidate that drops a required placeholder (`{secret_names}`,
  `{default_browser}`) scores 0.
- Data: the skinned scenario instances, split into train and validation
  with a fixed seed. ParaBank-like instances are validation only.
- Runner: `scripts/optimize_prompt.py`. The reflection model defaults to
  Claude Opus. The budget is `OPERANT_GEPA__BUDGET`.
- Output goes to `state/gepa/<timestamp>/`: the best prompts, a diff
  against the source, and per-candidate scores.
- The runner never edits source files. A person reviews the diff, applies
  it, and re-runs the eval trials.

## Consequences

- Prompt changes come with a measured before and after.
- Runs cost model calls. The runner is opt-in and never runs in CI.
- With few scenarios, the prompt could overfit. The skins and the held-out
  validation set reduce this.

## Alternatives considered

- DSPy with GEPA. Rejected: it would mean rewriting the loop as DSPy
  modules.
- Manual prompt tuning only. Rejected: no measure of improvement.
