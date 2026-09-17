# 14. Graph reuse in rediscovery

Status: Accepted (implemented)

## Context

Discovery got a one-line hint and a few outgoing steps. `merge` only ever adds,
so a broken edge stayed forever and routes could use it.

Evidence:

- DeltaReplay: verbatim replay on sibling tasks reached 9%, and fallback to the
  agent handled 78% of steps.
- TAG-Nav: after a version change full records lost their benefit, while
  transition hints kept some. 22 of 48 failures were wrong retrieval, and top-k
  above 1 polluted context.
- CALM removes a transition only on evidence that it no longer exists.

## Decision

- **Route hints.** On a `match`, discovery gets the recorded route toward the
  goal: transition descriptions only, framed as data. The destination is the top
  screen whose title clearly overlaps the goal, or none.
- **Seeded rediscovery.** `operant discover --seed <capability>` starts from the
  capability's goal node. It reads the newest graph, or the pinned one if the
  newest has lost that node. A successful run starts the capability's track
  record again, because replays of the old path say nothing about the new one.
- **Retirement.** `edge_outcomes` counts each edge per version. A seeded run
  retires an edge that failed at least twice, never passed on that version, and
  was replaced by this run's route to the same destination. `retired_in` is set
  on the new version, routes skip it, and older versions keep it.

- **Manual retirement.** `operant graph retire <vendor> <edge>...` removes steps
  that record a mistake.

## Consequences

- A hint can be wrong, so the model and the live screen still decide.
- Edges only retire with positive evidence, so a transient outage cannot remove
  one on its own.

## Alternatives considered

- Fast-forwarding through known edges. Rejected: the evidence above does not
  justify forcing a route, and the arrival hop covers the useful case.
- The full CALM state machine. Per-version counts are enough for now.
