"""
The approval gate that decides when a capability may replay unattended.

One rule, one place: the artifact store, the catalog, and the audit all
ask ``StabilityGate`` rather than re-implementing the threshold.

Import as:

import operant.domain.governance as govern
"""

from __future__ import annotations

import dataclasses

# #############################################################################
# StabilityGate
# #############################################################################


@dataclasses.dataclass(frozen=True)
class StabilityGate:
    """
    Minimum evidence before a capability can be approved.

    :ivar min_runs: Replays required before approval is possible.
    :ivar min_success_rate: Required ratio of successful replays.
    """

    min_runs: int = 3
    min_success_rate: float = 0.8

    def passes(self, runs: int, successes: int) -> bool:
        """
        Report whether the recorded replays satisfy the gate.

        :param runs: Total replays recorded.
        :param successes: Replays that ended in success or a business
            outcome.
        :return:``True`` when both thresholds are met.
        """
        if runs < self.min_runs:
            ok = False
        else:
            ok = successes / runs >= self.min_success_rate
        return ok

    def describe(self, runs: int, successes: int) -> str:
        """
        Explain the gate result in one line for humans and logs.
        """
        rate = f"{successes}/{runs}" if runs else "0/0"
        requirement = f">={self.min_runs} runs at >={self.min_success_rate:.0%}"
        verdict = "passes" if self.passes(runs, successes) else "fails"
        line = f"stability {rate} {verdict} the gate ({requirement})"
        return line
