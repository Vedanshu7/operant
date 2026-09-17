"""
The learn layer: the gateway remembers which tool worked and tries it first.

The dispatcher's journal becomes memory. Each tool that works or fails
on a situation is counted against a compact signature of it; later, the
chain is ordered by each tool's smoothed success rate there, so one lucky
win does not outrank a tool that keeps working. Learning is advisory only
- it reorders the chain, never shrinks it - so a stale preference
degrades to the full chain, not a failure. Persistence goes through a
``PreferenceStore`` so the mechanism has no file I/O of its own.

Import as:

import operant.application.gateway.learner as gllearne
"""

from __future__ import annotations

import re
from typing import Dict, Final, List, Optional

import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.ports.learning as learning

_TITLE_TAIL = re.compile(r"\s*[-|].*$")
# Separates the parts of a signature; an unknown app leaves it leading.
_SEP: Final = "::"
_DIGITS = re.compile(r"\d+")
_NAME_CHARS = 24


def belongs_to(key: str, app: str) -> bool:
    """
    Report whether a signature, or a key built on one, is ``app``'s.
    """
    owned = key.startswith(f"{app}{_SEP}")
    return owned


def signature(
    action: actions.SurfaceAction,
    app: str,
    screen: Optional[digest.ScreenDigest],
) -> str:
    """
    Build a coarse, stable key for an action on a kind of target.

    The app, the page (title with volatile tails and digits stripped so
    it generalises across records), the action kind, and the target: the
    control's role and name with digits masked, ``point`` for a click at
    a coordinate, nothing for actions without a target. Never the value
    and never the model's wording, so what is learned for one account's
    link applies to the next.

    :param action: the action being dispatched.
    :param app: the owning application; the screen's app when empty.
    :param screen: the screen the action runs on, when known.
    :return: the signature string; it starts with ``::`` when the app is
        unknown, and such signatures are never learned.
    """
    title = screen.window_title if screen is not None else ""
    page = _DIGITS.sub("#", _TITLE_TAIL.sub("", title)).strip().lower()
    owner = app or (screen.app if screen is not None else "")
    sig = _SEP.join((owner, page, action.kind, _target(action, screen)))
    return sig


def _target(
    action: actions.SurfaceAction, screen: Optional[digest.ScreenDigest]
) -> str:
    """
    Describe the action's target by role and masked name.
    """
    control = (
        next((c for c in screen.controls if c.ref == action.ref), None)
        if screen is not None and action.ref
        else None
    )
    if control is not None:
        name = _DIGITS.sub("#", (control.name or control.label).lower())
        target = f"{control.role}:{name[:_NAME_CHARS].strip()}"
    elif action.ref:
        target = "control"
    elif action.x is not None and action.y is not None:
        target = "point"
    else:
        target = ""
    return target


# #############################################################################
# ToolLearner
# #############################################################################


class ToolLearner:
    """
    Count tool outcomes per situation and order chains by them.
    """

    def __init__(self, store: learning.PreferenceStore) -> None:
        self._store = store
        self._counts = store.load()

    def preferred(self, sig: str) -> Optional[str]:
        """
        Return the tool with the best record for ``sig``, or ``None``.
        """
        tools = self._counts.get(sig, {})
        best = max(tools, key=lambda name: _rate(tools[name]), default=None)
        return best

    def record(self, sig: str, tool: str, *, ok: bool = True) -> bool:
        """
        Count one outcome of ``tool`` on ``sig``.

        :param sig: the situation signature.
        :param tool: the tool that ran.
        :param ok: whether it worked.
        :return: ``True`` if this changed which tool leads (worth
            logging).
        """
        if sig.startswith(_SEP):
            # Unknown app: a key shared by every app would mislead them all.
            return False
        before = self.preferred(sig)
        tools = self._counts.setdefault(sig, {})
        counts = tools.setdefault(tool, [0, 0])
        counts[0 if ok else 1] += 1
        self._store.save(self._counts)
        return self.preferred(sig) != before

    def order_chain(self, sig: str, tool_names: List[str]) -> List[str]:
        """
        Return the chain ordered by success rate on ``sig``.

        Untried tools rate as even; ties keep the configured order.
        """
        tools = self._counts.get(sig, {})
        ordered = sorted(
            tool_names, key=lambda name: -_rate(tools.get(name, [0, 0]))
        )
        return ordered

    def entries(self) -> Dict[str, Dict[str, List[int]]]:
        """
        Return every signature's ``{tool: [worked, failed]}`` counts.
        """
        return {sig: dict(tools) for sig, tools in self._counts.items()}

    def forget(self, app: str) -> int:
        """
        Delete every signature learned on ``app``.

        :return: how many were removed.
        """
        doomed = [sig for sig in self._counts if belongs_to(sig, app)]
        for sig in doomed:
            del self._counts[sig]
        if doomed:
            self._store.save(self._counts)
        return len(doomed)


def _rate(counts: List[int]) -> float:
    """
    Laplace-smoothed success rate of ``[worked, failed]`` counts.
    """
    return (counts[0] + 1) / (counts[0] + counts[1] + 2)
