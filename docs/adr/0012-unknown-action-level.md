# 12. An unknown level for actions

Status: Accepted (implemented)

## Context

Risk had two levels, and a control no pattern named counted as `safe`. So a
button called "Proceed" that moves money ran with no approval.

- `strict` was off in every policy and covered only buttons.
- A coordinate click skipped it, because it needs a resolved control.
- Asking at every unlisted control would break discovery, whose job is to
  explore controls nobody has listed.

Evidence:

- Magentic-UI labels actions always, maybe or never irreversible, and a model
  judges the maybe group.
- Mind the Web warns that injected actions can be framed to look aligned with
  the task, so a judge cannot be the only gate.
- Arcjet warns that long approval queues turn into automatic approvals.

## Decision

Add `unknown`, with a policy setting `approval.unknown`: `allow`, `commit`,
`ask` or `deny`. All shipped policies use `commit`. The code default stays
`allow`.

### Discovery under `commit`

- These ask a person: an unlisted button while a field on screen holds a value,
  Enter with an unlisted button and a filled field, and a click that resolves
  to no control. The shape comes from the screen, never the model's words.
- Every other unknown control goes to a model judge (`agents/gate.py`), which
  answers `navigation`, `commit` or `unsure`.
- `navigation` runs. Anything else, an error or a timeout asks a person.
- The judge can only tighten: `SurfaceAction.gate_unknown` can raise a step to
  approval and has no way to lower one.
- It sees the role, the name and fenced, redacted screen text, once per control
  in a run. Every verdict is logged and stored on the edge.

### Replay

- Replay has no model, so the judge never runs there.
- An unknown step needs a person's review. Approving a capability is that
  review, in one list, and an approval during a run counts too.
- Reviews live in `edge_approvals`, keyed by edge, role and masked name. A
  renamed control asks again. Without a review, an unattended run stops.
- A person must see the list. `catalog approve` shows it and confirms, and the
  API refuses an approval that doesn't name every outstanding step on the
  current graph version. `force` skips the stability gate, never this.
- A refused step that nobody decided on fails as `unreviewed_step`. A person's
  refusal stays `approval_denied`. Neither counts against stability, and
  neither does a cancelled run: they are decisions, not breakage.
- A graph below schema 2.4 loads `safe` clicks and key presses as `unknown`,
  because `safe` only meant that no pattern fired. An approved capability on
  such a graph needs approving once more.

### Coordinate clicks

The guard hit-tests the point, so the control underneath decides. The model's
words are kept only as a description of a generic or unnamed control.

## Consequences

- A person sees more prompts at first, until safe lists fill in.
- Unknown steps on invoked graphs and path-found edges are not in the review
  list. They ask at run time, and an unattended run stops as `unreviewed_step`.
- A canary skips a capability with an unknown step the judge did not call
  `navigation`.
- A commit control the judge calls `navigation` still runs once in discovery.
  Replay review catches it afterwards, and an app can use `ask`.
  `tests/evals/test_gate.py` measures this; see `docs/EVALS.md`.

## Alternatives considered

- Turn on `strict` everywhere. Rejected: it would stop discovery at every
  unlisted button and still miss links.
- Let the judge approve steps for replay. Rejected: replay stays model-free and
  immune to on-screen injection.
