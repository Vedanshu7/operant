"""
Replay options: what a run needs and the timing knobs it runs under.

The timing and budget fields default to the literals the engine has
always used; a composition root may populate them from
``operant.infra.settings.EngineSettings`` (its fields line up one-to-
one), but the replay package itself depends only on ``domain`` and
``ports``, so the settings object never crosses this seam.
``total_timeout_s`` excludes human wait time: the deadline is pushed
forward by however long a human held the run (see the engine's
``waited_s`` handling).

Import as:

import operant.application.replay.options as options
"""

from __future__ import annotations

import dataclasses
from typing import Dict, Optional

# #############################################################################
# OutputOrigin
# #############################################################################


@dataclasses.dataclass(frozen=True)
class OutputOrigin:
    """
    Where an extracted value came from.

    Typing a value into another vendor's app is an export, and its class
    decides whether a human must approve that.

    :ivar vendor_id: Vendor the value was extracted in.
    :ivar data_class: Sensitivity class assigned when it was extracted.
    """

    vendor_id: str
    data_class: str


# #############################################################################
# ReplayOptions
# #############################################################################


@dataclasses.dataclass
class ReplayOptions:
    """
    Everything one replay needs, plus the timing it runs under.

    :ivar tenant: Tenant binding to resolve base URL and secrets
        against.
    :ivar params: Task inputs keyed by name.
    :ivar inject_session_expiry_before: Edge id before which to force a
        session-expiry fault (test infra); cleared once fired.
    :ivar total_timeout_s: Wall-clock budget; human wait time is
        excluded.
    :ivar output_origins: Origins of outputs handed down by a calling
        graph (the traversal layer fills this on invoke).
    :ivar poll_interval_s: Delay between node-arrival polls.
    :ivar recovery_budget: Recover/escalate outcome edges allowed per
        edge.
    :ivar retry_delay_s: Pause before retrying a locator or edge.
    :ivar settle_ms: Arrival-poll floor after an action.
    :ivar settle_short_ms: Settle-wait cap after an action.
    :ivar goal_poll_s: Time to wait for the goal node at end of run.
    """

    tenant: str
    params: Dict[str, str]
    inject_session_expiry_before: Optional[str] = None
    total_timeout_s: float = 240.0
    output_origins: Dict[str, OutputOrigin] = dataclasses.field(
        default_factory=dict
    )
    poll_interval_s: float = 0.6
    recovery_budget: int = 2
    retry_delay_s: float = 1.5
    settle_ms: int = 4000
    settle_short_ms: int = 2000
    goal_poll_s: float = 6.0
