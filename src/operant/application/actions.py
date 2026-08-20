"""
The one place that builds the paired surface/recorded action.

Discovery (from LLM tool args), the drive REPL (from typed commands),
and replay (from a graph edge) all need the same primitives built the
same way, or a demonstrated capability replays differently from a
discovered one. Each builder returns an ``ActionPair``: the
``SurfaceAction`` the surface executes and the ``Action`` the recorder
stores. This is a pure builder - it never performs.

Import as:

import operant.application.actions as actions
"""

from __future__ import annotations

import dataclasses
from typing import Optional

import operant.application.secrets as assecret
import operant.domain.models.actions as actions
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets

# #############################################################################
# ActionPair
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ActionPair:
    """
    A surface action paired with the edge action to record.

    :ivar surface: What the gateway executes now.
    :ivar recorded: What the recorder stores on the edge; ``None`` for
        actions that are performed but not recorded.
    """

    surface: actions.SurfaceAction
    recorded: Optional[graph.Action]


# #############################################################################
# ActionFactory
# #############################################################################


class ActionFactory:
    """
    Build action pairs for every primitive.

    :ivar secrets: Resolver used by ``fill_secret``; optional when no
        secret fills are needed.
    """

    def __init__(self, secrets: Optional[assecret.SecretResolver] = None) -> None:
        self._secrets = secrets

    def launch(
        self, app: Optional[str], url: Optional[str], *, step: str = ""
    ) -> ActionPair:
        """
        Build a launch of ``app`` at ``url``.
        """
        pair = ActionPair(
            actions.SurfaceAction(kind="launch", app=app, url=url, step=step),
            graph.Action(kind="launch", app=app, url=url),
        )
        return pair

    def click(self, ref: str, *, step: str = "") -> ActionPair:
        """
        Build a click on the control ``ref``.
        """
        pair = ActionPair(
            actions.SurfaceAction(kind="click", ref=ref, step=step),
            graph.Action(kind="click"),
        )
        return pair

    def click_at(self, x: float, y: float, *, step: str = "") -> ActionPair:
        """
        Build a vision-grounded click at window-normalised ``x``/``y``.
        """
        pair = ActionPair(
            actions.SurfaceAction(kind="click", x=x, y=y, step=step),
            graph.Action(kind="click"),
        )
        return pair

    def fill(
        self,
        ref: str,
        value: str,
        *,
        data_class: str = "none",
        export_from: Optional[str] = None,
        recorded_value: Optional[targets.Value] = None,
        step: str = "",
    ) -> ActionPair:
        """
        Build a fill of ``ref`` with a literal or parameterised value.

        :param ref: Target control handle.
        :param value: Text to type now.
        :param data_class: Sensitivity tag for the guard.
        :param export_from: Vendor a cross-app value came from.
        :param recorded_value: The ``Value`` to store on the edge;
            defaults to a literal of ``value``.
        :param step: Edge id, for the approval question.
        """
        pair = ActionPair(
            actions.SurfaceAction(
                kind="fill",
                ref=ref,
                value=value,
                data_class=data_class,
                export_from=export_from,
                step=step,
            ),
            graph.Action(
                kind="fill",
                value=recorded_value or targets.Value(literal=value),
            ),
        )
        return pair

    def fill_secret(self, ref: str, name: str, *, step: str = "") -> ActionPair:
        """
        Build a fill of ``ref`` from the tenant secret ``name``.

        The value is resolved and typed now; only the reference name is
        recorded, so the secret never enters an artifact.

        :raises RuntimeError: If the factory has no secret resolver.
            operant.domain.errors.SecretNotFoundError: If ``name`` is
            unknown to the tenant or the store.
        """
        if self._secrets is None:
            raise RuntimeError("no secret resolver configured")
        value = self._secrets.resolve(name)
        pair = ActionPair(
            actions.SurfaceAction(
                kind="fill",
                ref=ref,
                value=value,
                data_class="credential",
                secret_ref=name,
                step=step,
            ),
            graph.Action(kind="fill", value=targets.Value(secret_ref=name)),
        )
        return pair

    def press(self, key: str, *, step: str = "") -> ActionPair:
        """
        Build a key press.
        """
        pair = ActionPair(
            actions.SurfaceAction(kind="press", key=key, step=step),
            graph.Action(kind="press", key=key),
        )
        return pair

    def select(
        self,
        ref: str,
        option: str,
        *,
        data_class: str = "none",
        export_from: Optional[str] = None,
        recorded_value: Optional[targets.Value] = None,
        step: str = "",
    ) -> ActionPair:
        """
        Build a selection of ``option`` in the control ``ref``.
        """
        pair = ActionPair(
            actions.SurfaceAction(
                kind="select",
                ref=ref,
                option=option,
                data_class=data_class,
                export_from=export_from,
                step=step,
            ),
            graph.Action(
                kind="select",
                option=recorded_value or targets.Value(literal=option),
            ),
        )
        return pair

    def scroll(
        self, ref: Optional[str], direction: str, amount: int, *, step: str = ""
    ) -> ActionPair:
        """
        Build a scroll in ``direction`` by ``amount`` notches.
        """
        pair = ActionPair(
            actions.SurfaceAction(
                kind="scroll",
                ref=ref,
                direction=direction,
                amount=amount,
                step=step,
            ),
            graph.Action(
                kind="scroll",
                direction=direction,
                amount=amount,
            ),
        )
        return pair
