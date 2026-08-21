"""
The remediation memory: read/record fixes for repeated step errors.

Advisory only, like the tool learner: a matched remedy is surfaced to
the model as a hint, never forced. ``success`` reinforces a remedy that
keeps working; a stale one simply stops being reinforced.

Import as:

import operant.application.remediation as remem
"""

from __future__ import annotations

from typing import Optional

import operant.domain.remediation as odremed
import operant.ports.remediation as psremed


def _key(situation_sig: str, error_sig: str) -> str:
    """
    Build the store key for a situation/error pair.
    """
    key = f"{situation_sig}||{error_sig}"
    return key


# #############################################################################
# RemediationMemory
# #############################################################################


class RemediationMemory:
    """
    Read and record step remedies through a store.
    """

    def __init__(self, store: psremed.RemediationStore) -> None:
        self._store = store
        self._remedies = {
            key: odremed.Remedy.from_dict(value)
            for key, value in store.load().items()
        }

    def query(
        self, situation_sig: str, error_sig: str
    ) -> Optional[odremed.Remedy]:
        """
        Return a remembered remedy for the pair, or ``None``.
        """
        remedy = self._remedies.get(_key(situation_sig, error_sig))
        return remedy

    def record(
        self, situation_sig: str, error_sig: str, kind: str, hint: str
    ) -> None:
        """
        Remember (or reinforce) a working remedy for the pair.
        """
        key = _key(situation_sig, error_sig)
        prior = self._remedies.get(key)
        if prior is not None:
            # Seen before: reinforce the remembered remedy's counts.
            remedy = odremed.Remedy(
                kind=kind,
                hint=hint,
                applied=prior.applied + 1,
                success=prior.success + 1,
            )
        else:
            # First sighting of this pair: store a fresh remedy.
            remedy = odremed.Remedy(kind=kind, hint=hint)
        self._remedies[key] = remedy
        self._store.save({k: v.as_dict() for k, v in self._remedies.items()})
