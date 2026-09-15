# 9. Locator scoring and an opt-in heal step

Status: Proposed

## Context

`locate.resolve_target` tries the recorded strategies in order and takes
the first that matches exactly one control. When none does, replay
escalates to a person.

The replay robustness suite (`tests/evals/perturb.py`) measured this
across 11 kinds of UI change on 3 screens:

- No change made replay act on a different control.
- A translated UI resolves through the tree path; a translation plus a
  layout shift escalates in 52% of steps instead of guessing.

So the current design is safe but brittle under combined changes.

Evidence:

- Similo scores every candidate on many attributes at once. It failed on
  11% of elements across releases, against 27% for single-locator
  approaches.
- Self-healing test tools follow one pattern: try healed locators
  already cached, then a model, and log every heal for review.
- AgentRR replays with a check function as the trust anchor and lets a
  small model fill gaps.

## Decision

### 1. Weighted scoring with a margin

- Score every control on the screen against all recorded attributes at
  once: name, label, role, tree path, region.
- Accept the top candidate only when it clears an absolute threshold
  and leads the runner-up by a margin; otherwise escalate as today.
- Log both scores as evidence. A shrinking margin across replays is an
  early drift signal for the stability gate (`StabilityGate`).
- The robustness suite is the acceptance test: no wrong-control actions
  are allowed, and fewer escalations than first-match on the combined
  changes.

### 2. Opt-in heal

- Off by default, and enabled per capability.
- When scoring escalates, a model chooses among the controls on the
  current screen only. Its choice then goes through the same locate and
  policy checks.
- A successful heal never edits the approved version. It writes a new
  draft version with the healed locator first; a person or the
  stability gate promotes it.
- A heal never runs on a mutating step without a person approving it.
- Heals are counted, and a capability that needs them often is flagged
  for re-discovery.

## Consequences

- Fewer escalations after UI changes while keeping the "no wrong click"
  property, which the suite enforces.
- Healing brings a model back into replay only when a capability opts
  in, so the default replay stays model-free and immune to on-screen
  injection.

## Alternatives considered

- Always heal with a model. Rejected: it makes replay cost, latency and
  injection risk unpredictable.
- Keep first-match only. That's safe, but the suite shows it escalates
  under realistic redesigns.
