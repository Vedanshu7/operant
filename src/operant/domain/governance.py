"""
The approval gate that decides when a capability may replay unattended.

One rule, one place: the artifact store, the catalog, and the audit all
ask ``StabilityGate`` rather than re-implementing the threshold.

Import as:

import operant.domain.governance as govern
"""

from __future__ import annotations

import dataclasses

import operant.domain.models.artifact as artifact

# #############################################################################
# StabilityGate
# #############################################################################


@dataclasses.dataclass(frozen=True)
class StabilityGate:
    """
    The evidence a capability needs to gain and keep approval.

    Judged over the most recent replays only: a lifetime count kept a
    capability with many old successes approved through a run of
    failures after the application's UI changed.

    :ivar min_runs: replays required before approval is possible.
    :ivar min_success_rate: required ratio of successful replays.
    :ivar window: how many recent replays the gate judges.
    :ivar max_consecutive_failures: failed replays in a row that
        degrade an approved capability.
    """

    min_runs: int = 3
    min_success_rate: float = 0.8
    window: int = 20
    max_consecutive_failures: int = 3

    def degrades(self, stability: artifact.Stability) -> bool:
        """
        Report whether the track record should revoke an approval.

        :param stability: the recent track record.
        :return: ``True`` after too many failed replays in a row.
        """
        degraded = stability.consecutive_failures >= self.max_consecutive_failures
        return degraded

    def passes(self, runs: int, successes: int) -> bool:
        """
        Report whether the recorded replays satisfy the gate.

        :param runs: total replays recorded.
        :param successes: replays that ended in success or a business
            outcome.
        :return: ``True`` when both thresholds are met.
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
