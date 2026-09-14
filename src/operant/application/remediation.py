"""
The remediation memory: read/record fixes for repeated step errors.

Advisory only, like the tool learner: a matched remedy is surfaced to
the model as a hint, never forced. ``success`` reinforces a remedy that
keeps working; one hinted and followed by the same error again counts
as applied without success, and a remedy that failed twice more than it
worked is no longer offered. Hints keep no numbers and no lines that
read as instructions.

Import as:

import operant.application.remediation as remem
"""

from __future__ import annotations

import dataclasses
from typing import Dict, Optional

import operant.domain.models.memory as mdmemory
import operant.domain.remediation as odremed
import operant.ports.remediation as psremed

# A remedy that failed this many more times than it worked is not offered.
_NET_FAILURES = 2


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
        if remedy is not None and remedy.applied - remedy.success >= (
            remedy.success + _NET_FAILURES
        ):
            # Hinted again and again without helping: stop offering it.
            remedy = None
        return remedy

    def record(
        self, situation_sig: str, error_sig: str, kind: str, hint: str
    ) -> None:
        """
        Remember (or reinforce) a working remedy for the pair.
        """
        key = _key(situation_sig, error_sig)
        prior = self._remedies.get(key)
        hint = mdmemory.mask_numbers(mdmemory.memory_safe(hint))
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
        self._save()

    def record_failure(self, situation_sig: str, error_sig: str) -> None:
        """
        Count a remedy that was hinted and the same error came back.
        """
        key = _key(situation_sig, error_sig)
        prior = self._remedies.get(key)
        if prior is not None:
            self._remedies[key] = dataclasses.replace(
                prior, applied=prior.applied + 1
            )
            self._save()

    def entries(self) -> Dict[str, odremed.Remedy]:
        """
        Return every remedy by ``situation||error`` key.
        """
        return dict(self._remedies)

    def forget(self, app: str) -> int:
        """
        Delete every remedy recorded on ``app``.

        :return: How many were removed.
        """
        doomed = [k for k in self._remedies if k.startswith(f"{app}::")]
        for key in doomed:
            del self._remedies[key]
        if doomed:
            self._save()
        return len(doomed)

    def _save(self) -> None:
        """
        Write every remedy through the store.
        """
        self._store.save({k: v.as_dict() for k, v in self._remedies.items()})
