"""Deterministic replay over the capability graph. No model anywhere.

Per edge: policy check -> resolve target (ranked strategies,
param-substituted) -> act -> wait -> assert arrival at the destination
node. Outcome edges are consulted only when something is off (arrival
assert failed, locator failed, or a declared extraction came back empty),
so detectors cannot false-positive while the flow is on its recorded
path.

The public entry points are ``run_capability`` (plan a path, then run it,
with cross-domain composition) and ``replay_path`` (run an already chosen
edge list). Timing and budgets come from ``ReplayOptions``; the result is
one of the four ``operant.domain.models.results`` types.

Typical usage example:

  result = traverse.run_capability(
      capability, graph, surface, broker, log, redactor, opts
  )
"""

from __future__ import annotations

import operant.application.replay.engine as engine
import operant.application.replay.options as options
import operant.application.replay.traverse as traverse

ReplayOptions = options.ReplayOptions
OutputOrigin = options.OutputOrigin
run_capability = traverse.run_capability
replay_path = engine.replay_path

__all__ = [
    "OutputOrigin",
    "ReplayOptions",
    "replay_path",
    "run_capability",
]
