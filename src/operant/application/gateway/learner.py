"""
The learn layer: the gateway remembers which tool worked and tries it first.

The dispatcher's journal becomes memory. The first time the agent fills
a field on a page, the chain is explored top-to-bottom and the winner is
recorded against a compact signature of the situation; later, the
learned tool leads the chain. Learning is advisory only - it reorders
the chain, never shrinks it - so a stale preference degrades to the full
chain, not a failure. Persistence goes through a ``PreferenceStore`` so
the mechanism has no file I/O of its own.

Import as:

import operant.application.gateway.learner as gllearne
"""

from __future__ import annotations

import re
from typing import List, Optional

import operant.domain.models.actions as actions
import operant.ports.learning as learning

_TITLE_TAIL = re.compile(r"\s*[-|].*$")
_DIGITS = re.compile(r"\d+")


def signature(action: actions.SurfaceAction, app: str, window_title: str) -> str:
    """
    Build a coarse, stable key for an action on a kind of target.

    The app, the page (title with volatile tails and digits stripped so
    it generalises across records), the action kind, and the target's
    role - never the value - so what is learned for one account's field
    applies to the next.

    :param action: The action being dispatched.
    :param app: The owning application.
    :param window_title: The current window title.
    :return: The signature string.
    """
    page = _TITLE_TAIL.sub("", window_title)
    page = _DIGITS.sub("#", page).strip().lower()
    role = ""
    if action.target_text:
        role = action.target_text.split(" | ")[0][:24].lower()
    sig = f"{app}::{page}::{action.kind}::{role}"
    return sig


# #############################################################################
# ToolLearner
# #############################################################################


class ToolLearner:
    """
    Read and updates learned tool preferences through a store.
    """

    def __init__(self, store: learning.PreferenceStore) -> None:
        self._store = store
        self._prefs = store.load()

    def preferred(self, sig: str) -> Optional[str]:
        """
        Return the learned tool for ``sig``, or ``None``.
        """
        pref = self._prefs.get(sig)
        return pref

    def record(self, sig: str, tool: str) -> bool:
        """
        Remembers the winning tool for ``sig``.

        :param sig: The situation signature.
        :param tool: The tool that succeeded.
        :return:``True`` if this changed the learned preference (worth
            logging).
        """
        changed = self._prefs.get(sig) != tool
        if changed:
            self._prefs[sig] = tool
            self._store.save(dict(self._prefs))
        return changed

    def order_chain(self, sig: str, tool_names: List[str]) -> List[str]:
        """
        Return the chain with the learned tool moved to the front.
        """
        preferred = self._prefs.get(sig)
        if preferred and preferred in tool_names:
            # Learned tool still in the chain: lead with it.
            ordered = [preferred, *(t for t in tool_names if t != preferred)]
        else:
            # No usable preference: keep the chain as given.
            ordered = tool_names
        return ordered
